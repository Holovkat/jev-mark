import json
import io
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import jev_gateway as gateway


class OpenAIGatewayTests(unittest.TestCase):
    def test_observed_transport_supports_sse_iteration(self):
        from jev_service import ObservedResponse
        observation = Mock()
        with ObservedResponse(io.BytesIO(b'data: event\n\n'), observation, 0, 'gpt-6-luna') as response:
            self.assertEqual(list(response), [b'data: event\n', b'\n'])
        observation.attempt.assert_called_once()

    def test_retired_chatgpt_profiles_are_not_loaded(self):
        for endpoint in ('https://api.openai.com/v1/decisions', 'https://api.openai.com/v1/responses'):
            raw = {'id': 'openai-chatgpt-luna', 'protocol': 'openai_chatgpt',
                   'base_url': endpoint, 'api_key': 'fixture'}
            self.assertIsNone(gateway.profile(raw, 'old'))

    def test_api_key_profile_routes_native_decisions_without_exposing_credentials(self):
        config = gateway.profile({'id': 'openai-api', 'name': 'OpenAI API',
                                  'protocol': 'openai_decisions', 'model': 'gpt-6-luna',
                                  'api_key': 'sk-proj-test', 'organization_id': 'org-test',
                                  'project_id': 'proj_test',
                                  'base_url': 'https://api.openai.com/v1/decisions'}, 'fallback')
        self.assertEqual(config['protocol'], 'openai_decisions')
        self.assertEqual(config['organization_id'], 'org-test')
        self.assertEqual(gateway.remote_capabilities(config)['billing_path'], 'openai_api')
        self.assertNotIn('sk-proj-test', json.dumps(gateway.remote_capabilities(config)))
        self.assertEqual(gateway.image_capability({**config, 'image_input': 'systemone'}), 'unsupported')
        payload = {'contexts': ['The sky is blue.'], 'schema': {'blue': {'type': 'boolean'}}}
        upstream = {'answers': [{'name': 'jev_field_0', 'type': 'predicate', 'probability': .9}],
                    'usage': {'input_tokens': 12}}
        with patch.object(gateway, 'urlopen', return_value=io.BytesIO(json.dumps(upstream).encode())) as transport:
            result = gateway.call_typesafe(config, payload)
        request = transport.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer sk-proj-test')
        self.assertEqual(request.get_header('Openai-organization'), 'org-test')
        self.assertEqual(request.get_header('Openai-project'), 'proj_test')
        self.assertEqual(json.loads(request.data)['questions'][0]['type'], 'predicate')
        self.assertTrue(result['complete'])
        self.assertTrue(result['results'][0]['decision']['blue'])
        self.assertNotIn('sk-proj-test', json.dumps(result))

    def test_api_key_profile_rejects_other_endpoints_and_invalid_org(self):
        raw = {'protocol': 'openai_decisions', 'api_key': 'sk-proj-test',
               'base_url': 'https://api.openai.com/v1/decisions'}
        self.assertEqual(gateway.profile(raw, 'api')['model'], 'gpt-6-luna')
        self.assertIsNone(gateway.profile({**raw, 'base_url': 'https://example.com/v1/decisions'}, 'bad'))
        self.assertIsNone(gateway.profile({**raw, 'organization_id': 'org-test\ninjected'}, 'bad'))
        self.assertIsNone(gateway.profile({**raw, 'api_key': ''}, 'bad'))

    def test_api_key_auth_failure_reports_action_without_exposing_key(self):
        config = gateway.profile({'protocol': 'openai_decisions', 'api_key': 'sk-proj-test',
                                  'model': 'gpt-6-luna',
                                  'base_url': 'https://api.openai.com/v1/decisions'}, 'api')
        error = HTTPError(config['endpoint'], 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
        with patch.object(gateway, 'urlopen', side_effect=error):
            with self.assertRaises(gateway.GatewayError) as raised:
                gateway.call_typesafe(config, {'contexts': ['test'], 'schema': {'answer': {'type': 'boolean'}}})
        self.assertEqual(raised.exception.status, 401)
        self.assertIn('credential and organization/project access', str(raised.exception.details['failed_work']))
        self.assertNotIn('sk-proj-test', str(raised.exception.details))

    def test_benchmark_routes_api_profile_through_native_adapter(self):
        from jev_benchmarks import BenchmarkService
        config = gateway.profile({'id': 'openai-api', 'protocol': 'openai_decisions',
                                  'api_key': 'sk-proj-test', 'model': 'gpt-6-luna',
                                  'base_url': 'https://api.openai.com/v1/decisions'}, 'fallback')
        case = {'state': 'The sky is blue.', 'questions': {'blue': {'type': 'noul'}}}
        service = BenchmarkService.__new__(BenchmarkService)
        service.gateway = gateway
        with patch.object(gateway, 'call_openai', return_value={'answers': {'blue': {'type': 'noul', 'noul': .9}}}) as adapter, \
             patch.object(gateway, 'urlopen') as ordinary:
            result = service._call(config, case)
        self.assertEqual(result['status'], 'complete')
        adapter.assert_called_once()
        ordinary.assert_not_called()
        self.assertEqual(service._public_profile(config)['protocol'], 'openai_decisions')
        self.assertNotIn('sk-proj-test', json.dumps(service._public_profile(config)))

    def test_legacy_system_one_benchmark_does_not_misroute_api_key_profile(self):
        import typesafe_benchmark
        raw = {'protocol': 'openai_decisions', 'api_key': 'sk-proj-test',
               'base_url': 'https://api.openai.com/v1/decisions'}
        self.assertIsNone(typesafe_benchmark.profile(raw, 'fallback'))


if __name__ == '__main__':
    unittest.main()
