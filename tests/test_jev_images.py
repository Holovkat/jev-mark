import base64
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import jev_gateway as gateway
from jev_images import validate_assets, responses_content

from image_smoke import shape_png
IMAGE = {'type': 'image', 'format': 'png', 'data_base64': base64.b64encode(shape_png()).decode()}
REF = 'image-9d13f901'


def packet():
    return {'contexts': ['Look at ' + REF], 'schema': {'visible': {'type': 'noul', 'instructions': 'Is a square visible?'}}, 'assets': {REF: copy.deepcopy(IMAGE)}}


def config():
    return {'id': 'vision-test', 'name': 'Vision test', 'endpoint': 'https://api.typesafe.ai/v1/systemone', 'model': 'jev-latest', 'api_key': 'test'}


class ImageTests(unittest.TestCase):
    def test_existing_text_packet_unchanged(self):
        self.assertEqual(validate_assets({'contexts': ['text']}), {})
        self.assertEqual(responses_content({'state': 'text'}, {}), '{"state": "text"}')

    def test_validation_and_nested_references(self):
        p = packet()
        p['contexts'] = ['text']
        p['schema']['visible']['criteria'] = {'true': {'example': REF}, 'false': 'absent'}
        self.assertEqual(validate_assets(p), p['assets'])
        for mutation in [
            lambda p: p.update(assets=[]),
            lambda p: p['assets'][REF].update(data_base64='data:image/png;base64,abc'),
            lambda p: p['assets'][REF].update(data_base64='!!!!'),
            lambda p: p['assets'][REF].update(format='gif'),
            lambda p: p['assets'][REF].update(format='jpg'),
            lambda p: p['assets'][REF].update(part='file'),
            lambda p: p.update(contexts=['unreferenced']),
            lambda p: p.update(contexts=['text'], schema={'q': {'type': 'choice', 'choices': [REF, 'other']}}),
            lambda p: p.update(assets={'': IMAGE}),
            lambda p: p.update(assets={'x' * 1025: IMAGE}),
        ]:
            p = packet(); mutation(p)
            with self.subTest(payload=p), self.assertRaises(ValueError):
                validate_assets(p)

    def test_unsupported_routes_make_no_inference_call(self):
        p = packet()
        with patch.object(gateway, 'urlopen') as transport:
            for fn in [gateway.local_payload, gateway.apple_payload,
                       lambda p: gateway.call_typesafe(dict(config(), endpoint='http://127.0.0.1:11434/v1/systemone'), p),
                       lambda p: gateway.call_typesafe(dict(config(), protocol='openai_chatgpt', endpoint='https://api.openai.com/v1/decisions'), p)]:
                with self.assertRaises(gateway.GatewayError) as caught:
                    fn(p)
                self.assertEqual(caught.exception.status, 422)
            transport.assert_not_called()

    def test_native_assets_header_context_order_and_no_mutation(self):
        p = packet(); p['contexts'] += ['No picture in this context']
        before = copy.deepcopy(p); requests = []
        def transport(req, **kwargs):
            requests.append(req)
            return io.BytesIO(b'{"answers":{"jev_field_0":{"type":"noul","noul":0.9}}}')
        with patch.object(gateway, 'urlopen', side_effect=transport):
            result = gateway.call_typesafe(config(), p)
        self.assertTrue(result['complete']); self.assertEqual(len(result['results']), 2)
        bodies = {json.loads(req.data)['state']: (req, json.loads(req.data)) for req in requests}
        req, body = bodies[p['contexts'][0]]
        self.assertEqual(body['assets'], p['assets'])
        self.assertEqual(req.get_header('Typesafe-danger-zone-images'), 'true')
        self.assertNotIn('assets', bodies[p['contexts'][1]][1])
        self.assertEqual(p, before)

    def test_native_nested_instruction_and_criteria_assets(self):
        p = packet()
        p['contexts'] = ['Compare the examples']
        p['schema']['visible']['instructions'] = {'example': REF, 'question': 'Is this a square?'}
        p['schema']['visible']['criteria'] = {'true': {'example': REF}, 'false': 'No square'}
        requests = []
        def transport(req, **kwargs):
            requests.append(json.loads(req.data))
            return io.BytesIO(b'{"answers":{"jev_field_0":{"noul":0.9}}}')
        with patch.object(gateway, 'urlopen', side_effect=transport):
            gateway.call_typesafe(config(), p)
        self.assertEqual(requests[0]['assets'], p['assets'])
        self.assertEqual(requests[0]['questions']['jev_field_0']['criteria']['true']['example'], REF)

    def test_retry_preserves_only_failed_context_images(self):
        p = packet(); p['contexts'] += ['text context']
        def transport(req, **kwargs):
            if REF in json.loads(req.data)['state']:
                raise HTTPError(req.full_url, 422, 'rejected', {}, io.BytesIO())
            return io.BytesIO(b'{"answers":{"jev_field_0":{"noul":0.9}}}')
        with patch.object(gateway, 'urlopen', side_effect=transport):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.call_typesafe(config(), p)
        retry = caught.exception.details['retry_requests']
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0]['request']['assets'], p['assets'])
        self.assertEqual(retry[0]['context_index'], 0)

    def test_responses_images_expand_values_only_in_order(self):
        value = {REF: 'key stays text', 'state': ['before ' + REF + ' after', REF]}
        parts = responses_content(value, {REF: IMAGE})
        self.assertEqual(sum(part['type'] == 'input_image' for part in parts), 2)
        self.assertIn('"' + REF + '":', parts[0]['text'])
        self.assertTrue(parts[1]['image_url'].startswith('data:image/png;base64,'))
        self.assertIn('after', parts[2]['text'])

    def test_responses_gateway_dispatch_and_capabilities(self):
        c = dict(config(), protocol='openai_chatgpt', endpoint='https://api.openai.com/v1/responses')
        with patch.object(gateway, 'call_chatgpt', return_value={'answers': {'jev_field_0': {'noul': .9}}}) as adapter:
            self.assertTrue(gateway.call_typesafe(c, packet())['complete'])
        self.assertEqual(adapter.call_args.kwargs['assets'], packet()['assets'])
        self.assertEqual(gateway.remote_capabilities(c)['image_input'], 'responses')
        self.assertEqual(gateway.profile(dict(config(), image_input='systemone'), 'x')['image_input'], 'systemone')


if __name__ == '__main__':
    unittest.main()
