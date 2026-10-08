import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import openai_chatgpt_provider as provider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'openai-chatgpt.json'
        self.record = {'access_token': 'private-token', 'refresh_token': 'old-refresh',
                       'scope': 'openid chatgpt.tokens.use.direct', 'saved_at': time.time(),
                       'expires_in': 3600, 'client_id': 'issued-client', 'subject': 'owner',
                       'ext_agent_host_id': 'urn:uuid:host'}
        provider._save_record(self.path, self.record)
        self.config = {'credentials_path': str(self.path), 'model': 'gpt-6-luna', 'reasoning_effort': 'medium'}
        self.questions = {
            'choice': {'type': 'choice', 'instructions': 'Choose', 'criteria': {'yes': 'Accept', 'no': 'Reject'}},
            'score': {'type': 'score', 'instructions': 'Score', 'criteria': ['bad', 'good']},
            'noul': {'type': 'noul', 'instructions': 'Is it valid?'}}
        self.answers = {
            'choice': {'type': 'choice', 'choice': 'yes', 'probabilities': {'yes': .8, 'no': .2}, 'confidence': .7},
            'score': {'type': 'score', 'score': .7, 'probabilities': {'0': .3, '1': .7}, 'confidence': .8},
            'noul': {'type': 'noul', 'noul': .9}}

    @staticmethod
    def stream(events):
        return io.BytesIO(b''.join(('data: ' + json.dumps(event) + '\r\n\r\n').encode() for event in events))

    def success(self, answers=None):
        encoded = json.loads(json.dumps(answers if answers is not None else self.answers))
        for name, answer in encoded.items():
            if answer['type'] == 'choice':
                options = {label: f'o{index}' for index, label in enumerate(self.questions[name]['criteria'])}
                answer['choice'] = options.get(answer['choice'], answer['choice'])
                answer['probabilities'] = {options.get(label, label): value
                                           for label, value in answer['probabilities'].items()}
        text = json.dumps({'answers': encoded})
        return [{'type': 'response.output_text.delta', 'delta': text[:13]},
                {'type': 'response.output_text.delta', 'delta': text[13:]},
                {'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 12, 'output_tokens': 34}}}]

    def test_native_answers_and_official_request_contract(self):
        with patch.object(provider, 'urlopen') as refresh:
            transport = unittest.mock.Mock(return_value=self.stream(self.success()))
            result = provider.call(self.config, {'candidate': 'state evidence'}, self.questions, transport=transport)
        refresh.assert_not_called()
        self.assertEqual(result, {'answers': self.answers, 'usage': {'input_tokens': 12, 'output_tokens': 34}})
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, provider.API + '/responses')
        self.assertEqual(request.get_header('Authorization'), 'Bearer private-token')
        body = json.loads(request.data)
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertEqual(body['reasoning'], {'effort': 'medium'})
        self.assertFalse(body['store'])
        self.assertTrue(body['stream'])
        self.assertEqual(body['input'][0]['role'], 'developer')
        self.assertEqual(json.loads(body['input'][1]['content'])['questions'], self.questions)
        self.assertTrue(body['text']['format']['strict'])
        self.assertNotIn('api_key', body)

    def test_schema_has_strict_objects_and_native_ranges(self):
        schema = provider.answer_schema(self.questions)
        def check(node):
            if node['type'] == 'object':
                self.assertFalse(node['additionalProperties'])
                self.assertEqual(set(node['required']), set(node['properties']))
                for child in node['properties'].values():
                    check(child)
        check(schema)
        answers = schema['properties']['answers']['properties']
        self.assertEqual(answers['choice']['properties']['choice']['enum'], ['o0', 'o1'])
        self.assertEqual(answers['choice']['properties']['probabilities']['required'], ['o0', 'o1'])
        self.assertEqual(answers['score']['properties']['score']['maximum'], 1)
        self.assertEqual(answers['score']['properties']['probabilities']['required'], ['0', '1'])
        self.assertEqual(answers['noul']['required'], ['type', 'noul'])
        with_criteria = {'predicate': {'type': 'noul', 'criteria': {'true': 'Valid', 'false': 'Invalid'}}}
        self.assertIn('predicate', provider.answer_schema(with_criteria)['properties']['answers']['properties'])

    def test_choice_labels_roundtrip_without_entering_strict_schema(self):
        labels = ['Use "quoted" answer\nnext line\\path 雪', 'o0', '', '{"nested":true}']
        criteria = {label: {'instructions': 'Preserve \\ evidence "exactly"', 'weight': index}
                    for index, label in enumerate(labels)}
        self.questions['choice']['criteria'] = criteria
        self.questions['choice']['instructions'] = 'Choose using the original structured criteria'
        self.answers['choice'].update(choice=labels[0], probabilities=dict(zip(labels, [.7, .1, .1, .1])))
        original = json.loads(json.dumps(self.questions))
        state = {'evidence': ['Quoted "text"', {'nested': 'Unicode 雪'}]}
        transport = unittest.mock.Mock(return_value=self.stream(self.success()))
        result = provider.call(self.config, state, self.questions, transport=transport)
        self.assertEqual(result['answers'], self.answers)
        self.assertEqual(self.questions, original)
        body = json.loads(transport.call_args.args[0].data)
        data = json.loads(body['input'][1]['content'])
        self.assertEqual(data['questions'], original)
        self.assertEqual(data['state'], state)
        self.assertEqual(data['choice_options'], {'choice': {f'o{index}': label for index, label in enumerate(labels)}})
        schema = body['text']['format']['schema']['properties']['answers']['properties']['choice']['properties']
        self.assertEqual(schema['choice']['enum'], ['o0', 'o1', 'o2', 'o3'])
        self.assertEqual(list(schema['probabilities']['properties']), ['o0', 'o1', 'o2', 'o3'])
        self.assertNotIn(labels[0], json.dumps(body['text']['format']['schema'], ensure_ascii=False))

    def test_choice_identifiers_are_scoped_to_each_question(self):
        self.questions['another'] = {'type': 'choice', 'criteria': {'different': 'First', 'second': 'Second'}}
        self.answers['another'] = {'type': 'choice', 'choice': 'second',
                                   'probabilities': {'different': .2, 'second': .8}, 'confidence': .6}
        transport = unittest.mock.Mock(return_value=self.stream(self.success()))
        result = provider.call(self.config, {}, self.questions, transport=transport)
        self.assertEqual(result['answers'], self.answers)
        data = json.loads(json.loads(transport.call_args.args[0].data)['input'][1]['content'])
        self.assertEqual(data['choice_options']['another'], {'o0': 'different', 'o1': 'second'})

    def test_original_labels_in_model_output_are_rejected_before_restoration(self):
        events = [{'type': 'response.output_text.delta', 'delta': json.dumps({'answers': self.answers})},
                  {'type': 'response.completed'}]
        transport = unittest.mock.Mock(return_value=self.stream(events))
        with self.assertRaisesRegex(RuntimeError, 'invalid answer'):
            provider.call(self.config, {}, self.questions, transport=transport)

    def test_late_failure_incomplete_error_and_refusal_fail(self):
        for kind in ('response.failed', 'response.incomplete', 'error', 'response.refusal.delta'):
            with self.subTest(kind=kind):
                events = self.success() + [{'type': kind, 'error': {'message': 'private token leaked upstream'}}]
                with patch.object(provider, 'urlopen', return_value=self.stream(events)):
                    with self.assertRaisesRegex(RuntimeError, 'failed or was refused') as raised:
                        provider.call(self.config, {}, self.questions)
                self.assertNotIn('private token', str(raised.exception))

    def test_normalizes_score_and_choice_from_validated_distribution(self):
        answers = json.loads(json.dumps(self.answers))
        answers['score'].update(score=0, probabilities={'0': .99, '1': .01})
        answers['choice']['choice'] = 'no'
        with patch.object(provider, 'urlopen', return_value=self.stream(self.success(answers))):
            result = provider.call(self.config, {}, self.questions)
        self.assertEqual(result['answers']['score']['score'], .01)
        self.assertEqual(result['answers']['choice']['choice'], 'yes')

    def test_requires_completed_and_valid_json(self):
        for events in (self.success()[:-1], [{'type': 'response.completed'}],
                       [{'type': 'response.output_text.delta', 'delta': '{'}, {'type': 'response.completed'}]):
            with self.subTest(events=events), patch.object(provider, 'urlopen', return_value=self.stream(events)):
                with self.assertRaises(RuntimeError):
                    provider.call(self.config, {}, self.questions)

    def test_rejects_malformed_native_answers(self):
        for mutate in (lambda a: a.pop('noul'), lambda a: a['choice'].update(choice='unknown'),
                       lambda a: a['choice'].update(confidence=True),
                       lambda a: a['score'].update(score=2),
                       lambda a: a['choice'].update(probabilities={'yes': .1, 'no': .2}),
                       lambda a: a['noul'].update(secret='extra')):
            answers = json.loads(json.dumps(self.answers))
            mutate(answers)
            with patch.object(provider, 'urlopen', return_value=self.stream(self.success(answers))):
                with self.assertRaises(RuntimeError):
                    provider.call(self.config, {}, self.questions)

    def test_http_error_is_preserved_without_fallback(self):
        error = HTTPError(provider.API, 429, 'limited', {}, io.BytesIO(b'private body'))
        with patch.object(provider, 'urlopen', side_effect=error) as upstream:
            with self.assertRaises(HTTPError) as raised:
                provider.call(self.config, {}, self.questions)
        self.assertIs(raised.exception, error)
        self.assertEqual(upstream.call_count, 1)

    def test_refresh_rotates_tokens_and_preserves_registration(self):
        provider._save_record(self.path, {**self.record, 'saved_at': 0})
        refreshed = {'access_token': 'replacement', 'refresh_token': 'new-refresh', 'expires_in': 3600,
                     'scope': self.record['scope'] + ' email', 'earliest_refresh_at': time.time() + 3500}
        with patch.object(provider, 'urlopen', return_value=io.BytesIO(json.dumps(refreshed).encode())) as upstream:
            self.assertEqual(provider.access_token(self.path), 'replacement')
            self.assertEqual(provider.access_token(self.path), 'replacement')
        self.assertEqual(upstream.call_count, 1)
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, provider.TOKEN_URL)
        self.assertEqual(parse_qs(request.data.decode()), {'grant_type': ['refresh_token'], 'client_id': ['issued-client'],
                                                         'refresh_token': ['old-refresh'], 'resource': [provider.API]})
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['subject'], 'owner')
        self.assertEqual(saved['refresh_token'], 'new-refresh')
        self.assertEqual(saved['scope'], refreshed['scope'])
        self.assertEqual(saved['earliest_refresh_at'], refreshed['earliest_refresh_at'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(str(self.path) + '.lock').stat().st_mode & 0o777, 0o600)

    def test_refresh_is_serialized_between_concurrent_calls(self):
        provider._save_record(self.path, {**self.record, 'saved_at': 0})
        refreshed = {'access_token': 'replacement', 'refresh_token': 'new-refresh', 'expires_in': 3600}
        results, errors = [], []
        def run():
            try:
                results.append(provider.access_token(self.path))
            except Exception as error:
                errors.append(error)
        def slow(_request, **_kwargs):
            time.sleep(.05)
            return io.BytesIO(json.dumps(refreshed).encode())
        with patch.object(provider, 'urlopen', side_effect=slow) as upstream:
            threads = [threading.Thread(target=run) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
        self.assertEqual(errors, [])
        self.assertEqual(results, ['replacement'] * 3)
        self.assertEqual(upstream.call_count, 1)

    def test_earliest_refresh_is_honored(self):
        now = time.time()
        with patch.object(provider, 'urlopen') as upstream:
            provider._save_record(self.path, {**self.record, 'saved_at': now - 3580, 'earliest_refresh_at': now + 100})
            self.assertEqual(provider.access_token(self.path), 'private-token')
            provider._save_record(self.path, {**self.record, 'saved_at': 0, 'earliest_refresh_at': now + 100})
            with self.assertRaisesRegex(RuntimeError, 'not available yet'):
                provider.access_token(self.path)
        upstream.assert_not_called()

    def test_refresh_failures_do_not_overwrite_saved_grant(self):
        record = {**self.record, 'saved_at': 0}
        provider._save_record(self.path, record)
        bad = [{'access_token': 'new'}, {'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 3600, 'scope': 'openid'},
               {'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 3600, 'client_id': 'other-registration'}]
        for refreshed in bad:
            with patch.object(provider, 'urlopen', return_value=io.BytesIO(json.dumps(refreshed).encode())):
                with self.assertRaises(RuntimeError):
                    provider.access_token(self.path)
            self.assertEqual(json.loads(self.path.read_text()), record)

    def test_credential_permissions_and_symlink_protection(self):
        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(RuntimeError, 'owner-only'):
            provider.access_token(self.path)
        os.chmod(self.path, 0o600)
        alias = self.path.parent / 'alias.json'
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            provider.access_token(alias)
        directory_alias = self.path.parent / 'alias-dir'
        directory_alias.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            provider.access_token(directory_alias / self.path.name)
        lock = Path(str(self.path) + '.lock')
        lock.unlink()
        lock.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            provider.access_token(self.path)

    def test_missing_scope_is_checked_on_every_call(self):
        provider._save_record(self.path, {**self.record, 'scope': 'openid'})
        with patch.object(provider, 'urlopen') as upstream:
            with self.assertRaisesRegex(RuntimeError, 'direct plan usage'):
                provider.call(self.config, {}, self.questions)
        upstream.assert_not_called()

    def test_unofficial_endpoint_never_receives_credentials(self):
        with patch.object(provider, 'urlopen') as upstream:
            with self.assertRaisesRegex(RuntimeError, 'official Responses endpoint'):
                provider.call({**self.config, 'endpoint': 'https://example.invalid'}, {}, self.questions)
        upstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
