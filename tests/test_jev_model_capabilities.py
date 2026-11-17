import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import jev_model_capabilities as caps

class CatalogTests(unittest.TestCase):
    def gateway(self):
        gateway=Mock()
        gateway.load_profiles.return_value=[{'id':'d1','name':'D1','model':'d1:3b','api_key':'SECRET','endpoint':'http://127.0.0.1:11434/v1/systemone'}, {'id':'future','name':'Future','model':'new-model','api_key':'SECRET','endpoint':'https://example.invalid/v1/systemone'}]
        gateway.is_ollama_profile.side_effect=lambda p:p['id']=='d1'
        gateway.image_capability.return_value='ollama'
        return gateway
    def test_metadata_is_evidence_not_box_allowlist(self):
        data=caps.catalog(self.gateway(),lambda *a,**kw:io.BytesIO(b'{"capabilities":["decision","vision"]}'))
        self.assertNotIn('SECRET',json.dumps(data));self.assertNotIn('endpoint',json.dumps(data))
        d1,future=data['models']
        self.assertEqual(d1['expected']['images']['value'],'supported')
        self.assertEqual(d1['expected']['reasoning']['value'],'unknown')
        self.assertEqual(d1['expected']['box']['value'],'unknown')
        self.assertEqual(future['expected']['box']['value'],'unknown')
    def test_metadata_failure_remains_unknown(self):
        def fail(*a,**kw):raise TimeoutError()
        data=caps.catalog(self.gateway(),fail)
        self.assertEqual(data['models'][0]['expected']['images']['value'],'unknown')
        self.assertEqual(data['models'][0]['evidence']['metadata']['status'],'unavailable')
    def test_removed_responses_adapter_is_not_reported_as_supported(self):
        gateway=self.gateway();gateway.is_ollama_profile.side_effect=None;gateway.is_ollama_profile.return_value=False
        gateway.load_profiles.return_value=[{'id':'other','name':'Other','model':'unknown','endpoint':'https://example.invalid/v1/responses'}]
        row=caps.catalog(gateway)['models'][0]
        self.assertEqual(row['evidence']['protocol'],'unknown')
        self.assertEqual(row['expected']['reasoning']['value'],'unknown')
    def test_typesafe_documented_images_do_not_remain_unknown(self):
        gateway=self.gateway();gateway.is_ollama_profile.side_effect=None;gateway.is_ollama_profile.return_value=False
        gateway.image_capability.return_value='systemone'
        for model in ('jev-latest','jev-1.14.0','jev-preview'):
            gateway.load_profiles.return_value=[{'id':'jev','name':'TypeSafe','model':model,'endpoint':'https://api.typesafe.ai/v1/systemone'}]
            row=caps.catalog(gateway)['models'][0]
            self.assertEqual(row['expected']['images']['value'],'supported')
            self.assertIn('https://docs.typesafe.ai/images',row['evidence']['image_contract'])
        for endpoint,model in [('https://example.invalid/v1/systemone','jev-1.14.0'),('https://api.typesafe.ai/v1/systemone','future-unverified-model'),('https://api.typesafe.ai/other','jev-1.14.0')]:
            gateway.load_profiles.return_value=[{'id':'future','name':'Future','model':model,'endpoint':endpoint}]
            self.assertEqual(caps.catalog(gateway)['models'][0]['expected']['images']['value'],'unknown')

    def test_disabled_image_route_and_documented_box(self):
        gateway=self.gateway();gateway.is_ollama_profile.return_value=False;gateway.is_ollama_profile.side_effect=None
        gateway.load_profiles.return_value=[{'id':'preview','name':'TypeSafe','model':'jev-1.14.0','endpoint':'https://api.typesafe.ai/v1/systemone'}]
        gateway.image_capability.return_value='systemone'
        self.assertEqual(caps.catalog(gateway)['models'][0]['expected']['box']['value'],'supported')
        gateway.image_capability.return_value='unsupported'
        model=caps.catalog(gateway)['models'][0]
        self.assertEqual(model['expected']['images']['value'],'unsupported');self.assertEqual(model['expected']['box']['value'],'unsupported')
