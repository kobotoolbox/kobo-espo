#!/usr/bin/env python3
"""
Demo data for the manual's CSO mapping page (site/pages/cso.html): five made-up Kenyan
civil society organisations, with their places, contacts and updates, and a portal user
for one of them (its password in secrets/seed.secrets). Everything is made up.

    python3 -I site/demo-cso.py

Idempotent: its own CSOs (by name) and what hangs off them are removed and made again,
nothing else is touched. Made through the admin API, as the forms' records would be (the
same formulas run: codes, keys, teams, Accounts, P-codes, the shared contact, superseded
updates, data checks).
"""
import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import admin, pw_key, secrets as read_secrets  # noqa: E402

AREAS = {a['name']: a for a in json.loads((ROOT / 'workflows' / 'core' / 'data' / 'admin-areas-ken.json').read_text())
         if a['level'] in ('admin1', 'admin2')}
PORTAL_USER = 'cso-portal-amani'

# name, acronym, type, sharing, places (sub-counties, or a county), roles, offers, seeks, settings, populations, contacts
CSOS = [
    ('Amani Community Health Network', 'ACHN', 'national_ngo', 'yes', ['Kamukunji', 'Embakasi East', 'Changamwe'],
     ['risk_communication', 'community_surveillance', 'wash'], ['community_access', 'local_knowledge', 'staff'],
     ['funding', 'training'], ['informal_settlements'], ['women_girls', 'children', 'informal_settlements'],
     [('Wanjiru', 'Kamau', 'Programme Coordinator', 'wanjiru.kamau'), ('Otieno', 'Ouma', 'Field Officer', 'otieno.ouma')]),
    ("Tana River Women's Development Group", 'TRWDG', 'women_led', 'profile_only', ['Galole', 'Bura'],
     ['community_engagement', 'protection', 'mhpss'], ['community_access', 'local_knowledge'], ['supplies', 'logistics'],
     ['rural', 'remote'], ['women_girls', 'displaced'], [('Halima', 'Abdi', 'Chairperson', 'halima.abdi')]),
    ('Pwani Youth for Health', 'PYH', 'youth_led', 'yes', ['Mvita', 'Kilifi North', 'Msambweni'],
     ['risk_communication', 'vaccination', 'workforce'], ['staff', 'communications'], ['training', 'data'],
     ['informal_settlements', 'rural'], ['children', 'health_workers'], [('Baraka', 'Mwangi', 'Director', 'baraka.mwangi')]),
    ('Kenya Faith Coalition for Health', 'KFCH', 'faith_based', 'no', ['Westlands', 'Kisumu Central', 'Dujis'],
     ['community_engagement', 'advocacy', 'coordination'], ['advocacy', 'convening'], ['data'],
     ['humanitarian'], ['minorities', 'poverty'], [('Grace', 'Njeri', 'Secretary General', 'grace.njeri')]),
    ('Turkana Pastoralist Health Link', 'TPHL', 'community_based', 'yes', ['Turkana Central', 'Loima'],
     ['community_health', 'community_surveillance', 'logistics'], ['local_knowledge', 'referral'], ['logistics', 'funding'],
     ['remote', 'nomadic', 'border'], ['rural_remote', 'children'], [('Ekal', 'Lokol', 'Coordinator', 'ekal.lokol')]),
]


def where(attr, value, kind='equals'):
    return {'where[0][type]': kind, 'where[0][attribute]': attr, 'where[0][value]': value}


def one(a, entity, attr, value):
    rows = a.call('GET', f'/{entity}', {'maxSize': 2, 'select': 'id', **where(attr, value)})['list']
    return rows[0]['id'] if rows else None


def area(a, name):
    if name not in AREAS:
        raise SystemExit(f'{name}: not a Kenyan sub-county or county in the admin areas')
    return one(a, 'CAdminArea', 'pcode', AREAS[name]['pcode'])


def remove(a):
    user = one(a, 'User', 'userName', PORTAL_USER)
    if user:
        a.call('DELETE', f'/User/{user}')
    for name, *_ in CSOS:
        for cso in a.call('GET', '/CCso', {'maxSize': 5, 'select': 'id,accountId', **where('name', name)})['list']:
            for entity, attr in (('CPresence', 'csoId'), ('CCsoUpdate', 'csoId'), ('Contact', 'cCsoId')):
                for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id', **where(attr, cso['id'])})['list']:
                    a.call('DELETE', f'/{entity}/{r["id"]}')
            a.call('DELETE', f'/CCso/{cso["id"]}')
            if cso.get('accountId'):
                a.call('DELETE', f'/Account/{cso["accountId"]}')


def main():
    a = admin()
    remove(a)
    made = {}
    for name, acr, kind, sharing, places, roles, offers, seeks, settings, pops, contacts in CSOS:
        cso = a.call('POST', '/CCso', body={
            'name': name, 'acronym': acr, 'csoType': kind, 'countryRegistered': 'KEN', 'sharing': sharing,
            'levels': ['community', 'district', 'national'], 'roles': roles, 'offers': offers, 'seeks': seeks,
            'settings': settings, 'populations': pops, 'stages': ['preparedness', 'response'],
            'hazards': ['cholera', 'hydromet'], 'mechanisms': ['health_cluster', 'rcce'], 'connectVia': ['email', 'phone']})
        cso = a.call('GET', f'/CCso/{cso["id"]}')
        for first, last, title, email in contacts:
            a.call('POST', '/Contact', body={'firstName': first, 'lastName': last, 'title': title, 'cCsoId': cso['id'],
                                             'emailAddress': f'{email}@example.org', 'phoneNumber': '+254 712 000000'},
                   headers={'X-Skip-Duplicate-Check': 'true'})
        for place in places:
            a.call('POST', '/CPresence', body={'name': place, 'csoId': cso['id'], 'adminAreaId': area(a, place)})
        made[acr] = a.call('GET', f'/CCso/{cso["id"]}')
        print(f'{acr}: {made[acr]["code"]}, {len(places)} places, {len(contacts)} contacts, teams {list(made[acr]["teamsNames"].values())}')

    def update(acr, place, status, roles, needs, note='', key=True, wait=0.0):
        time.sleep(wait)
        return a.call('POST', '/CCsoUpdate', body={
            'name': 'x', 'csoId': made[acr]['id'], 'adminAreaId': area(a, place), 'status': status, 'roles': roles,
            'needs': needs, 'needsNote': note, 'populations': ['women_girls', 'children'], 'locality': '',
            **({'keyGiven': made[acr]['updateKey']} if key else {})})
    update('ACHN', 'Kamukunji', 'ready', ['risk_communication', 'wash'], ['supplies'], 'Chlorine and soap for 40 households')
    update('ACHN', 'Kamukunji', 'active', ['risk_communication', 'wash'], ['supplies', 'logistics'],
           'Cholera cases in Gikomba: chlorine, soap, a vehicle', wait=1.1)
    update('ACHN', 'Embakasi East', 'active', ['community_surveillance'], [])
    update('PYH', 'Mvita', 'active', ['risk_communication', 'vaccination'], ['training'], 'Volunteers for OCV mobilisation')
    update('PYH', 'Kilifi North', 'planned', ['vaccination'], ['logistics'])
    update('TPHL', 'Turkana Central', 'active', ['community_health', 'logistics'], ['logistics', 'funding'],
           'Fuel for outreach to Lodwar settlements')
    update('TPHL', 'Loima', 'suspended', ['community_surveillance'], ['funding'], 'Insecurity on the road to Lorugum')
    update('TRWDG', 'Galole', 'active', ['protection', 'mhpss'], ['supplies'], 'Dignity kits after the floods')
    update('TRWDG', 'Mvita', 'active', ['mhpss'], [], key=False)  # no key, and not one of its places: flagged
    # A portal user for Amani's first contact, to show the portal
    contact = a.call('GET', '/Contact', {'maxSize': 1, 'select': 'id,accountId', **where('emailAddress', 'wanjiru.kamau@example.org')})['list'][0]
    portal = one(a, 'Portal', 'name', 'CSO portal')
    role = one(a, 'PortalRole', 'name', 'CSO portal')
    path = ROOT / 'secrets' / 'seed.secrets'
    have = read_secrets('seed')
    password = have.get(pw_key(PORTAL_USER)) or secrets.token_urlsafe(14)
    a.call('POST', '/User', body={'userName': PORTAL_USER, 'type': 'portal', 'password': password, 'contactId': contact['id'],
                                  'firstName': 'Wanjiru', 'lastName': 'Kamau', 'portalsIds': [portal], 'portalRolesIds': [role],
                                  'isActive': True, 'emailAddress': f'delivered+{PORTAL_USER}@resend.dev',
                                  'accountsIds': [contact['accountId']]})  # what the portal's "account" level checks
    have[pw_key(PORTAL_USER)] = password
    path.write_text(''.join(f'{k}={v}\n' for k, v in have.items()))
    path.chmod(0o600)
    print(f'portal user {PORTAL_USER} (Amani\'s Wanjiru Kamau), password in {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
