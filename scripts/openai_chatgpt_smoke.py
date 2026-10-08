#!/usr/bin/env python3
"""JEV's opt-in SIWC login and public Responses API smoke test.

Requires PyJWT with cryptography. Credentials stay in ignored .secure storage.
Never imports or refreshes another application's ChatGPT credentials.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

AUTH = 'https://auth.openai.com'
API = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('Refusing symlink credential storage')
    return json.loads(path.read_text()) if path.exists() else {}


def save_private(path, data):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('Refusing symlink credential storage')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def request_json(url, data=None, token=None, form=False):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        data = urlencode(data).encode() if form else json.dumps(data).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def validate_identity(tokens, client_id, nonce=None):
    import jwt
    key = jwt.PyJWKClient(AUTH + '/.well-known/jwks.json', timeout=30).get_signing_key_from_jwt(tokens['id_token'])
    identity = jwt.decode(tokens['id_token'], key.key, algorithms=['RS256'],
                          audience=client_id, issuer=AUTH,
                          options={'require': ['exp', 'iss', 'aud', 'sub']})
    if nonce is not None and not hmac.compare_digest(identity.get('nonce', ''), nonce):
        raise RuntimeError('ID token nonce mismatch')
    if 'chatgpt.tokens.use.direct' not in tokens.get('scope', '').split():
        raise RuntimeError('ChatGPT plan usage permission was not granted')
    return identity


def login(path, wait_seconds):
    previous = read_json(path)
    host_path = path.parent / 'openai-host.json'
    host = read_json(host_path)
    if not host:
        host = {'ext_agent_host_id': 'urn:uuid:' + str(uuid.uuid4())}
        save_private(host_path, host)
    state, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Callback URLs contain authorization codes.

        def do_GET(self):
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            valid = (parsed.path == '/auth/callback' and
                     hmac.compare_digest(values.get('state', [''])[0], state))
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Return to Codex to see the test result.' if valid else b'Invalid callback.')
            if valid:
                received.update(values)

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        redirect = f'http://127.0.0.1:{server.server_port}/auth/callback'
        params = dict(client_id=previous.get('client_id', 'dynamic_agent_client'),
                      ext_agent_host_id=host['ext_agent_host_id'], response_type='code',
                      redirect_uri=redirect, scope=SCOPE, resource=API, state=state,
                      nonce=nonce, code_challenge_method='S256',
                      code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        if not previous.get('client_id'):
            params['agent_name_hint'] = 'JEV'
        print('Opening OpenAI sign-in for JEV. Complete login and plan consent in your browser.', flush=True)
        webbrowser.open(AUTH + '/api/accounts/authorize?' + urlencode(params))
        deadline = time.monotonic() + wait_seconds
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if not received:
        raise RuntimeError('Sign-in timed out; rerun with --login to try again')
    if received.get('error'):
        raise RuntimeError('OpenAI declined or could not complete authorization')
    client_id = received.get('client_id', [previous.get('client_id')])[0]
    if not client_id or client_id == 'dynamic_agent_client':
        raise RuntimeError('Registration did not return an issued client ID')
    if previous.get('client_id') and previous['client_id'] != client_id:
        raise RuntimeError('Returning registration client ID mismatch')
    tokens = request_json(AUTH + '/api/accounts/oauth/token',
                          dict(grant_type='authorization_code', client_id=client_id,
                               code=received['code'][0], code_verifier=verifier,
                               redirect_uri=redirect, resource=API), form=True)
    identity = validate_identity(tokens, client_id, nonce)
    if previous.get('subject') and previous['subject'] != identity['sub']:
        raise RuntimeError('Returning account identity mismatch')
    record = {**tokens, 'client_id': client_id, 'subject': identity['sub'],
              'ext_agent_host_id': host['ext_agent_host_id'], 'saved_at': time.time()}
    save_private(path, record)
    print('JEV sign-in validated; protected credentials saved.', flush=True)
    return record


def infer(token, model):
    body = {'model': model, 'input': [{'role': 'user', 'content': 'Say exactly: Hello, world!'}],
            'reasoning': {'effort': 'medium'}, 'store': False, 'stream': True}
    req = Request(API + '/responses', data=json.dumps(body).encode(),
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    output, completed, data = [], False, []

    def consume(lines):
        nonlocal completed
        if not lines or '\n'.join(lines) == '[DONE]':
            return
        event = json.loads('\n'.join(lines))
        kind = event.get('type')
        if kind == 'response.output_text.delta':
            output.append(event.get('delta', ''))
        elif kind == 'response.completed':
            completed = True
        elif kind in {'response.failed', 'response.incomplete', 'error'}:
            error = event.get('response', {}).get('error') or event.get('error') or {}
            code = error.get('code', kind) if isinstance(error, dict) else kind
            raise RuntimeError('Inference terminal error: ' + str(code))

    with urlopen(req, timeout=90) as response:
        for raw in response:
            line = raw.decode().rstrip('\r\n')
            if not line:
                consume(data)
                data = []
            elif line.startswith('data:'):
                data.append(line[5:].lstrip())
        consume(data)
    if not completed:
        raise RuntimeError('Stream ended without response.completed')
    if ''.join(output).strip() != 'Hello, world!':
        raise RuntimeError('Completed inference, but smoke output did not match')
    return {'model': model, 'reasoning_effort': 'medium', 'completed': True, 'output_matches': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--credentials', type=Path, default=ROOT / '.secure/openai-chatgpt.json')
    parser.add_argument('--wait-seconds', type=int, default=300)
    parser.add_argument('--model', default='gpt-6-luna', help='Exact slug from the account catalog; default gpt-6-luna')
    args = parser.parse_args()
    record = login(args.credentials, args.wait_seconds) if args.login else read_json(args.credentials)
    if not record.get('access_token'):
        raise RuntimeError('No JEV ChatGPT credentials; run with --login')
    if 'chatgpt.tokens.use.direct' not in record.get('scope', '').split():
        raise RuntimeError('Credential lacks direct ChatGPT plan permission')
    if time.time() >= record['saved_at'] + record.get('expires_in', 3600):
        raise RuntimeError('Credential expired; rerun --login (this smoke tool does not rotate refresh tokens)')
    catalog = request_json(API + '/models', token=record['access_token'])
    models = [m for m in catalog.get('models', []) if m.get('visibility') == 'list']
    print(json.dumps({'visible_models': [{'slug': m['slug'], 'display_name': m.get('display_name')} for m in models]}), flush=True)
    if not models:
        raise RuntimeError('Account returned no visible inference models')
    model = args.model
    if model not in {m['slug'] for m in models}:
        raise RuntimeError('Requested model is not in this account catalog')
    print(json.dumps(infer(record['access_token'], model)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        # Never print provider bodies, callback URLs, or credentials.
        print(json.dumps({'status': 'failed', 'http_status': exc.code,
                          'request_id': exc.headers.get('x-request-id')}), file=sys.stderr)
        sys.exit(1)
    except URLError:
        print('Network request failed; credentials retained.', file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, KeyError, ValueError, ImportError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else 'Invalid data or missing PyJWT/cryptography dependency'
        print(message, file=sys.stderr)
        sys.exit(1)
