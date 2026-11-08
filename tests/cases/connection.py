#!/usr/bin/env python3
"""
The Kobo -> EspoCRM connection end to end: T1-T7, T12, and Workflow C (sites and lists).

    python3 -I tests/cases/connection.py [--kobo fake|real] [--skip-espo-down]

The real bridge (kobo-espo-bridge's bridge.py, run as a process, as in its container) and its
setup.py, against the test droplet's EspoCRM. Kobo: a fake one on this machine
(kobo-espo-bridge/fake_kobo.py, the default), or a real one (KOBO_URL, KOBO_TOKEN in .env,
a throwaway test account; tests/staging.py deploys the forms there first).

T3 stops EspoCRM on the droplet for a minute (docker compose stop espocrm) unless
--skip-espo-down. Writes tests/results/connection-<kobo>.json.
"""
import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, BridgeError, Espo, admin, as_user, env, secrets  # noqa: E402

from bridges import SECRETS, Bridge, by, notifications  # noqa: E402

FORMS = {k: json.loads((ROOT / 'kobo' / 'forms' / f'{k}.json').read_text())
         for k in ('support-request', 'volunteer-availability', 'site-registration', 'site-visit')}
TEMPLATES = {'support-request': 'support-request', 'volunteer-availability': 'volunteer',
             'site-registration': 'site-registration', 'site-visit': 'site-visit'}
RUN = str(int(time.time()))[-6:]  # makes this run's emails and site codes its own
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=sorted))  # sets, also inside dicts
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def status(fn):
    try:
        fn()
        return 200
    except BridgeError as e:
        return e.status


def droplet(cmd):
    return subprocess.run(['ssh', '-o', 'ControlMaster=auto', '-o', 'ControlPath=/tmp/kobo-espo-ssh-%C',
                           '-o', 'ControlPersist=10m', env('ESPO_SSH'),
                           f'cd /root/kobo-espo && docker compose -p kobo-espo {cmd}'],
                          capture_output=True, text=True)


def png(rgb=(200, 80, 40), size=64):
    """A small real PNG (stdlib only), for the media tests."""
    import struct
    import zlib
    raw = b''.join(b'\x00' + bytes(rgb) * size for _ in range(size))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def download(espo, attachment_id):
    """An attachment's bytes, as a user opening it in EspoCRM gets them."""
    import urllib.request
    req = urllib.request.Request(f'{URL}/?entryPoint=download&id={attachment_id}', headers=espo.headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def support(project, email, org='alpha', **kw):
    return {'requester_name': f'Test Requester {RUN}', 'requester_email': email, 'organisation': org,
            'project': project, 'category': 'forms', 'priority': 'High',
            'summary': f'Form will not deploy ({RUN})',
            'description': 'Deploying gives an error about a choice list.', **kw}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kobo', choices=['fake', 'real'], default='fake')
    ap.add_argument('--skip-espo-down', action='store_true')
    args = ap.parse_args()
    a = admin()
    if not SECRETS.exists():
        SECRETS.write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
        SECRETS.chmod(0o600)

    if args.kobo == 'fake':
        from fake_kobo import FakeKobo
        kobo = FakeKobo(token='fake-' + RUN).start()
        kobo_url, token = kobo.url, kobo.token
        uids = {k: kobo.add_form(f['settings']['form_title'], f) for k, f in FORMS.items()}
        submit = kobo.submit
    else:
        from staging import RealKobo
        kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
        kobo_url, token = kobo.url, kobo.token
        uids = kobo.deploy_all(FORMS)
        submit = kobo.submit

    bridges = {k: Bridge(TEMPLATES[k], kobo_url, token) for k in FORMS}
    for b in bridges.values():
        b.setup()
    print(f'setup done for {len(bridges)} templates; Kobo {args.kobo} at {kobo_url}')
    intake, vol, sites, visits = (bridges[k] for k in FORMS)
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}

    # --- T1: a support request becomes a Case with its requester ---------------------------
    email_a = f'req-a-{RUN}@example.org'
    shot = png()
    started = time.time()
    s1 = submit(uids['support-request'], support('consortium_a', email_a, org='alpha', attachment='screenshot.png'),
                files={'screenshot.png': (shot, 'image/png')})
    code, log, st = intake.once()
    latency = time.time() - started
    cases = by(a, 'Case', 'cKoboSubmissionUuid', s1['_uuid'])
    check('T1', 'one case for the submission', len(cases) == 1, log[-500:] if len(cases) != 1 else '')
    case = a.call('GET', f'/Case/{cases[0]["id"]}') if cases else {}
    check('T1', 'name, category, priority, project from the answers',
          case.get('name') == f'Forms and XLSForm: Form will not deploy ({RUN})' and case.get('cCategory') == 'forms'
          and case.get('priority') == 'High' and case.get('cProject') == 'consortium_a',
          {k: case.get(k) for k in ('name', 'cCategory', 'priority', 'cProject')})
    check('T1', 'in the Consortium A team only', case.get('teamsIds') == [team['Project: Consortium A']], case.get('teamsNames'))
    check('T1', 'source "Kobo form", Kobo link and ids', case.get('cSource') == 'Kobo form'
          and case.get('cKoboSubmissionId') == s1['_id'] and uids['support-request'] in (case.get('cKoboLink') or ''))
    contact = a.call('GET', f'/Contact/{case["contactId"]}') if case.get('contactId') else {}
    check('T1', 'requester Contact by email, with their name', contact.get('emailAddress') == email_a
          and contact.get('lastName') == RUN and contact.get('firstName') == 'Test Requester',
          {k: contact.get(k) for k in ('emailAddress', 'firstName', 'lastName')})
    check('T1', 'Account "Org Alpha" linked to the case and the contact',
          case.get('accountName') == 'Org Alpha' and contact.get('accountId') == case.get('accountId'))
    check('T1', 'description has the request', 'choice list' in (case.get('description') or ''))
    files = case.get('attachmentsIds') or []
    check('T1', 'media: the attached file is copied onto the case', len(files) == 1
          and (case.get('attachmentsNames') or {}).get(files[0]) == 'screenshot.png', case.get('attachmentsNames'))
    check('T1', 'media: the same bytes, and the triager can open it', files and download(as_user('triager'), files[0]) == shot)
    try:
        leaked = download(as_user('partner-b'), files[0]) if files else None
    except Exception as e:  # noqa: BLE001 - any refusal will do
        leaked = None
        refusal = getattr(e, 'code', type(e).__name__)
    check('T1', "media: partner-b (Consortium B) can't open it", leaked is None, locals().get('refusal'))
    check('T1', 'latency of one pass (submission -> case), seconds', True, round(latency, 1))

    # --- T2: delivered again -> still one case ----------------------------------------------
    intake.forget()
    code, log, st = intake.once()
    check('T2', 'a lost ledger rescans everything: no second case', len(by(a, 'Case', 'cKoboSubmissionUuid', s1['_uuid'])) == 1
          and st['counts']['existing'] >= 1, st['counts'])
    check('T2', 'and no second contact or account', len(by(a, 'Contact', 'emailAddress', email_a)) == 1
          and len(by(a, 'Account', 'name', 'Org Alpha')) == 1)
    s1b = submit(uids['support-request'], support('consortium_a', email_a, org='alpha', summary=f'Second ({RUN})'))
    intake.once()
    check('T2', "the same requester's next request reuses their contact",
          len(by(a, 'Contact', 'emailAddress', email_a)) == 1
          and by(a, 'Case', 'cKoboSubmissionUuid', s1b['_uuid'])[0].get('contactId') == case.get('contactId'))

    # --- T3: Kobo or EspoCRM down: failure visible, nothing lost ----------------------------
    if args.kobo == 'fake':
        kobo.down = True
        code, log, st = intake.once()
        check('T3', 'Kobo down: the pass fails and status.json says why', code == 1 and not st['ok'] and '503' in (st['error'] or ''),
              st.get('error'))
        kobo.down = False
    if not args.skip_espo_down:
        stop = droplet('stop espocrm')
        s3 = submit(uids['support-request'], support('internal', f'req-down-{RUN}@example.org', org='kobo',
                                                     summary=f'While EspoCRM was down ({RUN})'))
        code, log, st = intake.once()
        check('T3', 'EspoCRM stopped: the pass fails, visibly', code == 1 and not st['ok'], st.get('error'))
        cursor_before = st['counts']
        start = droplet('start espocrm')
        for _ in range(60):
            try:
                a.call('GET', '/App/user')
                break
            except BridgeError:
                time.sleep(3)
        code, log, st = intake.once()
        made = by(a, 'Case', 'cKoboSubmissionUuid', s3['_uuid'])
        check('T3', 'EspoCRM back: the next pass makes the case, once', code == 0 and len(made) == 1 and st['ok'],
              {'stop': stop.returncode, 'start': start.returncode, 'counts': st['counts']})
        check('T3', 'that case is in the Internal Kobo team', made and made[0].get('teamsIds') == [team['Internal Kobo']]
              if 'teamsIds' in (made[0] if made else {}) else bool(made))

    # --- T4: a missing answer, an invalid email -> clear error, nothing half-made -------------
    bad_email = f'not-an-email-{RUN}'
    missing = submit(uids['support-request'], support('consortium_b', f'req-missing-{RUN}@example.org', summary=''))
    invalid = submit(uids['support-request'], support('consortium_b', bad_email))
    code, log, st = intake.once()
    failed = intake.failed()
    check('T4', 'the pass goes on (the good ones still go through)', code == 0 and st['failed'] >= 2, st)
    check('T4', 'missing answer: "required answer missing: summary" in the ledger',
          f'submission {missing["_id"]}' in failed and 'required answer missing: summary' in failed, failed)
    check('T4', 'missing answer: no contact made for it', not by(a, 'Contact', 'emailAddress', f'req-missing-{RUN}@example.org'))
    check('T4', 'invalid email: refused by EspoCRM, recorded with its reason', f'submission {invalid["_id"]}' in failed
          and 'HTTP 400' in failed, failed)
    check('T4', 'no case for either', not by(a, 'Case', 'cKoboSubmissionUuid', missing['_uuid'])
          and not by(a, 'Case', 'cKoboSubmissionUuid', invalid['_uuid']))
    check('T4', 'no answers in the error messages (status.json)', bad_email not in json.dumps(st))

    # --- T5: triager notified, assigns, assignee notified; escalation -------------------------
    triager = as_user('triager')
    check('T5', 'triager notified of the new Consortium A case (mention)', bool(notifications(triager, case.get('id'))),
          [n.get('relatedParentName') for n in triager.call('GET', '/Notification', {'maxSize': 10})['list']])
    note = [n for n in a.call('GET', f'/Case/{case["id"]}/stream', {'maxSize': 20})['list'] if n.get('type') == 'Post']
    check('T5', 'the note on the case says what it is and mentions the triager',
          any('@triager' in (n.get('post') or '') for n in note))
    check('T5', 'triager assigns it to staff-1', status(lambda: triager.call(
        'PUT', f'/Case/{case["id"]}', body={'assignedUserId': user['staff-1']})) == 200)
    assigned_at = a.call('GET', f'/Case/{case["id"]}')['modifiedAt']
    check('T5', 'staff-1 notified of the assignment', bool(notifications(as_user('staff-1'), case['id'])))
    # partner-b shares a team (Consortium B) with the triager, not with the case: EspoCRM's
    # own check lets this through; the Case API Before Save Script refuses it
    check('T5', 'triager cannot assign it to someone outside its team (partner-b, Consortium B)',
          status(lambda: triager.call('PUT', f'/Case/{case["id"]}', body={'assignedUserId': user['partner-b']})) in (400, 403))
    check('T5', 'triager cannot put it in a second team (one team per case)', status(lambda: triager.call(
        'PUT', f'/Case/{case["id"]}', body={'teamsIds': [team['Project: Consortium A'], team['Project: Consortium B']]})) in (400, 403))
    created = datetime.strptime(by(a, 'Case', 'cKoboSubmissionUuid', s1b['_uuid'])[0]['createdAt'],
                                '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    wait = intake.t['escalation']['after_hours'] * 3600 - (time.time() - created) + 5
    if wait > 0:
        print(f'waiting {wait:.0f}s for the escalation interval')
        time.sleep(wait)
    code, log, st = intake.once()
    second = by(a, 'Case', 'cKoboSubmissionUuid', s1b['_uuid'])[0]
    # By this pass or an earlier one (after T3's minute without EspoCRM, the wait is often
    # over before now): once, and by this connection only
    escalations = [n for n in a.call('GET', f'/Case/{second["id"]}/stream', {'maxSize': 20})['list']
                   if (n.get('post') or '').startswith('Still unassigned')]
    check('T5', 'escalation: the unassigned case is mentioned to staff-1 (lead for Consortium A), once',
          bool(notifications(as_user('staff-1'), second['id'])) and len(escalations) == 1,
          {'escalations': len(escalations), 'this pass': st['counts']['escalated']})
    # (It may have been escalated before it was assigned, on a slow run: that's right)
    check('T5', 'escalation: no escalation of the case after it was assigned', not any(
        'unassigned' in (n.get('post') or '').lower() and n['createdAt'] > assigned_at
        for n in a.call('GET', f'/Case/{case["id"]}/stream', {'maxSize': 20})['list']))
    check('T5', 'escalation happens once', intake.once()[2]['counts']['escalated'] == 0)

    # --- T6: each consortium's requests land in its own team ---------------------------------
    sb = submit(uids['support-request'], support('consortium_b', f'req-b-{RUN}@example.org', org='delta'))
    si = submit(uids['support-request'], support('internal', f'req-i-{RUN}@example.org', org='kobo'))
    code, log, st = intake.once()
    cb = by(a, 'Case', 'cKoboSubmissionUuid', sb['_uuid'])
    if not cb:
        print(log[-1500:])
    ci = by(a, 'Case', 'cKoboSubmissionUuid', si['_uuid'])
    check('T6', 'Consortium B request -> Consortium B team', cb and a.call('GET', f'/Case/{cb[0]["id"]}')['teamsIds'] == [team['Project: Consortium B']])
    check('T6', 'internal request -> Internal Kobo team', ci and a.call('GET', f'/Case/{ci[0]["id"]}')['teamsIds'] == [team['Internal Kobo']])
    check('T6', 'partner-a sees the A case, not the B one', status(lambda: as_user('partner-a').call('GET', f'/Case/{case["id"]}')) == 200
          and status(lambda: as_user('partner-a').call('GET', f'/Case/{cb[0]["id"]}')) == 403)
    acc_delta = by(a, 'Account', 'name', 'Org Delta')
    check('T6', "Org Delta's account is in Consortium B's team only (partner-a can't read it)",
          acc_delta and status(lambda: as_user('partner-a').call('GET', f'/Account/{acc_delta[0]["id"]}')) == 403)

    # --- T7: volunteer sign-up -> Contact with profileType ------------------------------------
    vemail = f'vol-{RUN}@example.org'
    v1 = submit(uids['volunteer-availability'], {'full_name': f'Vera {RUN}', 'email': vemail, 'skills': 'wash data',
                                                 'languages': 'English, French', 'availability': 'From 1 Dec, 6 weeks',
                                                 'deployment': 'remote'})
    code, log, st = vol.once()
    vc = by(a, 'Contact', 'emailAddress', vemail)
    vc = a.call('GET', f'/Contact/{vc[0]["id"]}') if vc else {}
    check('T7', 'a Contact with profile Volunteer, skills, availability', vc.get('cProfileType') == 'Volunteer'
          and vc.get('cSkills') == ['wash', 'data'] and vc.get('cAvailability') == 'From 1 Dec, 6 weeks',
          {k: vc.get(k) for k in ('cProfileType', 'cSkills', 'cAvailability')})
    check('T7', 'in the roster pool team', vc.get('teamsIds') == [team['Roster and volunteers']])
    check('T7', 'not made a user (that stays a person\'s decision)', not by(a, 'User', 'emailAddress', vemail))
    submit(uids['volunteer-availability'], {'full_name': f'Vera {RUN}', 'email': vemail.upper(), 'skills': 'wash',
                                           'languages': 'English', 'availability': 'From 15 Dec'})
    code, log, st = vol.once()
    vcs = by(a, 'Contact', 'emailAddress', vemail)
    check('T7', 'signing up again (same email, other case) updates that contact', len(vcs) == 1
          and st['counts']['merged'] == 1 and a.call('GET', f'/Contact/{vcs[0]["id"]}')['cAvailability'] == 'From 15 Dec', st['counts'])
    check('T7', 'staff-1 notified of the sign-up', bool(notifications(as_user('staff-1'), vcs[0]['id'])))

    # --- T12: each API key can do its job only -------------------------------------------------
    keys = secrets('bridge')
    for key, can, cannot in (
            ('ESPO_INTAKE_API_KEY', ['Case', 'Contact', 'Account'], ['Task', 'CResponse', 'CSite', 'User']),
            ('ESPO_VOLUNTEERS_API_KEY', ['Contact'], ['Case', 'Account', 'Task', 'CResponse', 'User']),
            ('ESPO_SITES_API_KEY', ['CSite', 'CResponse', 'CStandard'], ['Case', 'Contact', 'Task', 'User']),
            ('ESPO_SITE_LISTS_API_KEY', ['CSite'], ['Case', 'Contact', 'Task', 'CResponse', 'User'])):
        k = Espo(URL, api_key=keys[key])
        listed = {e: status(lambda e=e: k.call('GET', f'/{e}', {'maxSize': 1})) for e in can + cannot}
        users = k.call('GET', '/User', {'maxSize': 50}).get('list', []) if listed['User'] == 200 else []
        check('T12', f'{key}: reads {", ".join(can)}', all(listed[e] == 200 for e in can), listed)
        check('T12', f'{key}: refused {", ".join(e for e in cannot if e != "User")}; lists no users',
              all(listed[e] == 403 for e in cannot if e != 'User') and not users, {**listed, 'users': len(users)})
        check('T12', f'{key}: cannot delete', status(lambda: k.call('DELETE', f'/Case/{case["id"]}')) == 403)
    k = Espo(URL, api_key=keys['ESPO_INTAKE_API_KEY'])
    check('T12', 'intake key: cannot change a case it made (create only)', status(lambda: k.call(
        'PUT', f'/Case/{case["id"]}', body={'name': 'changed by the key'})) == 403)

    # --- Workflow C: sites, lists from EspoCRM, follow-up visits ----------------------------
    resp = by(a, 'CResponse', 'name', 'Test EQ 1 response') or [a.call('POST', '/CResponse', body={
        'name': 'Test EQ 1 response', 'status': 'Active', 'teamsIds': [team['Response: Test EQ 1']],
        'leadId': user['staff-1'], 'emergencyType': 'Earthquake', 'country': 'Testland'})]
    resp2 = by(a, 'CResponse', 'name', 'Test EQ 2 response') or [a.call('POST', '/CResponse', body={
        'name': 'Test EQ 2 response', 'status': 'Active', 'teamsIds': [team['Response: Test EQ 2']],
        'leadId': user['staff-1'], 'emergencyType': 'Earthquake', 'country': 'Testland'})]
    code, log, st = sites.once()
    media = kobo.media_of(uids['site-registration']) if hasattr(kobo, 'media_of') else kobo.media[uids['site-registration']]
    rows = list(csv.DictReader(io.StringIO(media.get('responses.csv', b'').decode())))
    check('C1', 'responses.csv on the registration form: the active responses, id and name only',
          {r['label'] for r in rows} >= {'Test EQ 1 response', 'Test EQ 2 response'}
          and all(set(r) == {'name', 'label'} for r in rows), rows[:3])
    std = list(csv.DictReader(io.StringIO(media.get('standards.csv', b'').decode())))
    check('C1', 'standards.csv: code, label, requirement, category', {r['name'] for r in std} >= {'WASH-1', 'ENRG-1'}
          and std[0].keys() == {'name', 'label', 'requirement', 'category'}, std[:2])
    code_1, code_2 = f'EQ1-WP-{RUN}', f'EQ2-SP-{RUN}'
    s_a = submit(uids['site-registration'], {'response': resp[0]['id'], 'site_code': code_1, 'site_name': f'Water point {RUN}',
                                              'site_type': 'water_point', 'region': 'North', 'installed': '2026-11-01',
                                              'equipment': 'Hand pump, model X', 'location': '1.23 4.56 0 5',
                                              'standard': 'WASH-2', 'end': '2026-11-05T14:21:06.502+05:30',
                                              'photo': 'site photo (1).png'},
               files={'site photo (1).png': (png((40, 120, 200)), 'image/png')})
    submit(uids['site-registration'], {'response': resp2[0]['id'], 'site_code': code_2, 'site_name': f'Solar {RUN}',
                                       'site_type': 'solar', 'region': 'South', 'installed': '2026-11-02',
                                       'equipment': '4 panels, 1 battery'})
    code, log, st = sites.once()
    site = by(a, 'CSite', 'siteCode', code_1)
    site = a.call('GET', f'/CSite/{site[0]["id"]}') if site else {}
    check('C2', 'a registration makes a Site, linked to its response', site.get('responseId') == resp[0]['id']
          and site.get('siteType') == 'water_point', {k: site.get(k) for k in ('responseId', 'siteType')} or log[-300:])
    wash2 = by(a, 'CStandard', 'code', 'WASH-2')
    check('C2', 'linked to its standard, looked up by the code picked', wash2 and site.get('standardId') == wash2[0]['id'],
          site.get('standardId'))
    check('C2', "the form's end time, in UTC", site.get('registeredAt') == '2026-11-05 08:51:06', site.get('registeredAt'))
    check('C2', 'its location also as latitude and longitude (for maps)',
          (site.get('location'), site.get('latitude'), site.get('longitude')) == ('1.23 4.56 0 5', 1.23, 4.56),
          {k: site.get(k) for k in ('location', 'latitude', 'longitude')})
    check('C2', "in its response's team (Site formula)", site.get('teamsIds') == [team['Response: Test EQ 1']])
    check('C2', "media: the site photo is on the site, with the answer's file name (Kobo stores site_photo_1.png)",
          list((site.get('photosNames') or {}).values()) == ['site photo (1).png'], site.get('photosNames'))
    submit(uids['site-registration'], {'response': resp[0]['id'], 'site_code': code_1, 'site_name': f'Water point {RUN}',
                                       'site_type': 'water_point', 'region': 'North', 'installed': '2026-11-01',
                                       'equipment': 'Hand pump, model X; new seal'})
    code, log, st = sites.once()
    check('C2', 'registering the same code again updates that site', len(by(a, 'CSite', 'siteCode', code_1)) == 1
          and 'new seal' in a.call('GET', f'/CSite/{site["id"]}')['equipment'] and st['counts']['merged'] == 1, st['counts'])
    code_3 = f'EQ1-XX-{RUN}'
    bad_std = submit(uids['site-registration'], {'response': resp[0]['id'], 'site_code': code_3, 'site_name': f'Unknown std {RUN}',
                                                 'site_type': 'other', 'region': 'North', 'installed': '2026-11-01',
                                                 'equipment': 'x', 'standard': 'NO-SUCH-STD'})
    code, log, st = sites.once()
    check('C2', 'a standard code EspoCRM has no record for: recorded, no site made',
          f'submission {bad_std["_id"]}' in sites.failed() and '0 CStandard records with that code' in sites.failed()
          and not by(a, 'CSite', 'siteCode', code_3), sites.failed())
    check('C2', "roster-1 (Response 1) sees the site; volunteer-1 (Response 2) doesn't",
          status(lambda: as_user('roster-1').call('GET', f'/CSite/{site["id"]}')) == 200
          and status(lambda: as_user('volunteer-1').call('GET', f'/CSite/{site["id"]}')) == 403)

    code, log, st = visits.once()
    vmedia = kobo.media_of(uids['site-visit']) if hasattr(kobo, 'media_of') else kobo.media[uids['site-visit']]
    srows = list(csv.DictReader(io.StringIO(vmedia.get('sites.csv', b'').decode())))
    check('C3', "sites.csv on Response 1's visit form: its sites, not Response 2's",
          code_1 in {r['name'] for r in srows} and code_2 not in {r['name'] for r in srows}, srows)
    check('C3', 'sites.csv columns: code, label, status, region only', srows and srows[0].keys() == {'name', 'label', 'status', 'region'})
    visit = submit(uids['site-visit'], {'site': code_1, 'visit_date': '2026-11-05', 'condition': 'needs_repair',
                                        'visit_notes': 'Seal leaking again', 'visitor': 'Rui Roster',
                                        'photo': 'leak.png'}, files={'leak.png': (png((90, 90, 90)), 'image/png')})
    code, log, st = visits.once()
    after = a.call('GET', f'/CSite/{site["id"]}')
    check('C3', 'a visit updates the site: status and last visit', after.get('status') == 'needs_repair'
          and after.get('lastVisit') == '2026-11-05', {k: after.get(k) for k in ('status', 'lastVisit')} or log[-300:])
    notes = [n.get('post') or '' for n in a.call('GET', f'/CSite/{site["id"]}/stream', {'maxSize': 20})['list']]
    check('C3', "and adds a note with what was found, marked with the visit's uuid",
          any('Seal leaking again' in n and visit['_uuid'] in n for n in notes))
    vnote = next((n for n in a.call('GET', f'/CSite/{site["id"]}/stream', {'maxSize': 20})['list']
                  if visit['_uuid'] in (n.get('post') or '')), {})
    check('C3', "media: the visit's photo is on its note", list((vnote.get('attachmentsNames') or {}).values()) == ['leak.png'],
          vnote.get('attachmentsNames'))
    visits.forget()
    visits.once()
    notes2 = [n.get('post') or '' for n in a.call('GET', f'/CSite/{site["id"]}/stream', {'maxSize': 20})['list']]
    check('C3', 'a visit is never applied twice (lost ledger)', sum(visit['_uuid'] in n for n in notes2) == 1)
    time.sleep(1)
    code, log, st = visits.once()
    vmedia = kobo.media_of(uids['site-visit']) if hasattr(kobo, 'media_of') else kobo.media[uids['site-visit']]
    srows = list(csv.DictReader(io.StringIO(vmedia.get('sites.csv', b'').decode())))
    check('C3', 'the list follows: sites.csv now shows the new status',
          any(r['name'] == code_1 and r['status'] == 'needs_repair' for r in srows), srows)
    bad = submit(uids['site-visit'], {'site': 'NO-SUCH-SITE', 'visit_date': '2026-11-05', 'condition': 'operational',
                                      'visitor': 'x'})
    code, log, st = visits.once()
    check('C3', 'a visit to an unknown site is recorded, not guessed', f'submission {bad["_id"]}' in visits.failed()
          and '0 CSite records' in visits.failed(), visits.failed())

    out = ROOT / 'tests' / 'results' / f'connection-{args.kobo}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'when': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'espo': URL,
                               'kobo': args.kobo, 'run': RUN, 'passed': sum(r['ok'] for r in results),
                               'failed': sum(not r['ok'] for r in results), 'results': results}, indent=2) + '\n')
    print(f'\n{sum(r["ok"] for r in results)}/{len(results)} passed; {out.relative_to(ROOT)}')
    sys.exit(0 if all(r['ok'] for r in results) else 1)


if __name__ == '__main__':
    main()
