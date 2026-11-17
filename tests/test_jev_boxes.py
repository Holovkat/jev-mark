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
from jev_images import validate_box
from image_smoke import shape_png
from jev_analytics import Observation

REF = 'box-image-9d13f901'
BOX = {'left': .1, 'right': .46, 'top': .29, 'bottom': .65}


def packet():
    return {'contexts': ['Inspect the supplied image.'],
            'schema': {'location': {'type': 'box', 'image_ref': REF, 'instructions': 'Locate the red square.'},
                       'present': {'type': 'noul', 'instructions': 'Is there a red square?'}},
            'assets': {REF: {'type': 'image', 'format': 'png', 'data_base64': base64.b64encode(shape_png()).decode()}}}


def config(**kwargs):
    return dict({'id': 'future-box-provider', 'endpoint': 'https://offline.invalid/v1/systemone',
                 'model': 'future-unlisted-model', 'api_key': 'fixture', 'image_input': 'systemone'}, **kwargs)


def answer(box=None):
    return {'answers': {'jev_field_0': {'type': 'box', 'box': BOX if box is None else box, 'confidence': .93},
                        'jev_field_1': {'type': 'noul', 'noul': .98}}}


class BoxTests(unittest.TestCase):
    def test_shared_box_forwards_without_model_allowlist_and_binds_image(self):
        requests = []
        def transport(req, **kwargs):
            requests.append(req)
            return io.BytesIO(json.dumps(answer()).encode())
        p = packet(); original = copy.deepcopy(p)
        with patch.object(gateway, 'urlopen', side_effect=transport):
            result = gateway.call_typesafe(config(), p)
        body = json.loads(requests[0].data)
        self.assertEqual(body['model'], 'future-unlisted-model')
        self.assertEqual(body['questions']['jev_field_0']['type'], 'box')
        self.assertEqual(body['questions']['jev_field_0']['instructions']['target_image'], REF)
        self.assertNotIn('criteria', body['questions']['jev_field_0'])
        self.assertEqual(body['assets'], p['assets'])
        self.assertEqual(result['results'][0]['decision']['location'], BOX)
        self.assertEqual(result['results'][0]['fields']['location']['image_ref'], REF)
        self.assertNotIn('probabilities', result['results'][0]['fields']['location'])
        self.assertTrue(result['results'][0]['decision']['present'])
        self.assertEqual(p, original)

    def test_geometry_rejects_nonfinite_inverted_missing_or_coerced_edges(self):
        invalid = [None, [], {}, dict(BOX, left=True), dict(BOX, right='0.5'), dict(BOX, left=-.1),
                   dict(BOX, right=1.1), dict(BOX, bottom=float('inf')), dict(BOX, top=float('nan')),
                   dict(BOX, top=.9), dict(BOX, left=BOX['right']), dict(BOX, x=.4), dict(BOX, right=10**1000)]
        for box in invalid:
            with self.subTest(box=box), self.assertRaises(ValueError): validate_box(box)

    def test_image_binding_and_no_criteria_are_required_before_inference(self):
        for change in ('missing_image', 'unknown_ref', 'criteria', 'ambiguous'):
            p = packet()
            if change == 'missing_image': p.pop('assets')
            if change == 'unknown_ref': p['schema']['location']['image_ref'] = 'not-attached'
            if change == 'criteria': p['schema']['location']['criteria'] = None
            if change == 'ambiguous':
                p['schema']['location'].pop('image_ref')
                p['assets']['second'] = p['assets'][REF]
                p['contexts'] = [REF + ' second']
            with self.subTest(change=change), patch.object(gateway, 'urlopen') as transport:
                with self.assertRaises(gateway.GatewayError) as caught: gateway.call_typesafe(config(), p)
                self.assertEqual(caught.exception.status, 400)
                transport.assert_not_called()

    def test_invalid_box_preserves_presence_and_retry_assets(self):
        with patch.object(gateway, 'urlopen', return_value=io.BytesIO(json.dumps(answer(dict(BOX, top=.9))).encode())):
            with self.assertRaises(gateway.GatewayError) as caught: gateway.call_typesafe(config(), packet())
        data = caught.exception.details
        self.assertTrue(data['results'][0]['decision']['present'])
        self.assertNotIn('location', data['results'][0]['decision'])
        retry = data['retry_requests'][0]['request']
        self.assertEqual(list(retry['schema']), ['location'])
        self.assertEqual(retry['assets'], packet()['assets'])

    def test_invalid_box_confidence_preserves_successful_siblings(self):
        for confidence in (True, '0.9', -0.1, 1.1, float('nan'), float('inf'), 10**1000):
            native = answer()
            native['answers']['jev_field_0']['confidence'] = confidence
            with self.subTest(confidence=confidence), patch.object(gateway, 'urlopen', return_value=io.BytesIO(json.dumps(native).encode())):
                with self.assertRaises(gateway.GatewayError) as caught:
                    gateway.call_typesafe(config(), packet())
                self.assertTrue(caught.exception.details['results'][0]['decision']['present'])
                self.assertNotIn('location', caught.exception.details['results'][0]['decision'])

    def test_ollama_is_attempted_and_native_box_rejection_stays_explicit(self):
        c = config(endpoint='http://127.0.0.1:11434/v1/systemone', image_input='ollama', model='d1:3b')
        error = HTTPError(c['endpoint'], 400, 'unsupported', {}, io.BytesIO(json.dumps({'error': 'questions.jev_field_0: "type" must be one of: choice, score, noul'}).encode()))
        with patch.object(gateway, 'urlopen', side_effect=error) as transport:
            with self.assertRaises(gateway.GatewayError) as caught: gateway.call_typesafe(c, packet())
        self.assertEqual(transport.call_count, 1)
        body = json.loads(transport.call_args.args[0].data)
        self.assertIn('images', body)
        self.assertEqual(body['questions']['jev_field_0']['type'], 'box')
        self.assertEqual(caught.exception.status, 400)
        self.assertIn('does not accept Box', caught.exception.details['failed_work'][0]['error'])

    def test_analytics_classifies_box_without_new_database_columns(self):
        observation = Observation({})
        p = packet();p['schema'].pop('present')
        observation.payload(p)
        self.assertEqual(observation.row['kind'], 'box')
        self.assertEqual(observation.row['fields_requested'], 1)


if __name__ == '__main__': unittest.main()
