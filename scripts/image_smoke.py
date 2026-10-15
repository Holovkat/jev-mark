#!/usr/bin/env python3
"""Known-answer image smoke. Explicitly choose a profile or a gateway URL."""
import argparse
import base64
import json
import struct
import time
import uuid
import zlib
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def shape_png():
    """320px white image, red square and blue circle; no external dependencies."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = []
    for y in range(320):
        row = bytearray([0])
        for x in range(320):
            colour = (255, 0, 0) if 35 <= x < 145 and 95 <= y < 205 else (
                (0, 0, 255) if (x - 235)**2 + (y - 150)**2 <= 55**2 else (255, 255, 255))
            row.extend(colour)
        rows.append(bytes(row))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 320, 320, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def payload():
    ref = str(uuid.uuid4())
    return {'contexts': ['Inspect this image: ' + ref],
            'schema': {'colour': {'type': 'choice', 'choices': ['red', 'blue', 'green'],
                                  'instructions': 'What colour is the square in the image? Use visual evidence only.'}},
            'assets': {ref: {'type': 'image', 'format': 'png', 'data_base64': base64.b64encode(shape_png()).decode()}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--profile', help='Configured profile ID. Does not change the selected backend.')
    target.add_argument('--url', help='Gateway base URL, e.g. http://127.0.0.1:41896')
    args = parser.parse_args()
    import jev_gateway as gateway
    started = time.perf_counter()
    try:
        if args.profile:
            config = next((p for p in gateway.load_profiles() if p['id'] == args.profile), None)
            if config is None:
                parser.error('Configured profile not found.')
            result = gateway.call_typesafe(config, payload())
        else:
            req = Request(args.url.rstrip('/') + '/v1/decision', data=json.dumps(payload()).encode(),
                          headers={'Content-Type': 'application/json', 'X-JEV-Client': 'image-smoke'})
            with urlopen(req, timeout=180) as response:
                result = json.load(response)
        choice = result['results'][0]['decision']['colour']
        summary = {'status': 'passed' if choice == 'red' else 'failed', 'expected': 'red', 'actual': choice,
                   'usage': result.get('usage'), 'elapsed_ms': round((time.perf_counter() - started) * 1000)}
    except (gateway.GatewayError, HTTPError) as error:
        summary = {'status': 'error', 'http_status': getattr(error, 'status', getattr(error, 'code', None)),
                   'error': getattr(error, 'message', 'Gateway returned an HTTP error.')}
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
