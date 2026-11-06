#!/usr/bin/env python3
"""
The EspoCRM MCP's tools (kobo-espo-bridge espo_mcp/, plans/kobo-connections-plan.md
phase 4): M1-M8, with the fake Kobo, against the test droplet. A connection from a form
to a new entity, as an agent would make it: share check, entity, proposal, the confirm
gate, a test submission, a change, pause, access for a role, and the MCP keys.

    python3 -I tests/cases/mcp.py

Runs the tools as functions (espo_mcp/tools.py), with a bridge service of its own
(`serve`, BRIDGE_NAME tests-mcp, every 5 s) as the droplet runs one; the MCP over HTTP
is tests/cases/mcp_http.py. Removes what it made at the end. Writes tests/results/mcp.json.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, admin, secrets  # noqa: E402

from bridges import BRIDGE_DIR, by  # noqa: E402

sys.path.insert(0, str(BRIDGE_DIR))
from espo_mcp import keys, tools  # noqa: E402
from espo_mcp.confirm import Refused  # noqa: E402

RUN = str(int(time.time()))[-6:]
NAME = 'tests-mcp'
ENTITY = f'McpApp{RUN}'
ROLE = 'Internal Staff'
FORM = {'settings': {}, 'survey': [
    {'type': 'text', 'name': 'org_name', 'label': 'Organisation', 'required': 'true'},
    {'type': 'text', 'name': 'contact_email', 'label': 'Email'},
    {'type': 'select_one', 'select_from_list_name': 'country', 'name': 'country', 'label': 'Country'},
    {'type': 'decimal', 'name': 'amount', 'label': 'Amount requested (USD)'},
    {'type': 'text', 'name': 'purpose', 'label': 'What is it for?', 'appearance': 'multiline'},
    {'type': 'note', 'name': 'thanks', 'label': 'Thank you'},
], 'choices': [{'list_name': 'country', 'name': 'ke', 'label': 'Kenya'},
               {'list_name': 'country', 'name': 'ug', 'label': 'Uganda'}]}
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def refused(fn):
    try:
        fn()
        return None
    except Refused as e:
        return str(e)


def main():
    a = admin()
    from fake_kobo import FakeKobo
    kobo = FakeKobo(token='fake-' + RUN, username='bridge_acct').start()
    title = f'Grant application (mcp test {RUN})'
    uid = kobo.add_form(title, FORM)
    work = Path(tempfile.mkdtemp(prefix='bridge-mcp-'))
    (work / 'token').write_text(kobo.token)
    keys_file = work / 'bridge.secrets'
    keys_file.write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
    keys_file.chmod(0o600)
    env = {'PATH': os.environ['PATH'], 'ESPO_URL': URL, 'ESPO_SITE_URL': URL, 'BRIDGE_SECRETS': str(keys_file),
           'KOBO_URL': kobo.url, 'KOBO_TOKEN_FILE': str(work / 'token'), 'BRIDGE_STATE_DIR': str(work / 'state'),
           'BRIDGE_NAME': NAME, 'BRIDGE_POLL_SECONDS': '5', 'MCP_KEYS_FILE': str(work / 'mcp-keys')}
    service = subprocess.Popen([sys.executable, '-I', '-u', str(BRIDGE_DIR / 'bridge.py'), 'serve'], env=env,
                               stdout=open(work / 'serve.log', 'w'), stderr=subprocess.STDOUT)
    inst = tools.Instance(env)
    entity = 'C' + ENTITY
    made = {'connection': None}
    try:
        # --- M1: what's there ---------------------------------------------------------------
        info = tools.bridge_info(inst)
        check('M1', "bridge_info: the instance, and the bridge's Kobo account to share forms with",
              info['espocrm'] == URL and info['kobo_account'] == 'bridge_acct' and info['kobo_server'] == kobo.url, info)
        ents = {e['entity'] for e in tools.list_entities(inst)['entities']}
        check('M1', 'list_entities: EspoCRM\'s own and custom ones, not the bridge\'s or the agents\'',
              {'Case', 'Contact', 'CSite', 'CApplication'} <= ents and not ents & {'CKoboConnection', 'CAgent', 'User'},
              sorted(ents))
        users = {u['user'] for u in tools.list_users(inst)['users']}
        check('M1', 'list_users and list_teams: people (not API users) and teams',
              'staff-2' in users and not any(u.startswith('kobo-') for u in users)
              and 'Grants review' in tools.list_teams(inst)['teams'], sorted(users))

        # --- M2: a form the bridge can't see: the error says what to share ------------------
        why = refused(lambda: tools.propose_connection(inst, 'aNotSharedWithTheBridge1', 'Case'))
        check('M2', 'a form not shared with the bridge: refused, saying what to share with whom',
              why and 'share_project aNotSharedWithTheBridge1 with bridge_acct' in why, why)
        why = refused(lambda: tools.propose_connection(inst, uid, 'CNoSuchThing'))
        check('M2', 'an entity that doesn\'t exist: refused, pointing to create_entity', why and 'create_entity' in why, why)

        # --- M3: a new entity, through the confirm gate -------------------------------------
        first = tools.create_entity(inst, ENTITY, 'Application (test)', 'Applications (test)')
        exists = entity in (a.call('GET', '/Metadata', {'key': 'scopes'}) or {})
        why = refused(lambda: tools.create_entity(inst, ENTITY, 'Something else', 'Others', confirm=first['confirm']))
        check('M3', 'create_entity: the first call makes nothing and returns a token; another change can\'t use it',
              first['confirm_required'] and not exists and why and 'labels differs' in why, {'why': why})
        done = tools.create_entity(inst, ENTITY, 'Application (test)', 'Applications (test)', confirm=first['confirm'])
        made['entity'] = entity
        check('M3', 'with the token: the entity is made', done['changed'] and entity in (
            a.call('GET', '/Metadata', {'key': 'scopes'}) or {}), done)

        # --- M4: proposal, preview, create_connection ---------------------------------------
        kobo.submit(uid, {'org_name': f'Riverbend Trust {RUN}', 'contact_email': 'a@example.org', 'country': 'ke',
                          'amount': '2500.5', 'purpose': 'Water trucking'})
        p = tools.propose_connection(inst, f'https://kf.example.org/#/forms/{uid}/summary', entity,
                                     team='Grants review', notify=['staff-2'])
        pre = p['preview']
        check('M4', 'propose_connection: a template, each question, what was left out, from a Kobo link',
              p['form']['uid'] == uid and '[[field]]' in p['template'] and {q['question'] for q in p['questions']}
              >= {'org_name', 'amount'} and [x['question'] for x in p['left_out']] == ['thanks'], p)
        check('M4', 'and a preview of the latest submission, with the team and who\'s told',
              isinstance(pre, dict) and pre['record'].get('name') == f'Riverbend Trust {RUN}'
              and pre['record'].get('amount') == 2500.5 and pre['teams'] == ['Grants review']
              and pre['notify'] == ['staff-2'], pre)
        cname = f'MCP Grants {RUN}'
        first = tools.create_connection(inst, cname, p['template'])
        why = refused(lambda: tools.create_connection(inst, cname, p['template'] + '\n# changed', confirm=first['confirm']))
        check('M4', 'create_connection: shown first; the token won\'t save another template',
              first['would_create']['makes'] == entity and first['would_create']['notifies'] == ['staff-2']
              and not any(r['name'] == cname for r in tools.connection_rows(inst)) and why and 'template differs' in why,
              {'first': first, 'why': why})
        done = tools.create_connection(inst, cname, p['template'], confirm=first['confirm'])
        made['connection'] = done['created']['id']
        check('M4', 'with the token: saved, run by this bridge service', done['changed'] and
              a.call('GET', f'/CKoboConnection/{made["connection"]}')['runBy'] == NAME, done)

        # --- M5: test_connection waits for the service's pass, and shows the record ----------
        t5 = tools.test_connection(inst, cname, wait_seconds=120)
        newest = t5.get('newest_record') or {}
        check('M5', 'test_connection: the next pass made the record, with its link',
              t5.get('status') == 'ok' and newest.get('name') == f'Riverbend Trust {RUN}'
              and newest.get('link', '').startswith(f'{URL}/#{entity}/view/'), t5)
        rec = by(a, entity, 'name', f'Riverbend Trust {RUN}')
        rec = a.call('GET', f'/{entity}/{rec[0]["id"]}') if rec else {}
        check('M5', 'the record is as previewed', rec and all(rec.get(k) == v for k, v in pre['record'].items()),
              {k: (v, rec.get(k)) for k, v in pre['record'].items() if rec.get(k) != v})

        # --- M6: update, pause, resume --------------------------------------------------------
        changed = p['template'].replace('notify = ["staff-2"]', 'notify = ["staff-1", "staff-2"]')
        first = tools.update_connection(inst, cname, template=changed)
        check('M6', 'update_connection: the first call shows the diff', first['confirm_required']
              and '+notify = ["staff-1", "staff-2"]' in (first['template_diff'] or ''), first)
        tools.update_connection(inst, cname, template=changed, confirm=first['confirm'])
        check('M6', '... and saves it with the token', tools.connection_status(inst, cname)['template'] == changed)
        first = tools.pause_connection(inst, cname)
        tools.pause_connection(inst, cname, confirm=first['confirm'])
        paused = tools.connection_status(inst, cname)['active'] is False
        tools.resume_connection(inst, cname)
        check('M6', 'pause (two calls) and resume', paused and tools.connection_status(inst, cname)['active'] is True)

        # --- M7: grant_access, team level, kept by the seed -----------------------------------
        first = tools.grant_access(inst, entity, ROLE)
        tools.grant_access(inst, entity, ROLE, confirm=first['confirm'])
        role = by(a, 'Role', 'name', ROLE)[0]
        data = a.call('GET', f'/Role/{role["id"]}')['data'].get(entity)
        check('M7', 'grant_access: the role reads and edits its teams\' records, never all, can\'t delete',
              data == {'create': 'no', 'read': 'team', 'edit': 'team', 'delete': 'no', 'stream': 'team'}, data)
        seed = subprocess.run([sys.executable, '-I', str(ROOT / 'espo' / 'seed' / 'seed.py')], capture_output=True, text=True)
        kept = a.call('GET', f'/Role/{role["id"]}')['data'].get(entity)
        check('M7', 'the seed, run again, keeps that access (it puts back only what it defines)',
              seed.returncode == 0 and kept == data, {'seed': seed.stdout[-300:] + seed.stderr[-300:], 'kept': kept})

        # --- M8: keys: only for admins, only while they're admins -----------------------------
        os.environ['MCP_KEYS_FILE'] = env['MCP_KEYS_FILE']
        out = subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'espo_mcp' / 'keys.py'), 'add', 'staff-1'],
                             env=env, capture_output=True, text=True)
        check('M8', 'no key for a user who isn\'t an admin', out.returncode != 0 and 'not an active EspoCRM admin'
              in out.stderr, out.stderr[-200:])
        out = subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'espo_mcp' / 'keys.py'), 'add', 'admin'],
                             env=env, capture_output=True, text=True)
        key = out.stdout.strip()
        admins = keys.Admins(inst.espo)
        stored = Path(env['MCP_KEYS_FILE']).read_text()
        check('M8', 'an admin\'s key: it works, and the file keeps only its hash',
              key.startswith('kem_') and admins.who(key) == 'admin' and key not in stored and keys.hashed(key) in stored)
        keys.save({**keys.load(), keys.hashed('kem_staff1-made-by-hand'): 'staff-1'})
        check('M8', 'a key someone put in the file for a non-admin: refused; a made-up key: refused',
              admins.who('kem_staff1-made-by-hand') is None and admins.who('kem_nothing') is None
              and admins.who('') is None)
    finally:
        service.terminate()
        kobo.stop()
        if made.get('connection'):
            conn = a.call('GET', f'/CKoboConnection/{made["connection"]}')
            for u in by(a, 'User', 'userName', conn.get('apiUser') or '-'):
                a.call('DELETE', f'/User/{u["id"]}')
            for r in by(a, 'Role', 'name', f'Kobo connection: {conn.get("apiUser")}'):
                a.call('DELETE', f'/Role/{r["id"]}')
            a.call('DELETE', f'/CKoboConnection/{made["connection"]}')
        for r in by(a, 'Role', 'name', ROLE):
            data = a.call('GET', f'/Role/{r["id"]}')['data']
            if entity in data:
                a.call('PUT', f'/Role/{r["id"]}', body={'data': {k: v for k, v in data.items() if k != entity}})
        if made.get('entity'):
            for row in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id'})['list']:
                a.call('DELETE', f'/{entity}/{row["id"]}')
            a.call('POST', '/EntityManager/action/removeEntity', body={'name': entity})

    path = ROOT / 'tests' / 'results' / 'mcp.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'mcp: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
