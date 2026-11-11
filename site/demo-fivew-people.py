#!/usr/bin/env python3
"""
Demo data for the manual's 5W page (site/pages/fivew.html), on top of site/demo-data.py's
Hurricane Melissa response: its clusters' people (made up), a second organisation's water
trucking in a community UNICEF already serves (an overlap for the ICCG's 3W), and a portal
user for the Jamaica Red Cross's focal point (its password in secrets/seed.secrets).

    python3 -I site/demo-fivew-people.py

Idempotent: its own records (its cluster contacts by email, its activity by title, its
portal user) are removed and made again, nothing else is touched. Made through the admin
API, so the same formulas run (Accounts, Contacts, partners, overlaps).
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import admin, pw_key, secrets as read_secrets  # noqa: E402

MELISSA = 'Hurricane Melissa response, Jamaica'
PORTAL_USER = 'fivew-portal-jrc'
# (project's sector, role, name, organisation's code or a typed-in name, job title, email, phone)
PEOPLE = [
    ('WASH', 'coordinator', 'Keisha Morgan', 'ORG_UNICEF', 'WASH Cluster Coordinator', 'keisha.morgan@unicef.example.org', '+1 876 555 0141'),
    ('WASH', 'imo', 'Ravi Persaud', 'ORG_UNICEF', 'Information Management Officer', 'ravi.persaud@unicef.example.org', '+1 876 555 0142'),
    ('WASH', 'government_focal_point', 'Dwayne Brown', 'National Water Commission', 'Director, Emergency Water Supply',
     'dwayne.brown@nwc.example.org', '+1 876 555 0143'),
    ('SHELTER', 'coordinator', 'Amara Thompson', 'ORG_IFRC', 'Shelter Cluster Coordinator', 'amara.thompson@ifrc.example.org', '+1 876 555 0151'),
    ('SHELTER', 'co_coordinator', 'Hannah Clarke', 'ORG_ADRA', 'Shelter Programme Manager', 'hannah.clarke@adra.example.org', '+1 876 555 0152'),
    ('EMERGENCY_TELECOMS', 'coordinator', 'Tomás Rivera', 'ORG_WFP', 'ETC Coordinator', 'tomas.rivera@wfp.example.org', '+1 876 555 0161'),
]
OVERLAP = 'Water trucking to Black River (Mercy Corps)'


def where(attr, value, kind='equals', i=0):
    return {f'where[{i}][type]': kind, f'where[{i}][attribute]': attr, f'where[{i}][value]': value}


def rows(a, entity, select, **kw):
    return a.call('GET', f'/{entity}', {'maxSize': 200, 'select': select, **kw})['list']


def main():
    a = admin()
    resp = rows(a, 'CResponse', 'id,code', **where('name', MELISSA))
    if not resp:
        raise SystemExit(f'No "{MELISSA}": run site/demo-data.py first')
    resp = resp[0]
    projects = {p['cluster']: p for p in rows(a, 'CProject', 'id,cluster,name', **where('responseId', resp['id']))}
    org = lambda code: rows(a, 'COrganisation', 'id', **where('code', code))[0]['id']  # noqa: E731
    # Its own records from an earlier run
    for u in rows(a, 'User', 'id', **where('userName', PORTAL_USER)):
        a.call('DELETE', f'/User/{u["id"]}')
    for p in projects.values():
        for c in rows(a, 'CClusterContact', 'id,emailAddress', **where('projectId', p['id'])):
            if (c.get('emailAddress') or '').lower() in {x[5] for x in PEOPLE}:
                a.call('DELETE', f'/CClusterContact/{c["id"]}')
    for act in rows(a, 'CActivity', 'id', **where('title', OVERLAP)):
        for loc in rows(a, 'CActivityLocation', 'id', **where('activityId', act['id'])):
            a.call('DELETE', f'/CActivityLocation/{loc["id"]}')
        a.call('DELETE', f'/CActivity/{act["id"]}')

    for sector, role, name, who, title, email, phone in PEOPLE:
        listed = who.startswith('ORG_')
        a.call('POST', '/CClusterContact', body={
            'name': name, 'projectId': projects[sector]['id'], 'role': role, 'jobTitle': title, 'emailAddress': email, 'phone': phone,
            **({'organisationId': org(who)} if listed else {'organisationId': org('other'), 'organisationOther': who})})
    print(f'{len(PEOPLE)} cluster contacts')

    # Mercy Corps (registered for WASH) trucks water to Black River too, where UNICEF does
    black = next(x for x in rows(a, 'CActivityLocation', 'name,communityId,parishId', **where('responseId', resp['id']))
                 if (x.get('name') or '').startswith('Black River'))
    act = a.call('POST', '/CActivity', body={
        'name': 'Water trucking', 'title': OVERLAP, 'responseId': resp['id'], 'leadOrganisationId': org('ORG_MERCYCORPS'),
        'sector': 'WASH', 'activityType': 'water_trucking', 'status': 'IN_PROGRESS', 'startDate': '2026-11-03',
        'reportDate': '2026-11-06', 'resourceType': 'wash', 'resourceUnit': 'litres'})
    a.call('POST', '/CActivityLocation', body={'name': 'x', 'activityId': act['id'], 'communityId': black['communityId'],
                                                'parishId': black['parishId'], 'locationType': 'general_community',
                                                'quantity': 40000, 'populationTargeted': 4000, 'populationReached': 1800})
    print('an overlap: Mercy Corps\'s water trucking in Black River')

    # A portal user for the Jamaica Red Cross's focal point, to show the organisation portal
    contact = rows(a, 'Contact', 'id,accountId', **where('emailAddress', 'andrea.campbell@jrc.example.org'))[0]
    portal = rows(a, 'Portal', 'id', **where('name', 'Organisation portal'))[0]['id']
    role = rows(a, 'PortalRole', 'id', **where('name', 'Organisation portal'))[0]['id']
    path = ROOT / 'secrets' / 'seed.secrets'
    have = read_secrets('seed')
    password = have.get(pw_key(PORTAL_USER)) or secrets.token_urlsafe(14)
    a.call('POST', '/User', body={'userName': PORTAL_USER, 'type': 'portal', 'password': password, 'contactId': contact['id'],
                                  'firstName': 'Andrea', 'lastName': 'Campbell', 'portalsIds': [portal], 'portalRolesIds': [role],
                                  'isActive': True, 'emailAddress': f'delivered+{PORTAL_USER}@resend.dev',
                                  'accountsIds': [contact['accountId']]})  # what the portal's "account" level checks
    have[pw_key(PORTAL_USER)] = password
    path.write_text(''.join(f'{k}={v}\n' for k, v in have.items()))
    path.chmod(0o600)
    print(f'portal user {PORTAL_USER} (JRC\'s Andrea Campbell), password in {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
