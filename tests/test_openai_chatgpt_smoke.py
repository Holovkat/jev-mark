import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import openai_chatgpt_smoke as smoke


class SmokeTests(unittest.TestCase):
    def stream(self, events):
        return io.BytesIO(b''.join(('data: ' + json.dumps(e) + '\n\n').encode() for e in events))

    def test_success_requires_completion_and_expected_output(self):
        stream = self.stream([{'type': 'response.output_text.delta', 'delta': 'Hello, world!'},
                              {'type': 'response.completed'}])
        with patch.object(smoke, 'urlopen', return_value=stream) as upstream:
            self.assertTrue(smoke.infer('private-token', 'account-model')['completed'])
        req = upstream.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.openai.com/v1/responses')
        body = json.loads(req.data)
        self.assertFalse(body['store'])
        self.assertTrue(body['stream'])
        self.assertEqual(body['reasoning'], {'effort': 'medium'})
        self.assertIsInstance(body['input'], list)
        self.assertNotIn('temperature', body)

    def test_partial_output_is_not_success(self):
        with patch.object(smoke, 'urlopen', return_value=self.stream([
                {'type': 'response.output_text.delta', 'delta': 'Hello, world!'}])):
            with self.assertRaisesRegex(RuntimeError, 'without response.completed'):
                smoke.infer('private-token', 'account-model')

    def test_late_usage_failure_is_not_success(self):
        events = [{'type': 'response.output_text.delta', 'delta': 'Hello, world!'},
                  {'type': 'response.failed', 'response': {'error': {
                      'code': 'subscription_sharing_usage_limit_exceeded'}}}]
        with patch.object(smoke, 'urlopen', return_value=self.stream(events)):
            with self.assertRaisesRegex(RuntimeError, 'subscription_sharing_usage_limit_exceeded'):
                smoke.infer('private-token', 'account-model')

    def test_incomplete_or_error_are_not_success(self):
        for kind in ['response.incomplete', 'error']:
            with self.subTest(kind=kind), patch.object(smoke, 'urlopen', return_value=self.stream([{'type': kind}])):
                with self.assertRaises(RuntimeError):
                    smoke.infer('private-token', 'account-model')

    def test_credentials_are_private_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            path = directory / 'session.json'
            smoke.save_private(path, {'access_token': 'private-token'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            alias = directory / 'alias.json'
            alias.symlink_to(path)
            with self.assertRaises(RuntimeError):
                smoke.save_private(alias, {})
            with self.assertRaises(RuntimeError):
                smoke.read_json(alias)
            directory_alias = directory / 'directory-alias'
            directory_alias.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                smoke.read_json(directory_alias / 'session.json')
            with self.assertRaises(RuntimeError):
                smoke.save_private(directory_alias / 'other.json', {})

    def test_identity_checks_nonce_and_direct_scope(self):
        import jwt
        claims = {'sub': 'account', 'nonce': 'expected'}
        with patch.object(jwt, 'PyJWKClient'), patch.object(jwt, 'decode', return_value=claims) as decode:
            tokens = {'id_token': 'private-token', 'scope': smoke.SCOPE}
            self.assertEqual(smoke.validate_identity(tokens, 'issued-client', 'expected')['sub'], 'account')
            self.assertEqual(decode.call_args.kwargs['audience'], 'issued-client')
            self.assertEqual(decode.call_args.kwargs['issuer'], smoke.AUTH)
            with self.assertRaisesRegex(RuntimeError, 'nonce mismatch'):
                smoke.validate_identity(tokens, 'issued-client', 'wrong')
            with self.assertRaisesRegex(RuntimeError, 'permission was not granted'):
                smoke.validate_identity({**tokens, 'scope': 'openid'}, 'issued-client', 'expected')


if __name__ == '__main__':
    unittest.main()
