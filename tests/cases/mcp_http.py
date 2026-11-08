#!/usr/bin/env python3
"""
The EspoCRM MCP over HTTP (kobo-espo-bridge espo_mcp/server.py): H1-H4 with keys, H5-H8
signing in (OAuth, espo_mcp/oauth.py, as claude.ai would). The server runs here (uvicorn,
a free port), with the test droplet's EspoCRM and the fake Kobo, and an MCP client (the
SDK's) calls it. Needs the SDK: run with the venv.

H8 makes an admin of its own (mcp-oauth-<run>) with a two-factor code, turning on
two-factor authentication in EspoCRM's settings (not forced) for the test, and removes
both at the end.

    .venv/bin/python -I tests/cases/mcp_http.py

The tools themselves are tested in tests/cases/mcp.py. Writes tests/results/mcp_http.json.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets as pysecrets
import struct
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, admin, pw_key, secrets  # noqa: E402

from bridges import BRIDGE_DIR  # noqa: E402

sys.path.insert(0, str(BRIDGE_DIR))
import httpx2  # noqa: E402
import uvicorn  # noqa: E402
from mcp.client.auth import OAuthClientProvider  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from espo_mcp import keys, server, tools  # noqa: E402

RUN = str(int(time.time()))[-6:]
INITIALIZE = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}
ACCEPT = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def text(result):
    return ' '.join(getattr(c, 'text', '') for c in result.content)


def totp(secret):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack('>Q', int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 15
    return '%06d' % ((struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % 1000000)


def sign_in(authorize_url, username, password, code='', csrf=None):
    """The browser's part: /authorize, the sign-in page, its post. (the post's response, the page's HTML)"""
    with httpx2.Client(timeout=60) as b:
        to_login = b.get(authorize_url)
        if to_login.status_code != 302:
            return to_login, ''
        page = b.get(to_login.headers['location'])
        fields = dict(re.findall(r'name="(p|csrf)" value="([^"]*)"', page.text))
        if csrf is not None:
            fields['csrf'] = csrf
        action = re.search(r'action="([^"]+)"', page.text).group(1)  # a path: /login/callback here
        origin = '/'.join(authorize_url.split('/')[:3])
        return b.post(origin + action, data={**fields, 'username': username, 'password': password, 'code': code}), \
            page.text


def code_of(response):
    loc = response.headers.get('location', '')
    m = re.search(r'[?&]code=([^&]+)', loc)
    return m and m.group(1), dict(re.findall(r'[?&](state)=([^&]+)', loc)).get('state')


class Memory:
    """The SDK client's token storage, in memory."""
    tokens = client = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client

    async def set_client_info(self, client):
        self.client = client


async def oauth_session(url, username, password, out):
    """As claude.ai would: discovery, registration, sign-in (here, by sign_in()), a session."""
    got = {}

    async def redirect(authorize_url):
        response, _ = await asyncio.to_thread(sign_in, authorize_url, username, password)
        got['code'], got['state'] = code_of(response)
        out['signin_status'] = response.status_code

    async def callback():
        return AuthorizationCodeResult(code=got['code'], state=got['state'])

    storage = Memory()
    provider = OAuthClientProvider(url, OAuthClientMetadata(
        client_name='kobo-espo test', redirect_uris=['http://localhost:39113/callback'],
        grant_types=['authorization_code', 'refresh_token'], response_types=['code']), storage, redirect, callback)
    async with httpx2.AsyncClient(auth=provider, timeout=120) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                out['tools'] = len((await s.list_tools()).tools)
                out['info'] = await s.call_tool('bridge_info', {})
    out['storage'] = storage


async def bearer_call(url, token):
    """bridge_info with this bearer: the result, or the HTTP status that refused it."""
    async with httpx2.AsyncClient(headers={'Authorization': f'Bearer {token}'}, timeout=120) as client:
        first = await client.post(url, json=INITIALIZE, headers=ACCEPT)
        if first.status_code != 200:
            return first.status_code
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                return await s.call_tool('bridge_info', {})


async def session_calls(url, key):
    out = {}
    client = httpx2.AsyncClient(headers={'Authorization': f'Bearer {key}'}, timeout=120)
    async with streamable_http_client(url, http_client=client) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            out['tools'] = sorted(t.name for t in (await s.list_tools()).tools)
            out['schemas'] = {t.name: t.input_schema for t in (await s.list_tools()).tools}
            out['prompts'] = [p.name for p in (await s.list_prompts()).prompts]
            out['prompt'] = (await s.get_prompt('connect_a_form', {'form': 'Grant applications'})).messages[0].content.text
            out['info'] = await s.call_tool('bridge_info', {})
            out['unshared'] = await s.call_tool('propose_connection', {'form': 'aNotSharedWithTheBridge1', 'entity': 'Case'})
            out['entity_first'] = await s.call_tool('create_entity', {
                'name': f'McpHttp{RUN}', 'label_singular': 'X', 'label_plural': 'Xs'})
            out['entity_forged'] = await s.call_tool('create_entity', {
                'name': f'McpHttp{RUN}', 'label_singular': 'X', 'label_plural': 'Xs', 'confirm': 'abc.def'})
    return out


def main():
    import logging
    for name in ('httpx', 'httpx2', 'mcp'):
        logging.getLogger(name).setLevel(logging.WARNING)
    from fake_kobo import FakeKobo
    kobo = FakeKobo(token='fake-' + RUN, username='bridge_acct').start()
    work = Path(tempfile.mkdtemp(prefix='bridge-mcp-http-'))
    (work / 'token').write_text(kobo.token)
    port = free_port()
    public = f'http://127.0.0.1:{port}'
    env = {'ESPO_URL': URL, 'ESPO_SITE_URL': URL, 'ESPO_ADMIN_PASSWORD': secrets()['ESPO_ADMIN_PASSWORD'],
           'KOBO_URL': kobo.url, 'KOBO_TOKEN_FILE': str(work / 'token'), 'BRIDGE_NAME': 'tests-mcp-http'}
    import os
    os.environ['MCP_KEYS_FILE'] = str(work / 'mcp-keys')
    os.environ['MCP_OAUTH_KEY_FILE'] = str(work / 'oauth.key')
    os.environ['MCP_ADMIN_CHECK_SECONDS'] = '0'  # H8 takes admin rights away and expects it at once
    admin_key = 'kem_' + 'a' * 20 + RUN
    keys.save({keys.hashed(admin_key): 'admin', keys.hashed('kem_staff1_' + RUN): 'staff-1'})
    inst = tools.Instance(env)
    app = server.http_app(inst, public)
    srv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.1)
    url = f'{public}/mcp'
    try:
        # --- H1: only an admin's key ----------------------------------------------------------
        body, hdrs = INITIALIZE, ACCEPT
        codes = {}
        for label, key in [('none', None), ('made up', 'kem_nothing'), ('non-admin', 'kem_staff1_' + RUN),
                           ('admin', admin_key)]:
            h = {**hdrs, **({'Authorization': f'Bearer {key}'} if key else {})}
            codes[label] = httpx2.post(url, json=body, headers=h, timeout=30).status_code
        check('H1', 'no key, a made-up key, a non-admin\'s key: 401; an admin\'s: in',
              codes == {'none': 401, 'made up': 401, 'non-admin': 401, 'admin': 200}, codes)
        bad_host = httpx2.post(url, json=body, headers={**hdrs, 'Authorization': f'Bearer {admin_key}',
                                                        'Host': 'evil.example.org'}, timeout=30).status_code
        check('H1', 'another Host header (DNS rebinding): refused', bad_host in (400, 421), bad_host)

        # --- H2-H4: a session, as Claude Code's -------------------------------------------------
        out = asyncio.run(session_calls(url, admin_key))
        check('H2', 'the tools and the prompt', out['tools'] == sorted([
            'bridge_info', 'list_teams', 'list_users', 'list_entities', 'propose_connection', 'preview_template',
            'create_connection', 'update_connection', 'pause_connection', 'resume_connection', 'create_entity',
            'grant_access', 'test_connection', 'connection_status', 'list_roles', 'list_projects', 'create_response',
            'create_project', 'invite_user', 'add_to_team', 'remove_from_team', 'create_dashboard_feed',
            'list_dashboard_feeds', 'remove_dashboard_feed'])
              and sorted(out['prompts']) == ['connect_a_form', 'set_up_a_response'],
              out['tools'])
        check('H2', 'each parameter described for the agent (propose_connection)',
              all(p.get('description') for p in out['schemas']['propose_connection']['properties'].values()),
              out['schemas']['propose_connection'])
        check('H2', 'the prompt: the steps across both servers', 'Grant applications' in out['prompt']
              and 'share_project' in out['prompt'] and 'test_connection' in out['prompt'], out['prompt'][:300])
        info = out['info']
        check('H3', 'bridge_info over MCP: the Kobo account to share with',
              not info.is_error and 'bridge_acct' in text(info), text(info)[:300])
        un = out['unshared']
        check('H4', 'a refusal is a tool error with its message (what to share)',
              un.is_error and 'share_project aNotSharedWithTheBridge1 with bridge_acct' in text(un), text(un)[:300])
        first, forged = out['entity_first'], out['entity_forged']
        made = f'CMcpHttp{RUN}' in (inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {})
        check('H4', 'create_entity: the first call returns a token; a forged one changes nothing',
              not first.is_error and '"confirm"' in text(first) and forged.is_error
              and "isn't a valid token" in text(forged) and not made, {'forged': text(forged)[:200], 'made': made})

        # --- H5: discovery, as claude.ai finds where to sign in --------------------------------
        r = httpx2.post(url, json=body, headers=hdrs, timeout=30)
        prm_url = re.search(r'resource_metadata="([^"]+)"', r.headers.get('www-authenticate', ''))
        prm = httpx2.get(prm_url.group(1), timeout=30).json() if prm_url else {}
        asm = httpx2.get(f'{public}/.well-known/oauth-authorization-server', timeout=30).json()
        check('H5', 'a 401 names the resource metadata; it names this server as where to sign in',
              r.status_code == 401 and prm.get('resource') == url
              and [a.rstrip('/') for a in prm.get('authorization_servers', [])] == [public], prm)
        check('H5', 'the authorization server: sign-in, tokens, registration, PKCE (S256)',
              asm.get('authorization_endpoint') == f'{public}/authorize' and asm.get('token_endpoint') == f'{public}/token'
              and asm.get('registration_endpoint') == f'{public}/register'
              and asm.get('code_challenge_methods_supported') == ['S256'], asm)

        # --- H6: the whole sign-in with the SDK's OAuth client, as an admin ---------------------
        out = {}
        asyncio.run(oauth_session(url, 'admin', secrets()['ESPO_ADMIN_PASSWORD'], out))
        tok = out['storage'].tokens
        check('H6', 'signed in as admin (the page sends the browser back with a code), then the tools',
              out.get('signin_status') == 303 and out.get('tools') == 24 and not out['info'].is_error
              and 'bridge_acct' in text(out['info']), {k: out.get(k) for k in ('signin_status', 'tools')})
        check('H6', 'the tokens are sealed: neither names the user or can be read',
              tok and 'admin' not in tok.access_token and 'admin' not in (tok.refresh_token or '')
              and tok.expires_in == 3600)

        # --- H7: refusals ----------------------------------------------------------------------
        def register(redirect='http://127.0.0.1:39114/cb', **extra):
            return httpx2.post(f'{public}/register', timeout=30, json={
                'client_name': 'h7', 'redirect_uris': [redirect], 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'client_secret_post', **extra})

        def authorize_url(client, redirect='http://127.0.0.1:39114/cb', verifier='v' * 50, state='st'):
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            return f'{public}/authorize?' + urlencode({
                'response_type': 'code', 'client_id': client['client_id'], 'redirect_uri': redirect,
                'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state, 'resource': url})

        client = register().json()
        wrong, _ = sign_in(authorize_url(client), 'admin', 'not-the-password')
        staff_pw = secrets('seed')[pw_key('staff-1')]
        staff, _ = sign_in(authorize_url(client), 'staff-1', staff_pw)
        check('H7', 'a wrong password: the page again, saying so, and no code', wrong.status_code == 400
              and 'accept that username and password' in wrong.text and not code_of(wrong)[0], wrong.status_code)
        check('H7', 'a user who isn\'t an admin, with their right password: refused, saying only admins',
              staff.status_code == 400 and 'Only EspoCRM administrators' in staff.text and not code_of(staff)[0],
              staff.status_code)
        forged, _ = sign_in(authorize_url(client), 'admin', secrets()['ESPO_ADMIN_PASSWORD'], csrf='forged')
        bad_p = httpx2.get(f'{public}/login', params={'p': 'not-a-sealed-blob'}, timeout=30)
        other = sign_in(authorize_url(client, redirect='https://evil.example.org/cb'), 'admin', 'x')[0]
        bad_reg = register(redirect='http://evil.example.org/cb')
        check('H7', 'refused: a forged form, a made-up sign-in link, an unregistered redirect, an http one',
              forged.status_code == 400 and 'another page' in forged.text and bad_p.status_code == 400
              and other.status_code == 400 and bad_reg.status_code == 400,
              [forged.status_code, bad_p.status_code, other.status_code, bad_reg.status_code])

        # --- H8: an admin with a two-factor code; codes and refresh tokens once; rights taken away
        a = admin()
        before_2fa = a.call('GET', '/Settings').get('auth2FA')
        user8, pw8 = f'mcp-oauth-{RUN}', pysecrets.token_urlsafe(14)
        u8 = a.call('POST', '/User', body={'userName': user8, 'lastName': f'MCP OAuth {RUN}', 'type': 'admin',
                                           'isActive': True, 'password': pw8})
        try:
            a.call('PUT', '/Settings', body={'auth2FA': True})
            setup = a.call('POST', '/UserSecurity/action/getTwoFactorUserSetupData', body={
                'id': u8['id'], 'password': secrets()['ESPO_ADMIN_PASSWORD'], 'auth2FAMethod': 'Totp', 'reset': True})
            a.call('PUT', f'/UserSecurity/{u8["id"]}', body={'password': secrets()['ESPO_ADMIN_PASSWORD'],
                                                             'auth2FA': True, 'auth2FAMethod': 'Totp',
                                                             'code': totp(setup['auth2FATotpSecret'])})
            c8 = register().json()
            no_code, _ = sign_in(authorize_url(c8), user8, pw8)
            check('H8', 'two-factor: without the code, the page asks for it', no_code.status_code == 400
                  and 'two-factor' in no_code.text and not code_of(no_code)[0], no_code.status_code)
            ok, _ = sign_in(authorize_url(c8, state='s8'), user8, pw8, totp(setup['auth2FATotpSecret']))
            code8, state8 = code_of(ok)
            sessions = a.call('GET', '/AuthToken', {'where[0][type]': 'equals', 'where[0][attribute]': 'userId',
                                                    'where[0][value]': u8['id'], 'select': 'id,isActive'})['list']
            check('H8', 'with the code: back to the app with a code and its state; EspoCRM\'s session ended',
                  ok.status_code == 303 and code8 and state8 == 's8' and sessions
                  and not any(t.get('isActive') for t in sessions), {'status': ok.status_code, 'sessions': sessions})
            exchange = {'grant_type': 'authorization_code', 'code': code8, 'redirect_uri': 'http://127.0.0.1:39114/cb',
                        'client_id': c8['client_id'], 'client_secret': c8.get('client_secret'),
                        'code_verifier': 'v' * 50, 'resource': url}
            wrong_verifier = httpx2.post(f'{public}/token', data={**exchange, 'code_verifier': 'w' * 50}, timeout=30)
            t1 = httpx2.post(f'{public}/token', data=exchange, timeout=30)
            again = httpx2.post(f'{public}/token', data=exchange, timeout=30)
            check('H8', 'the code: not without its PKCE verifier; with it, tokens; only once',
                  wrong_verifier.status_code == 400 and t1.status_code == 200 and again.status_code == 400,
                  [wrong_verifier.status_code, t1.status_code, again.status_code, again.text[:200]])
            t1 = t1.json()
            first = asyncio.run(bearer_call(url, t1['access_token']))
            refresh = {'grant_type': 'refresh_token', 'refresh_token': t1['refresh_token'],
                       'client_id': c8['client_id'], 'client_secret': c8.get('client_secret')}
            t2 = httpx2.post(f'{public}/token', data=refresh, timeout=30)
            reused = httpx2.post(f'{public}/token', data=refresh, timeout=30)
            check('H8', 'its token calls the tools; a refresh works once',
                  not isinstance(first, int) and not first.is_error and t2.status_code == 200
                  and reused.status_code == 400, [first if isinstance(first, int) else 'ok', t2.status_code,
                                                  reused.status_code])
            t2 = t2.json()
            a.call('PUT', f'/User/{u8["id"]}', body={'type': 'regular'})
            after = asyncio.run(bearer_call(url, t2['access_token']))
            late = httpx2.post(f'{public}/token', data={**refresh, 'refresh_token': t2['refresh_token']}, timeout=30)
            check('H8', 'no longer an admin in EspoCRM: the token is refused, and so is a refresh',
                  after == 401 and late.status_code == 400 and 'no longer an active' in late.text,
                  {'after': after if isinstance(after, int) else 'let in', 'refresh': late.text[:200]})
        finally:
            a.call('DELETE', f'/User/{u8["id"]}')
            a.call('PUT', '/Settings', body={'auth2FA': bool(before_2fa)})
    finally:
        srv.should_exit = True
        kobo.stop()

    path = ROOT / 'tests' / 'results' / 'mcp_http.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'mcp_http: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
