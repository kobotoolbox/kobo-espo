#!/usr/bin/env python3
"""
Made-up demo data for the manual's screenshots, put through the real path: submissions on
the Kobo test account's forms, picked up by the running bridges (deploy/bridges.sh), then
triaged and worked in EspoCRM by the seed users.

    python3 -I site/demo-data.py
    python3 -I site/demo-data.py 5w     only add the 5W (Workflow E), removing nothing

First removes every case, contact, account, task, response, project, site, registration
and 5W activity in EspoCRM (the test droplet's are all test output), and their notes and
notifications; keeps users, roles, teams, the seeded standards, organisations and areas.
Kobo projects are left as they are.
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

# Workflow E: the Hurricane Melissa 5W, with the Melissa form's own codes and Jamaica's P-codes
MELISSA = 'Hurricane Melissa response, Jamaica'
MELISSA_PROJECTS = [('WASH', 'WASH'), ('SHELTER', 'Shelter'), ('EMERGENCY_TELECOMS', 'Emergency Telecommunications')]
REGISTRATIONS = [  # (organisation, its type, sectors, focal point, email)
    ('ORG_JRC', 'RED_CROSS_MOVEMENT', 'WASH SHELTER', 'Andrea Campbell', 'andrea.campbell@jrc.example.org'),
    ('ORG_UNICEF', 'UN_AGENCY', 'WASH', 'Marcus Reid', 'marcus.reid@unicef.example.org'),
    ('ORG_ADRA', 'INTERNATIONAL_NGO', 'SHELTER', 'Hannah Clarke', 'hannah.clarke@adra.example.org'),
    ('ORG_WFP', 'UN_AGENCY', 'EMERGENCY_TELECOMS', 'Daniel Okoro', 'daniel.okoro@wfp.example.org'),
    ('ORG_MERCYCORPS', 'INTERNATIONAL_NGO', 'WASH', 'Lucia Ferreira', 'lucia.ferreira@mercycorps.example.org'),
]
# (lead, its type, implementing (None: the lead), sector, activity type, title, status, resource type, unit,
#  start, end, communities: (parish, community, location type, quantity, targeted, reached))
REPORTS = [
    ('ORG_JRC', 'RED_CROSS_MOVEMENT', None, 'WASH', 'distribution_of_hygiene_kits', 'Hygiene kits for displaced families',
     'COMPLETED', 'wash', 'hygiene', '2026-10-31', '2026-11-05',
     [('JM14', 'JM141316', 'shelter', 420, 1600, 1520), ('JM14', 'JM140904', 'general_community', 180, 700, 690)]),
    ('ORG_UNICEF', 'UN_AGENCY', 'ORG_JRC', 'WASH', 'water_trucking', 'Water trucking to Black River and Santa Cruz',
     'IN_PROGRESS', 'wash', 'water', '2026-11-01', None,
     [('JM09', 'JM090203', 'general_community', 60000, 9000, 5200), ('JM09', 'JM090709', 'general_community', 35000, 6000, 2100)]),
    ('ORG_ADRA', 'INTERNATIONAL_NGO', None, 'SHELTER', 'emergency', 'Emergency shelter kits, Hanover',
     'IN_PROGRESS', 'non_food', 'shelter_kit', '2026-11-02', None,
     [('JM02', 'JM020410', 'general_community', 250, 1200, 650), ('JM02', 'JM020203', 'general_community', 150, 800, 300)]),
    ('ORG_JRC', 'RED_CROSS_MOVEMENT', None, 'SHELTER', 'nfi', 'Tarpaulins and mattresses, Westmoreland',
     'COMPLETED', 'non_food', 'tarpaulin', '2026-10-30', '2026-11-03',
     [('JM14', 'JM141402', 'general_community', 120, 400, 460)]),  # more reached than targeted: a data check
    ('ORG_WFP', 'UN_AGENCY', None, 'EMERGENCY_TELECOMS', 'other', 'Connectivity for collective centres',
     'IN_PROGRESS', 'it', 'communication', '2026-11-01', None,
     [('JM14', 'JM141410', 'shelter', 3, 900, 900), ('JM09', 'JM090215', 'school', 2, 500, 350)]),
    ('ORG_UNICEF', 'UN_AGENCY', None, 'WASH', 'hygiene_promotion_awareness_campaigns', 'Hygiene promotion in schools',
     'PLANNED', 'wash', 'hygiene', '2026-11-12', None,
     [('JM10', 'JM100519', 'school', 0, 3000, 0)]),
    ('ORG_IFRC', 'RED_CROSS_MOVEMENT', None, 'HEALTH', 'health_facility_rehabilitation_or_support',
     'Generators for health centres', 'COMPLETED', 'non_food', 'generator', '2026-11-03', '2026-11-20',  # ends after
     [('JM14', 'JM141301', 'health_facility', 2, 3000, 3000)]),  # today, yet completed: a data check
]


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
    for entity in ('Task', 'CFocalPoint', 'CActivityLocation', 'CActivity', 'CResponder', 'CSite', 'CProject',
                   'CResponse', 'Case', 'Contact', 'Account'):
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
                    "('Case','Contact','Account','Task','CResponse','CSite','CProject','CResponder','CActivity'); "
                    "delete from `case` where deleted=1; delete from contact where deleted=1; "
                    "delete from account where deleted=1; delete from task where deleted=1; "
                    "delete from c_response where deleted=1; delete from c_site where deleted=1; "
                    "delete from c_project where deleted=1; delete from c_responder where deleted=1; "
                    "delete from c_activity where deleted=1; delete from c_activity_location where deleted=1; "
                    "delete from c_focal_point where deleted=1;"],
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


def fivew(a, kobo, uids, team, user):
    """Workflow E: the Hurricane Melissa 5W: its cluster projects, organisations registering, their reports."""
    def team_of(name):
        if name not in team:
            team[name] = a.call('POST', '/Team', body={'name': name})['id']
        return team[name]
    if a.call('GET', '/CResponse', {'where[0][type]': 'equals', 'where[0][attribute]': 'name', 'where[0][value]': MELISSA,
                                    'select': 'id'})['list']:
        raise SystemExit(f'"{MELISSA}" is there already: run site/demo-data.py without 5w to start again')
    melissa = a.call('POST', '/CResponse', body={
        'name': MELISSA, 'status': 'Active', 'emergencyType': 'Cyclone', 'country': 'Jamaica', 'startDate': '2026-10-28',
        'teamsIds': [team_of('Response: Hurricane Melissa')], 'leadId': user['staff-1'], 'assignedUserId': user['staff-1'],
        'description': 'Category 5 hurricane, landfall on 28 October in the south-west. The 5W of the WASH, '
                       'shelter and telecommunications clusters.'})
    a.call('POST', f'/Team/{team["Response: Hurricane Melissa"]}/users', body={'id': user['staff-1']})
    for cluster, label in MELISSA_PROJECTS:
        a.call('POST', '/CProject', body={'name': f'{MELISSA} · {label}', 'responseId': melissa['id'], 'status': 'Active',
                                          'cluster': cluster, 'teamsIds': [team_of(f'Cluster: Hurricane Melissa {label}')]})
    code = a.call('GET', f'/CResponse/{melissa["id"]}')['code']
    for org, kind, sectors, focal, email in REGISTRATIONS:
        kobo.submit(uids['responder-registration'], {
            'response': code, 'org_type': kind, 'organisation': org, 'sectors': sectors, 'focal_name': focal,
            'focal_email': email, 'focal_phone': '+1 876 555 0' + str(100 + len(focal)), 'registration_key': f'{code}/{org}'})
    for org, *_ in REGISTRATIONS:
        wait_for(a, 'CResponder', 'registrationKey', f'{code}/{org}')
    print(f'{len(REGISTRATIONS)} organisations registered from Kobo')
    L, R = 'org_details', 'RESPONSES/FIGURES_COMMUNITY'
    focal = {org: (name, email) for org, _, _, name, email in REGISTRATIONS}
    focal['ORG_IFRC'] = ('Sofia Brown', 'sofia.brown@ifrc.example.org')  # reports without registering
    kinds = {org: kind for org, kind, *_ in REGISTRATIONS}
    reports = []
    for lead, kind, impl, sector, act, title, status, res, unit, start, end, places in REPORTS:
        rows = []
        for parish, community, where, qty, targeted, reached in places:
            women, children = reached * 52 // 100, reached * 30 // 100
            rows.append({f'{R}/parish': parish, f'{R}/community': community, f'{R}/location_type': where,
                         f'{R}/quantities/quantity_resource': str(qty), f'{R}/total_pop/total_population_targeted': str(targeted),
                         f'{R}/total_pop/total_population_reached': str(reached), f'{R}/people/category_of_people': 'idp',
                         f'{R}/people/idp/idp_people_targeted': str(targeted), f'{R}/people/idp/idp_people_reached': str(reached),
                         f'{R}/people/idp/idp_women_reached': str(women - children // 2),
                         f'{R}/people/idp/idp_men_reached': str(reached - women - children + children // 2),
                         f'{R}/people/idp/idp_children_reached': str(children),
                         f'{R}/people/idp/shelter_household_idp/idp_household_reached': str(reached // 4)})
        reports.append(kobo.submit(uids['activity-report'], {
            'today': start, 'response': code,
            f'{L}/ORAGANIZATION_LEAD/LeadOrganization_type': kind, f'{L}/ORAGANIZATION_LEAD/LeadOrganization_name': lead,
            f'{L}/ORAGANIZATION_LEAD/same_as_lead': 'no' if impl else 'yes',
            **({f'{L}/ORAGANIZATION_IMPLEMENTING/ImplementingOrganization_type': kinds[impl],
                f'{L}/ORAGANIZATION_IMPLEMENTING/ImplementingOrganization_name': impl} if impl else {}),
            f'{L}/FOCAL_POINTS': [{f'{L}/FOCAL_POINTS/name': focal[lead][0], f'{L}/FOCAL_POINTS/email': focal[lead][1],
                                   f'{L}/FOCAL_POINTS/job_title': 'Field coordinator'}],
            'RESPONSES/sector': sector, 'RESPONSES/activity_type': act,
            **({'RESPONSES/activity_type_other': 'VSAT connectivity'} if act == 'other' else {}),
            'RESPONSES/activity_title': title, 'RESPONSES/activity_Status': status, 'RESPONSES/resource_type': res,
            'RESPONSES/resource_unit_type': unit, 'RESPONSES/start_date': start,
            **({'RESPONSES/end_date': end} if end else {}), R: rows}))
    for rep in reports:
        wait_for(a, 'CActivity', 'cKoboSubmissionUuid', rep['_uuid'])
    print(f'{len(reports)} 5W activities from Kobo')


def main(only_5w=False):
    a = admin()
    if not only_5w:
        clean(a)
    kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
    forms = {k: json.loads((ROOT / 'kobo' / 'forms' / f'{k}.json').read_text())
             for k in ('support-request', 'volunteer-availability', 'site-registration', 'site-visit',
                       'responder-registration', 'activity-report')}
    uids = {k: kobo.deploy(f) for k, f in forms.items()}
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 200})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    if only_5w:
        fivew(a, kobo, uids, team, user)
        return

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

    fivew(a, kobo, uids, team, user)
    print('done: requests, volunteers, three responses with tasks, sites and visits, the Melissa 5W')


if __name__ == '__main__':
    try:
        main(only_5w=sys.argv[1:] == ['5w'])
    except BridgeError as e:
        sys.exit(f'demo data failed: {e}')
