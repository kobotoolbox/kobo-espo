#!/usr/bin/env python3
"""
Made-up demo data for the manual's screenshots, put through the real path: submissions on
the Kobo test account's forms, picked up by the running bridges (deploy/bridges.sh), then
triaged and worked in EspoCRM by the seed users.

    python3 -I site/demo-data.py

First removes every case, contact, account, task, response and site in EspoCRM (the test
droplet's are all test output), and their notes and notifications; keeps users, roles,
teams and the seeded standards. Kobo projects are left as they are.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import BridgeError, admin, as_user, env  # noqa: E402
from staging import RealKobo  # noqa: E402

import subprocess  # noqa: E402

REQUESTS = [  # (who, email, org, project, category, priority, summary, description)
    ('Amara Okafor', 'amara.okafor@beta.example.org', 'beta', 'consortium_a', 'data', 'High',
     'Export to XLS times out',
     'Exporting the household survey (about 40,000 submissions) to XLS stops after a few minutes with "export failed". CSV works. We need the XLS for the cluster meeting on Thursday.'),
    ('Luis Herrera', 'luis.herrera@alpha.example.org', 'alpha', 'consortium_a', 'forms', 'Normal',
     'Cascading select not filtering',
     'In the distribution form, choosing a district still shows every village, not only that district\'s. The choice_filter is district=${district}.'),
    ('Grace Mwangi', 'grace.mwangi@gamma.example.org', 'gamma', 'consortium_a', 'access', 'Urgent',
     "New enumerators can't log in",
     'Twelve enumerators added yesterday get "invalid credentials" in KoboCollect. Data collection starts tomorrow morning.'),
    ('Tomas Lindqvist', 'tomas.lindqvist@delta.example.org', 'delta', 'consortium_b', 'integrations', 'High',
     'REST service stopped sending',
     'Our REST service to the dashboard has shown "failed" since Monday. Nothing changed on our side as far as we know.'),
    ('Priya Raman', 'priya.raman@epsilon.example.org', 'epsilon', 'consortium_b', 'training', 'Low',
     'KoboCollect refresher for new staff',
     'Could someone run a one-hour KoboCollect refresher for 15 new staff in December?'),
    ('Jonas Weber', 'jonas.weber@kobo.example.org', 'kobo', 'internal', 'other', 'Normal',
     'Help pages in Portuguese',
     'Partners in Mozambique asked whether the getting-started pages exist in Portuguese.'),
]
VOLUNTEERS = [
    ('Nadia Haddad', 'nadia.haddad@example.org', 'wash coordination', 'Arabic, English, French',
     'From 1 December, 6 weeks', 'in_country regional'),
    ('Kenji Sato', 'kenji.sato@example.org', 'data', 'English, Japanese', 'Remote, evenings (UTC)', 'remote'),
    ('Fatou Diallo', 'fatou.diallo@example.org', 'health translation', 'French, Wolof, English',
     'From 15 November, 3 months', 'in_country'),
    ('Ole Hansen', 'ole.hansen@example.org', 'logistics shelter', 'English, Norwegian', 'January', 'regional'),
]
SITES = [  # (response, code, name, type, region, installed, equipment, standard)
    ('eq1', 'EQ1-WP-001', 'Hilltop water point', 'water_point', 'North district', '2026-10-20',
     'Hand pump (India Mk II), 2 taps, soak pit', 'WASH-2'),
    ('eq1', 'EQ1-WP-002', 'Market square water point', 'water_point', 'North district', '2026-10-22',
     'Tap stand, 4 taps, 10 m³ tank', 'WASH-1'),
    ('eq1', 'EQ1-SO-001', 'Clinic solar system', 'solar', 'North district', '2026-10-25',
     '6 × 400 W panels, 10 kWh battery, inverter SN 44-1182', 'ENRG-1'),
    ('eq1', 'EQ1-HP-001', 'Riverside health post', 'health_post', 'River valley', '2026-10-28',
     'Tent clinic, cold chain fridge', 'HLTH-1'),
    ('eq1', 'EQ1-WP-003', 'School water point', 'water_point', 'River valley', '2026-11-01',
     'Hand pump, 1 tap', 'WASH-2'),
    ('eq2', 'EQ2-SH-001', 'Collective centre A', 'shelter', 'South coast', '2026-10-30',
     '40 family tents, 2 latrine blocks', ''),
    ('eq2', 'EQ2-WP-001', 'Harbour water point', 'water_point', 'South coast', '2026-11-02',
     'Bladder tank 5 m³, 6 taps', 'WASH-1'),
]
VISITS = [('EQ1-WP-001', '2026-11-04', 'needs_repair', 'Pump handle loose, seal leaking; spare seal needed.', 'Rui Roster'),
          ('EQ1-SO-001', '2026-11-04', 'operational', 'All panels clean, battery at 96 %.', 'Rana Roster')]


def picture(title, subtitle, colour):
    """A labelled stand-in for a photo (made up, and says so), as JPEG bytes."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (960, 640), colour)
    d = ImageDraw.Draw(img)
    try:
        big, small = ImageFont.truetype('Helvetica.ttc', 54), ImageFont.truetype('Helvetica.ttc', 30)
    except OSError:
        big = small = ImageFont.load_default()
    d.rectangle([30, 30, 930, 610], outline=(255, 255, 255), width=4)
    d.text((70, 240), title, fill='white', font=big)
    d.text((70, 320), subtitle, fill='white', font=small)
    d.text((70, 540), 'Made-up photo for the demo', fill=(235, 235, 235), font=small)
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=85)
    return out.getvalue()


def clean(a):
    for entity in ('Task', 'CSite', 'CResponse', 'Case', 'Contact', 'Account'):
        while True:
            rows = a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id'})['list']
            if not rows:
                break
            for r in rows:
                a.call('DELETE', f'/{entity}/{r["id"]}')
    for s in a.call('GET', '/CStandard', {'maxSize': 50, 'select': 'code'})['list']:
        if not s.get('code', '').startswith(('WASH-', 'ENRG-', 'HLTH-')):
            a.call('DELETE', f'/CStandard/{s["id"]}')
    subprocess.run([str(ROOT / 'tests' / 'db.sh'),
                    "delete from notification; delete from note where parent_type in "
                    "('Case','Contact','Account','Task','CResponse','CSite'); "
                    "delete from `case` where deleted=1; delete from contact where deleted=1; "
                    "delete from account where deleted=1; delete from task where deleted=1; "
                    "delete from c_response where deleted=1; delete from c_site where deleted=1;"],
                   check=True, capture_output=True)
    print('cleaned EspoCRM')


def wait_for(a, entity, attr, value, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        rows = a.call('GET', f'/{entity}', {'where[0][type]': 'equals', 'where[0][attribute]': attr,
                                           'where[0][value]': value, 'select': 'id,name'})['list']
        if rows:
            return rows[0]
        time.sleep(2)
    raise SystemExit(f'{entity} with {attr}={value} not made by the bridge within {timeout}s (deploy/bridges.sh?)')


def main():
    a = admin()
    clean(a)
    kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
    forms = {k: json.loads((ROOT / 'kobo' / 'forms' / f'{k}.json').read_text())
             for k in ('support-request', 'volunteer-availability', 'site-registration', 'site-visit')}
    uids = {k: kobo.deploy(f) for k, f in forms.items()}
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}

    # Workflow A: requests from Kobo, triaged
    subs = []
    for who, email, org, project, cat, prio, summary, desc in REQUESTS:
        files = ({'export-error.jpg': (picture('Export failed', 'XLS export, household survey, after 4 min',
                                               (150, 40, 40)), 'image/jpeg')} if cat == 'data' else {})
        subs.append(kobo.submit(uids['support-request'], {
            'requester_name': who, 'requester_email': email, 'organisation': org, 'project': project,
            'category': cat, 'priority': prio, 'summary': summary, 'description': desc,
            **({'attachment': 'export-error.jpg'} if files else {})}, files=files))
        time.sleep(2)
    cases = [wait_for(a, 'Case', 'cKoboSubmissionUuid', s['_uuid']) for s in subs]
    print(f'{len(cases)} cases from Kobo')
    triager = as_user('triager')
    triager.call('PUT', f'/Case/{cases[2]["id"]}', body={'assignedUserId': user['partner-a'], 'status': 'Assigned'})
    triager.call('PUT', f'/Case/{cases[3]["id"]}', body={'assignedUserId': user['staff-2'], 'status': 'Assigned'})
    as_user('partner-a').call('POST', '/Note', body={
        'type': 'Post', 'parentType': 'Case', 'parentId': cases[2]['id'],
        'post': 'Their accounts were created on the wrong server (EU). Recreating them on the global server now.'})
    as_user('staff-1').call('PUT', f'/Case/{cases[5]["id"]}', body={'assignedUserId': user['staff-1'],
                                                                     'status': 'Assigned'})

    # Workflow B: volunteers sign up; two responses with their boards
    for name, email, skills, langs, avail, dep in VOLUNTEERS:
        kobo.submit(uids['volunteer-availability'], {'full_name': name, 'email': email, 'skills': skills,
                                                     'languages': langs, 'availability': avail, 'deployment': dep})
    staff = as_user('staff-1')
    eq1 = staff.call('POST', '/CResponse', body={
        'name': 'Earthquake response, Testland North', 'status': 'Active', 'emergencyType': 'Earthquake',
        'country': 'Testland', 'startDate': '2026-10-18', 'teamsIds': [team['Response: Test EQ 1']],
        'leadId': user['staff-1'], 'assignedUserId': user['staff-1'],
        'description': 'M6.8 earthquake on 17 October. Kobo supports the WASH and shelter clusters with forms and data.'})
    eq2 = staff.call('POST', '/CResponse', body={
        'name': 'Flood response, Testland South', 'status': 'Active', 'emergencyType': 'Flood',
        'country': 'Testland', 'startDate': '2026-10-28', 'teamsIds': [team['Response: Test EQ 2']],
        'leadId': user['staff-1'], 'assignedUserId': user['staff-1']})
    starter = {t['name']: t for t in a.call('GET', '/Task', {'maxSize': 50, 'select': 'name', 'where[0][type]': 'equals',
                                                             'where[0][attribute]': 'cResponseId', 'where[0][value]': eq1['id']})['list']}
    staff.call('PUT', f'/Task/{starter["Set up the Kobo project"]["id"]}', body={'status': 'Completed'})
    staff.call('PUT', f'/Task/{starter["Confirm the roster"]["id"]}', body={'status': 'Started'})
    staff.call('PUT', f'/Task/{starter["Comms plan"]["id"]}', body={'assignedUserId': user['roster-2'], 'status': 'Not Started'})
    for name, who, status, due, collab in (
            ('Map water points in North district', 'roster-1', 'Started', '2026-11-08', ['volunteer-2']),
            ('Translate the household form to French', 'volunteer-2', 'Not Started', '2026-11-10', []),
            ('Check the clinic solar system', 'roster-2', 'Blocked', '2026-11-07', []),
            ('Train enumerators on the site visit form', 'roster-1', 'Backlog', None, [])):
        staff.call('POST', '/Task', body={'name': name, 'cResponseId': eq1['id'], 'assignedUserId': user[who],
                                          'status': status, 'dateEndDate': due,
                                          'collaboratorsIds': [user[who]] + [user[c] for c in collab]})
    staff.call('POST', '/Task', body={'name': 'Assess the collective centres', 'cResponseId': eq2['id'],
                                      'assignedUserId': user['volunteer-1'], 'status': 'Started'})
    blocked = a.call('GET', '/Task', {'select': 'name', 'where[0][type]': 'equals', 'where[0][attribute]': 'name',
                                      'where[0][value]': 'Check the clinic solar system'})['list'][0]
    as_user('roster-2').call('POST', '/Note', body={'type': 'Post', 'parentType': 'Task', 'parentId': blocked['id'],
                                                    'post': 'Waiting for the inverter manual from the supplier. @staff-1 can you chase?'})

    # Workflow C: sites registered from Kobo, then visited
    time.sleep(70)  # the sites bridge puts responses.csv on the registration form (BRIDGE_LIST_MIN_SECONDS)
    for resp, code, name, kind, region, installed, equipment, std in SITES:
        kobo.submit(uids['site-registration'], {
            'response': (eq1 if resp == 'eq1' else eq2)['id'], 'site_code': code, 'site_name': name,
            'site_type': kind, 'region': region, 'installed': installed, 'equipment': equipment,
            'photo': f'{code}.jpg', 'end': datetime.now().astimezone().isoformat(timespec='milliseconds'),
            **({'standard': std} if std else {})},
            files={f'{code}.jpg': (picture(name, f'{code} · {region}', (40, 100, 150)), 'image/jpeg')})
    for code in [s[1] for s in SITES]:
        wait_for(a, 'CSite', 'siteCode', code)
    print(f'{len(SITES)} sites from Kobo')
    time.sleep(70)  # sites.csv onto the visit form
    for code, date, cond, notes, who in VISITS:
        kobo.submit(uids['site-visit'], {'site': code, 'visit_date': date, 'condition': cond,
                                         'visit_notes': notes, 'visitor': who, 'photo': f'visit-{code}.jpg'},
                    files={f'visit-{code}.jpg': (picture(f'Visit to {code}', notes[:48],
                                                         (160, 110, 30) if cond == 'needs_repair' else (50, 120, 70)),
                                                 'image/jpeg')})
    time.sleep(45)
    print('done: requests, volunteers, two responses with tasks, sites and visits')


if __name__ == '__main__':
    try:
        main()
    except BridgeError as e:
        sys.exit(f'demo data failed: {e}')
