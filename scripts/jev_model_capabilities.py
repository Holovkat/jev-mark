"""Credential-free expectations for configured decision routes, not a support gate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CAPABILITIES = [
    ("reasoning", "Reasoning mode", "An explicitly exposed thinking/reasoning mode; not general reasoning accuracy."),
    ("decision", "Native decisions", "A native probability-bearing decision protocol, rather than generated structured text."),
    ("images", "Image input", "Images can reach this model through its currently configured JEV route."),
    ("text", "Text input", "Text evidence can reach this model through its configured route."),
    ("choice", "Choice", "The route accepts finite categorical Choice questions."),
    ("score", "Score", "The route accepts bounded ordinal Score questions."),
    ("noul", "Noul", "The route accepts binary/presence Noul questions."),
    ("box", "Box", "The route accepts image-bound normalized bounding-box questions."),
]


def catalog(gateway, transport=urlopen):
    rows = []
    for profile in gateway.load_profiles():
        endpoint = urlsplit(profile['endpoint'])
        ollama = gateway.is_ollama_profile(profile)
        native = endpoint.path.endswith(('/systemone', '/decisions'))
        image_mode = gateway.image_capability(profile)
        evidence = {
            'protocol': 'native_decisions' if native else 'unknown',
            'image_adapter': image_mode,
            'contract': 'JEV route accepts text, Choice, Score and Noul; upstream model acceptance still applies.',
            'metadata': None,
            'reasoning_effort': profile.get('reasoning_effort', 'not configured'),
        }
        expectations = {}
        def expect(key, value, basis):
            expectations[key] = {'value': value, 'basis': basis}
        expect('reasoning', 'unknown', 'No reasoning-mode evidence for this route.')
        expect('decision', 'supported' if native else 'unknown',
               'Configured inference protocol; this is not a quality measurement.')
        expect('images', 'unsupported' if image_mode == 'unsupported' else 'unknown',
               'Image route disabled/unsupported.' if image_mode == 'unsupported' else 'Image adapter enabled; model acceptance is not yet established.')
        for key in ('text', 'choice', 'score', 'noul'):
            expect(key, 'supported', 'Configured JEV adapter contract; not a live inference probe.')
        expect('box', 'unsupported' if image_mode == 'unsupported' else 'unknown',
               'This route cannot carry the required image.' if image_mode == 'unsupported' else 'Native Box acceptance is delegated to the provider; no allowlist.')
        if ollama:
            try:
                base = profile['endpoint'].rsplit('/v1/systemone', 1)[0]
                request = Request(base + '/api/show', data=json.dumps({'model': profile['model']}).encode(),
                                  headers={'Content-Type': 'application/json'})
                with transport(request, timeout=2) as response:
                    metadata = json.load(response)
                capabilities = metadata.get('capabilities')
                if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
                    raise ValueError('Invalid capability metadata')
                evidence['metadata'] = {'source': 'Ollama /api/show', 'capabilities': capabilities}
                for key, flag in (('reasoning', 'thinking'), ('decision', 'decision')):
                    expect(key, 'supported' if flag in capabilities else 'unknown',
                           'Advertised by Ollama /api/show.' if flag in capabilities else 'Not advertised by Ollama; absence is not proof of rejection.')
                if image_mode != 'unsupported':
                    expect('images', 'supported' if 'vision' in capabilities else 'unknown',
                           'Ollama advertises vision and the image adapter is enabled.' if 'vision' in capabilities else 'Image adapter enabled but vision is not advertised.')
            except Exception:
                evidence['metadata'] = {'source': 'Ollama /api/show', 'status': 'unavailable'}
        official_typesafe = endpoint.hostname == 'api.typesafe.ai' and endpoint.path == '/v1/systemone'
        if official_typesafe and profile['model'] in ('jev-latest', 'jev-1.14.0', 'jev-preview'):
            evidence['image_contract'] = 'https://docs.typesafe.ai/images: System One accepts image assets with TypeSafe-Danger-Zone-Images: true.'
            if image_mode == 'systemone':
                expect('images', 'supported', 'TypeSafe documented image contract for this Jev model and enabled System One image adapter; not a live probe in this report.')
        if official_typesafe:
            evidence['box_contract'] = 'https://docs.typesafe.ai/primitives/box: Box requires model jev-1.14.0 or jev-preview and enabled images. The docs do not establish which version jev-latest resolves to.'
            if profile['model'] in ('jev-1.14.0', 'jev-preview') and image_mode != 'unsupported':
                expect('box', 'supported', 'TypeSafe experimental Box documentation; model alias can change, no live probe in this report.')
        rows.append({'id': profile['id'], 'name': profile['name'], 'model': profile['model'],
                     'evidence': evidence, 'expected': expectations})
    return {'generated_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'Configured remote profiles only; local finite routing, Apple and CLM are not inventoried here.',
            'capabilities': [{'id': key, 'name': name, 'definition': definition} for key, name, definition in CAPABILITIES],
            'models': rows}
