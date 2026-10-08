import json
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import jev_gateway as gateway


class ChatGPTGatewayTests(unittest.TestCase):
    def test_observed_transport_supports_sse_iteration(self):
        from jev_service import ObservedResponse
        observation = Mock()
        with ObservedResponse(io.BytesIO(b'data: event\n\n'), observation, 0, 'gpt-6-luna') as response:
            self.assertEqual(list(response), [b'data: event\n', b'\n'])
        observation.attempt.assert_called_once()

    def config(self):
        return gateway.profile({'id': 'openai-chatgpt-luna', 'name': 'System One',
                                'protocol': 'openai_chatgpt', 'model': 'gpt-6-luna',
                                'base_url': 'https://api.openai.com/v1/responses'}, 'fallback')

    def test_profile_preserves_protocol_without_api_key(self):
        config = self.config()
        self.assertEqual(config['endpoint'], 'https://api.openai.com/v1/responses')
        self.assertEqual(config['reasoning_effort'], 'medium')
        self.assertEqual(config['credentials_path'], str(gateway.SECURE_DIR / 'openai-chatgpt.json'))
        self.assertIsNone(gateway.profile({'protocol': 'openai_chatgpt', 'base_url': 'https://example.com/v1/responses'}, 'bad'))

    def test_native_decisions_profile_and_dispatch(self):
        config = gateway.profile({'protocol': 'openai_chatgpt', 'model': 'gpt-6-luna',
                                  'base_url': 'https://api.openai.com/v1/decisions'}, 'native')
        self.assertEqual(config['endpoint'], 'https://api.openai.com/v1/decisions')
        self.assertNotIn('reasoning_effort', config)
        capacity = gateway.remote_capabilities(config)
        self.assertEqual(capacity['inference_protocol'], 'native_decisions')
        self.assertNotIn('reasoning_effort', capacity)
        with patch('openai_decisions_provider.call', return_value={'answers': {}}) as native, patch('openai_chatgpt_provider.call') as responses:
            gateway.call_chatgpt(config, 'state', {'q': {'type': 'noul'}})
        native.assert_called_once()
        responses.assert_not_called()

    def test_adapter_uses_existing_result_contract(self):
        payload = {'contexts': ['An urgent issue with a workaround.'],
                   'schema': {'route': {'type': 'choice', 'choices': ['review', 'skip']},
                              'risk': {'type': 'score', 'criteria': ['low', 'high']},
                              'urgent': {'type': 'noul'}}}
        native = {'answers': {
            'jev_field_0': {'type': 'choice', 'choice': 'review', 'probabilities': {'review': .8, 'skip': .2}, 'confidence': .7},
            'jev_field_1': {'type': 'score', 'score': .8, 'probabilities': {'0': .2, '1': .8}, 'confidence': .7},
            'jev_field_2': {'type': 'noul', 'noul': .8}}, 'usage': {'input_tokens': 20, 'output_tokens': 10}}
        with patch.object(gateway, 'call_chatgpt', return_value=native) as adapter, patch.object(gateway, 'urlopen') as ordinary:
            response = gateway.call_typesafe(self.config(), payload)
        ordinary.assert_not_called()
        self.assertEqual(adapter.call_args.args[1], payload['contexts'][0])
        self.assertTrue(response['complete'])
        self.assertEqual(response['results'][0]['decision'], {'route': 'review', 'risk': .8, 'urgent': True})
        self.assertEqual(response['results'][0]['fields']['route']['confidence'], .7)
        self.assertEqual(response['results'][0]['fields']['route']['probability'], .8)
        self.assertEqual(response['capacity']['billing_path'], 'chatgpt_plan')


if __name__ == '__main__':
    unittest.main()
