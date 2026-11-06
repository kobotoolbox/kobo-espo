#!/usr/bin/env python3
"""
The EspoCRM MCP over HTTP (kobo-espo-bridge espo_mcp/server.py): H1-H4. The server runs
here (uvicorn, a free port), with the test droplet's EspoCRM and the fake Kobo, and an MCP
client (the SDK's) calls it as Claude Code would. Needs the SDK: run with the venv.

    .venv/bin/python -I tests/cases/mcp_http.py

The tools themselves are tested in tests/cases/mcp.py. Writes tests/results/mcp_http.json.
"""
import asyncio
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, secrets  # noqa: E402

from bridges import BRIDGE_DIR  # noqa: E402

sys.path.insert(0, str(BRIDGE_DIR))
import httpx2  # noqa: E402
import uvicorn  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from espo_mcp import keys, server, tools  # noqa: E402

RUN = str(int(time.time()))[-6:]
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
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}
        hdrs = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
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
            'grant_access', 'test_connection', 'connection_status']) and out['prompts'] == ['connect_a_form'],
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
