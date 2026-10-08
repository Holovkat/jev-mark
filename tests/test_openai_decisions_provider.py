import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import openai_decisions_provider as provider


class DecisionsProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = {'credentials_path': '/app/own-grant.json', 'model': 'gpt-6-luna',
                       'reasoning_effort': 'medium'}
        self.questions = {
            'choose': {'type': 'choice', 'instructions': {'task': 'Choose carefully'},
                       'criteria': {'"Quoted" café': {'description': 'Keep \\ and " exactly'}, 'no': 'Reject'}},
            'rate': {'type': 'score', 'instructions': 'Rate', 'criteria': ['bad', {'description': 'good'}]},
            'check': {'type': 'noul', 'instructions': 'Is it valid?',
                      'criteria': {'true': {'rule': 'Valid'}, 'false': 'Invalid'}}}
        self.native = {'answers': [
            {'name': 'choose', 'type': 'choice', 'choice': '"Quoted" café', 'confidence': .61,
             'probabilities': [{'value': '"Quoted" café', 'probability': .8}, {'value': 'no', 'probability': .2}]},
            {'name': 'rate', 'type': 'score', 'score': .71, 'confidence': .72,
             'probabilities': [{'value': 0, 'label': '0', 'probability': .3},
                               {'value': 1, 'label': '1', 'probability': .7}]},
            {'name': 'check', 'type': 'predicate', 'probability': .9}],
            'usage': {'input_tokens': 12}}
        self.token_patch = patch.object(provider, 'access_token', return_value='own-chatgpt-token')
        self.token = self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def invoke(self, native=None):
        transport = Mock(return_value=io.BytesIO(json.dumps(self.native if native is None else native).encode()))
        result = provider.call(self.config, {'candidate': 'Evidence'}, self.questions, transport=transport)
        return result, transport

    def test_native_request_and_normalized_results(self):
        result, transport = self.invoke()
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/decisions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer own-chatgpt-token')
        self.token.assert_called_once_with('/app/own-grant.json')
        body = json.loads(request.data)
        self.assertEqual(set(body), {'model', 'input', 'questions'})
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertEqual(json.loads(body['input']), {'candidate': 'Evidence'})
        native_questions = body['questions']
        self.assertEqual([q['name'] for q in native_questions], list(self.questions))
        self.assertEqual(json.loads(native_questions[0]['instructions']), self.questions['choose']['instructions'])
        self.assertEqual(native_questions[0]['choices'][0]['value'], '"Quoted" café')
        self.assertEqual(json.loads(native_questions[0]['choices'][0]['description']),
                         self.questions['choose']['criteria']['"Quoted" café'])
        self.assertEqual(native_questions[1]['levels'][1]['label'], '1')
        self.assertEqual(json.loads(native_questions[1]['levels'][1]['description']), {'description': 'good'})
        self.assertEqual(native_questions[2]['type'], 'predicate')
        self.assertIn(json.dumps(self.questions['check']['criteria'], ensure_ascii=False),
                      native_questions[2]['instructions'])
        self.assertEqual(result['answers']['choose'], {'type': 'choice', 'choice': '"Quoted" café',
                         'probabilities': {'"Quoted" café': .8, 'no': .2}, 'confidence': .61})
        # Native score/confidence are preserved, not replaced with local estimates.
        self.assertEqual(result['answers']['rate'], {'type': 'score', 'score': .71,
                         'probabilities': {'0': .3, '1': .7}, 'confidence': .72})
        self.assertEqual(result['answers']['check'], {'type': 'noul', 'noul': .9})
        self.assertEqual(result['usage'], {'input_tokens': 12})

    def test_http401_is_preserved_without_fallback(self):
        error = HTTPError(provider.ENDPOINT, 401, 'Unauthorized', {},
                          io.BytesIO(b'{"code":"no_matching_rule"}'))
        self.addCleanup(error.close)
        transport = Mock(side_effect=error)
        with patch.object(provider, 'urlopen') as default_transport:
            with self.assertRaises(HTTPError) as raised:
                provider.call(self.config, 'Evidence', self.questions, transport=transport)
        self.assertIs(raised.exception, error)
        self.assertEqual(raised.exception.read(), b'{"code":"no_matching_rule"}')
        transport.assert_called_once()
        default_transport.assert_not_called()

    def test_refusal_is_explicit_failure(self):
        native = copy.deepcopy(self.native)
        native['answers'][0] = {'type': 'refusal', 'name': 'choose'}
        with self.assertRaisesRegex(RuntimeError, 'refused'):
            self.invoke(native)

    def test_malformed_responses_fail_safely(self):
        mutations = [
            lambda r: r['answers'].pop(),
            lambda r: r['answers'].reverse(),
            lambda r: r['answers'][0].update(name='wrong'),
            lambda r: r['answers'][0].update(type='predicate'),
            lambda r: r['answers'][0].update(choice='unknown'),
            lambda r: r['answers'][0].pop('confidence'),
            lambda r: r['answers'][0].update(confidence=True),
            lambda r: r['answers'][0]['probabilities'][1].update(value='"Quoted" café'),
            lambda r: r['answers'][0]['probabilities'][1].update(probability=.9),
            lambda r: r['answers'][1]['probabilities'][0].update(label='wrong'),
            lambda r: r['answers'][1]['probabilities'][0].update(value=False),
            lambda r: r['answers'][1].update(score=20),
            lambda r: r['answers'][2].update(probability=float('nan')),
            lambda r: r.update(usage=[]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                native = copy.deepcopy(self.native)
                mutation(native)
                with self.assertRaises(RuntimeError):
                    self.invoke(native)
        for native in ([], {}, {'answers': {}}, {'answers': [None] * 3}):
            with self.assertRaises(RuntimeError):
                self.invoke(native)

    def test_endpoint_and_model_cannot_redirect_credentials(self):
        for field, value in [('endpoint', 'https://other.example/decisions'), ('model', 'gpt-6.1-sol')]:
            config = {**self.config, field: value}
            with self.assertRaises(RuntimeError):
                provider.call(config, 'Evidence', self.questions)
        self.token.assert_not_called()

    def test_unreadable_response_is_safe_failure(self):
        for raw in (b'not json containing private text', b'\xff'):
            with self.subTest(raw=raw):
                transport = Mock(return_value=io.BytesIO(raw))
                with self.assertRaisesRegex(RuntimeError, '^Decisions returned unreadable answers$'):
                    provider.call(self.config, 'Evidence', self.questions, transport=transport)

    def test_invalid_questions_fail_before_authentication(self):
        for questions in ({}, {'x': {'type': 'choice', 'criteria': []}},
                          {'x': {'type': 'score', 'criteria': ['only']}},
                          {'x': {'type': 'noul', 'criteria': {'other': 'bad'}}},
                          {'x': {'type': 'unknown'}}):
            with self.assertRaises(RuntimeError):
                provider.call(self.config, 'Evidence', questions)
        self.token.assert_not_called()


if __name__ == '__main__':
    unittest.main()
