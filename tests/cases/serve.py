#!/usr/bin/env python3
"""
Kobo connections made in EspoCRM (plans/kobo-connections-plan.md, phases 2 and 3): K1-K5,
with the fake Kobo, against the test droplet. K5: a template proposed from a form with
every question type (kobo-espo-bridge's propose.py) set up and run, on an entity made for
the test (CSrvEvery, removed at the end), and the record compared with propose.preview().

    python3 -I tests/cases/serve.py

Makes "SRV ..." connection records for a service of its own (Run by: tests-serve), runs
`bridge.py serve once` as that service, and removes what it made (records, contacts, the
connection's API user and role) at the end. Writes tests/results/serve.json.
"""
import importlib.util
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

RUN = str(int(time.time()))[-6:]
NAME = 'tests-serve'
FORM = json.loads((ROOT / 'kobo' / 'forms' / 'volunteer-availability.json').read_text())
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def template(form_name):
    """volunteer.toml for another form, without its [bridge] user: the connection gets its own."""
    text = (ROOT / 'kobo' / 'templates' / 'volunteer.toml').read_text()
    head, rest = text.split('[form]', 1)
    head = head.split('[bridge]')[0]
    rest = rest.replace('"Volunteer availability (espo-kobo test)"', f'"{form_name}"', 1)
    return head + '[form]' + rest


def volunteer(email):
    return {'full_name': f'Serve Tester {RUN}', 'email': email, 'skills': 'wash', 'languages': 'en',
            'availability': 'now', 'deployment': 'remote'}


def main():
    a = admin()
    from fake_kobo import FakeKobo
    kobo = FakeKobo(token='fake-' + RUN).start()
    form_name = f'Volunteer sign-up (serve test {RUN})'
    uid = kobo.add_form(form_name, {**FORM, 'settings': {**FORM.get('settings', {}), 'form_title': form_name}})
    work = Path(tempfile.mkdtemp(prefix='bridge-serve-'))
    (work / 'token').write_text(kobo.token)
    keys = work / 'bridge.secrets'
    keys.write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
    keys.chmod(0o600)
    env = {'PATH': os.environ['PATH'], 'ESPO_URL': URL, 'BRIDGE_SECRETS': str(keys), 'KOBO_URL': kobo.url,
           'KOBO_TOKEN_FILE': str(work / 'token'), 'BRIDGE_STATE_DIR': str(work / 'state'), 'BRIDGE_NAME': NAME,
           'BRIDGE_LIST_MIN_SECONDS': '0'}

    def serve():
        out = subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'bridge.py'), 'serve', 'once'],
                             env=env, capture_output=True, text=True)
        return out.returncode, out.stdout + out.stderr

    def get(rec):
        return a.call('GET', f'/CKoboConnection/{rec["id"]}')

    made, entity_made = [], []
    try:
        # --- K1: a connection made in EspoCRM runs in the next pass, with its own API user -
        serve()  # the first serve on an instance makes the entity (made already: nothing)
        rec = a.call('POST', '/CKoboConnection', body={'name': f'SRV Volunteers {RUN}', 'runBy': NAME,
                                                       'active': True, 'template': template(form_name)})
        made.append(rec)
        email1 = f'serve-1-{RUN}@example.org'
        kobo.submit(uid, volunteer(email1))
        code, log = serve()
        got = get(rec)
        check('K1', 'a connection made in EspoCRM: one pass, and the submission is a Contact',
              code == 0 and len(by(a, 'Contact', 'emailAddress', email1)) == 1, log[-800:])
        user = got.get('apiUser') or ''
        check('K1', 'with an API user of its own (kobo-conn-<name>), not the shared default',
              user == f'kobo-conn-srv-volunteers-{RUN}' and by(a, 'User', 'userName', user)
              and not by(a, 'User', 'userName', 'kobo-bridge'), user)
        check('K1', 'its status in the record: OK, the last pass, what the template makes',
              got.get('status') == 'ok' and got.get('lastPass') and got.get('recordEntity') == 'Contact'
              and got.get('koboForm') == form_name and got.get('routeTeams') == 'Roster and volunteers'
              and got.get('notifyUsers') == 'staff-1' and 'created 1' in (got.get('lastCounts') or ''),
              {k: got.get(k) for k in ('status', 'lastPass', 'recordEntity', 'koboForm', 'routeTeams',
                                       'notifyUsers', 'lastCounts', 'lastError')})

        # --- K2: a broken template says why; the other connections go on ---------------------
        broken = a.call('POST', '/CKoboConnection', body={'name': f'SRV Broken {RUN}', 'runBy': NAME,
                                                          'active': True, 'template': '[form\nname = "x"'})
        made.append(broken)
        email2 = f'serve-2-{RUN}@example.org'
        kobo.submit(uid, volunteer(email2))
        code, log = serve()
        bad = get(broken)
        check('K2', 'a template that isn\'t TOML: Setup failed, and Last error says why',
              bad.get('status') == 'setup_failed' and (bad.get('lastError') or '').startswith('template:'),
              {k: bad.get(k) for k in ('status', 'lastError')})
        check('K2', 'the other connection still ran (and the pass exits 1)',
              code == 1 and len(by(a, 'Contact', 'emailAddress', email2)) == 1, log[-800:])
        a.call('PUT', f'/CKoboConnection/{broken["id"]}', body={'active': False})

        # --- K3: paused, then active again --------------------------------------------------
        a.call('PUT', f'/CKoboConnection/{rec["id"]}', body={'active': False})
        email3 = f'serve-3-{RUN}@example.org'
        kobo.submit(uid, volunteer(email3))
        code, log = serve()
        check('K3', 'paused: no Contact, the record says Paused',
              code == 0 and not by(a, 'Contact', 'emailAddress', email3) and get(rec).get('status') == 'paused',
              get(rec).get('status'))
        a.call('PUT', f'/CKoboConnection/{rec["id"]}', body={'active': True})
        code, log = serve()
        check('K3', 'active again: the waiting submission comes in',
              code == 0 and len(by(a, 'Contact', 'emailAddress', email3)) == 1, log[-800:])

        # --- K4: the template edited in EspoCRM: set up again in the next pass ---------------
        a.call('PUT', f'/CKoboConnection/{rec["id"]}', body={'template': template(form_name) + '\n# edited\n'})
        code, log = serve()
        check('K4', 'the template edited in EspoCRM: setup runs again in the next pass',
              code == 0 and 'setting up again' in log and get(rec).get('status') == 'ok', log[-800:])
        a.call('PUT', f'/CKoboConnection/{rec["id"]}', body={'active': False})

        # --- K5: a proposed template, as it is: set up, run, and as previewed ---------------
        sys.path.insert(0, str(BRIDGE_DIR))
        import bridge
        import propose
        spec = importlib.util.spec_from_file_location('bridge_test_propose', BRIDGE_DIR / 'tests' / 'test_propose.py')
        every = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(every)
        title = f'Every question (serve test {RUN})'
        content = {**every.EVERY, 'settings': {'form_title': title}}
        every_uid = kobo.add_form(title, content)
        a.call('POST', '/EntityManager/action/createEntity', body={
            'name': 'SrvEvery', 'type': 'Base', 'labelSingular': 'Srv every', 'labelPlural': 'Srv every', 'stream': True})
        entity_made.append('CSrvEvery')
        proposal = propose.propose(content, 'CSrvEvery', team='Internal Kobo')
        conn = a.call('POST', '/CKoboConnection', body={'name': f'SRV Every {RUN}', 'runBy': NAME, 'active': True,
                                                        'template': proposal['template']})
        made.append(conn)
        sub = kobo.submit(every_uid, {
            'end': '2026-11-06T11:30:00.000+01:00', 'site_name': f'SRV Well {RUN}', 'notes': 'Line one\nline two',
            'counts/people': 12, 'counts/litres_per_day': 3.5, 'counts/score': 7, 'visit_date': '2026-11-05',
            'seen_at': '2026-11-05T09:15:00.000-05:00', 'opening_time': '08:00:00.000+01:00', 'working': 'no',
            'risks': 'flood fire', 'site': 'EQ1-WP-001', 'location': '-1.28 36.82 1700 5', 'meter': 'M-42',
            'consent': 'OK', 'photo': 'well.jpg'}, files={'well.jpg': (b'\xff\xd8\xff fake jpeg', 'image/jpeg')})
        code, log = serve()
        got = by(a, 'CSrvEvery', 'cKoboSubmissionUuid', sub['_uuid'])
        record = a.call('GET', f'/CSrvEvery/{got[0]["id"]}') if got else {}
        expected = propose.preview(bridge.parse_template(proposal['template']), sub, content, kobo.url, every_uid)
        differ = {k: (v, record.get(k)) for k, v in expected.get('record', {}).items()
                  if record.get(k) != v}
        check('K5', 'a proposed template for every question type: set up and run as it is',
              code == 0 and len(got) == 1 and get(conn).get('status') == 'ok', log[-1200:])
        check('K5', 'the record is what the preview said', got and not differ, differ)
        check('K5', 'the photo is copied onto it, in its Files from Kobo',
              list((record.get('koboFilesNames') or {}).values()) == ['well.jpg'] == expected.get('files'),
              {'record': record.get('koboFilesNames'), 'preview': expected.get('files')})
        check('K5', 'in the route\'s team', record.get('teamsNames') and list(record['teamsNames'].values()) == ['Internal Kobo'],
              record.get('teamsNames'))
    finally:
        kobo.stop()
        for email in (f'serve-{i}-{RUN}@example.org' for i in (1, 2, 3)):
            for c in by(a, 'Contact', 'emailAddress', email):
                a.call('DELETE', f'/Contact/{c["id"]}')
        for rec in made:
            user = a.call('GET', f'/CKoboConnection/{rec["id"]}').get('apiUser')
            for u in by(a, 'User', 'userName', user) if user else []:
                a.call('DELETE', f'/User/{u["id"]}')
            for r in by(a, 'Role', 'name', f'Kobo connection: {user}') if user else []:
                a.call('DELETE', f'/Role/{r["id"]}')
            a.call('DELETE', f'/CKoboConnection/{rec["id"]}')
        for entity in entity_made:
            for row in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id'})['list']:
                a.call('DELETE', f'/{entity}/{row["id"]}')
            a.call('POST', '/EntityManager/action/removeEntity', body={'name': entity})

    path = ROOT / 'tests' / 'results' / 'serve.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'serve: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
