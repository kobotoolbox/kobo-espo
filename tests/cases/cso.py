#!/usr/bin/env python3
"""
C1-C10: Workflow F, the CSO mapping (plans/cso-mapping-plan.md): the CSO forms through the
bridge (kobo/templates/cso-*.toml, generated with the forms by kobo/forms/cso.py) into
CCso (and its Account), CPresence, Contact and CCsoUpdate, and their formulas: codes and
keys, teams by country, consent, a profile sent again, superseded updates, P-codes, data
checks. Access as the CSO coordinators of Kenya and Uganda (cso-kenya, cso-uganda) with
their own passwords, and as a CSO's contact in the CSO portal (C10, a portal user made
for the run).

    python3 -I tests/cases/cso.py [--kobo fake|real]

A fake Kobo by default (kobo-espo-bridge/fake_kobo.py); with --kobo real, the forms on the
test account (tests/staging.py deploys them). Its CSOs are named "CSOT <run> ...", removed
first and at the end. Writes tests/results/cso.json (cso-real.json with --kobo real).
"""
import argparse
import csv
import io
import json
import re
import secrets
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, BridgeError, Espo, admin, as_user, env  # noqa: E402

from bridges import Bridge, by, ensure_secrets  # noqa: E402

sys.path.insert(0, str(ROOT / 'agents'))
import tools  # noqa: E402  (the geocode tool; its token from secrets/agents.secrets)

KINDS = ('cso-profile-ken', 'cso-update-ken', 'cso-profile', 'cso-update')
FORMS = {k: json.loads((ROOT / 'kobo' / 'forms' / f'{k}.json').read_text()) for k in KINDS}
RUN = str(int(time.time()))[-6:]
PREFIX = 'CSOT'
CODE = re.compile(r'^CSO-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{4}$')
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=sorted))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def status(fn):
    try:
        fn()
        return 200
    except BridgeError as e:
        return e.status


def where(attr, value, kind='equals'):
    return {'where[0][type]': kind, 'where[0][attribute]': attr, 'where[0][value]': value}


def cleanup(a):
    for u in a.call('GET', '/User', {'maxSize': 50, 'select': 'id', **where('userName', 'csot-', 'startsWith')})['list']:
        a.call('DELETE', f'/User/{u["id"]}')
    for cso in a.call('GET', '/CCso', {'maxSize': 200, 'select': 'id,accountId', **where('name', PREFIX, 'startsWith')})['list']:
        for entity, attr in (('CPresence', 'csoId'), ('CCsoUpdate', 'csoId'), ('Contact', 'cCsoId')):
            for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id', **where(attr, cso['id'])})['list']:
                a.call('DELETE', f'/{entity}/{r["id"]}')
        if cso.get('accountId'):
            for m in a.call('GET', '/Email', {'maxSize': 50, 'select': 'id', **where('parentId', cso['accountId'])})['list']:
                a.call('DELETE', f'/Email/{m["id"]}')  # its welcome emails (C11), sent or not
        a.call('DELETE', f'/CCso/{cso["id"]}')
        if cso.get('accountId'):
            a.call('DELETE', f'/Account/{cso["accountId"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kobo', choices=['fake', 'real'], default='fake')
    args = ap.parse_args()
    a = admin()
    ensure_secrets()
    cleanup(a)
    if args.kobo == 'fake':
        from fake_kobo import FakeKobo
        kobo = FakeKobo(token='fake-' + RUN).start()
        uids = {k: kobo.add_form(f['settings']['form_title'], f) for k, f in FORMS.items()}
    else:
        from staging import RealKobo
        kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
        uids = kobo.deploy_all(FORMS)
    bridges = {k: Bridge(k, kobo.url, kobo.token) for k in KINDS}
    for b in bridges.values():
        b.setup()
    print(f'setup done for {len(bridges)} templates; Kobo {args.kobo} at {kobo.url}')
    try:
        run(a, kobo, uids, bridges)
    finally:
        cleanup(a)
    path = ROOT / 'tests' / 'results' / ('cso.json' if args.kobo == 'fake' else 'cso-real.json')
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'cso: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def profile(name, presence, focal=(('Amina Focal', 'Coordinator'),), sharing='yes', cso=None, key=None, generic=False, **kw):
    """A profile submission's answers, as Kobo names them (group paths)."""
    W, F = 'where/PRESENCE', 'FOCAL_POINTS'
    rows = []
    for p in presence:
        if generic:
            rows.append({f'{W}/country': p[0], f'{W}/location': p[1]})
        else:
            admin1, admin2 = p
            rows.append({f'{W}/admin1': admin1, **({f'{W}/admin2': admin2} if admin2 else {}),
                         f'{W}/area': admin2 or admin1, f'{W}/country': 'KEN'})
    return {**({'cso': cso} if cso else {}), **({'key': key} if key else {}),
            'about/cso_name': f'{PREFIX} {RUN} {name}', 'about/acronym': name[:4].upper(),
            'about/cso_type': kw.pop('cso_type', 'national_ngo'), 'about/country_registered': kw.pop('registered', 'KEN'),
            'about/levels': 'national district',
            F: [{f'{F}/name': n, f'{F}/position': pos, f'{F}/email': f'{n.split()[0].lower()}-{RUN}@example.org',
                 f'{F}/phone': '+254 712 000000'} for n, pos in focal],
            'sharing': sharing, 'where/PRESENCE': rows,
            'where/settings': 'informal_settlements rural', 'where/populations': 'women_girls children',
            'does/stages': 'preparedness response', 'does/roles': kw.pop('roles', 'risk_communication wash'),
            'does/hazards': 'cholera hydromet', 'coordination/mechanisms': 'health_cluster',
            'coordination/offers': kw.pop('offers', 'training logistics'), 'coordination/seeks': kw.pop('seeks', 'funding'),
            'coordination/connect_via': 'email phone', **kw}


def update(code, key, area=None, admin1=None, roles='risk_communication', state='active', generic=None, **kw):
    P = 'place'
    where_ = ({f'{P}/country': generic[0], f'{P}/location': generic[1]} if generic
              else {f'{P}/admin1': admin1 or area[:5], f'{P}/admin2': area, f'{P}/area': area, f'{P}/country': 'KEN'})
    return {'cso': code, **({'key': key} if key else {}), 'cso_code': code, **where_, f'{P}/locality': 'Gikomba',
            'roles': roles, 'status': state, 'populations': 'women_girls', 'needs': kw.pop('needs', 'supplies'), **kw}


def run(a, kobo, uids, bridges):
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 100})['list']}
    ken, uga, none = team['CSO: Kenya'], team['CSO: Uganda'], team['CSO: Unassigned']
    uga_areas = json.loads((ROOT / 'workflows' / 'core' / 'data' / 'admin-areas-uga.json').read_text())
    uga2 = next(x for x in uga_areas if x['level'] == 'admin2')

    def one(entity, attr, value):
        rows = by(a, entity, attr, value)
        return a.call('GET', f'/{entity}/{rows[0]["id"]}') if len(rows) == 1 else {'count': len(rows)}

    def rows(entity, cso, **filters):
        attr = 'cCsoId' if entity == 'Contact' else 'csoId'
        return [a.call('GET', f'/{entity}/{r["id"]}') for r in by(a, entity, attr, cso['id'])
                if all(a.call('GET', f'/{entity}/{r["id"]}').get(k) == v for k, v in filters.items())]

    # --- C1: a Kenyan CSO's profile, from the Kenya form ------------------------------------------
    s1 = kobo.submit(uids['cso-profile-ken'], profile('Amani', [('KE047', 'KE047288'), ('KE001', None)],
                                                      focal=(('Amina Focal', 'Coordinator'), ('Baraka Second', 'Director'))))
    code, log, st = bridges['cso-profile-ken'].once()
    amani = one('CCso', 'cKoboSubmissionUuid', s1['_uuid'])
    check('C1', 'a profile makes one CSO, with its CSO- code and a 16-character key, the key given not kept',
          bool(amani.get('code') and CODE.match(amani['code'])) and len(amani.get('updateKey') or '') == 16
          and not amani.get('keyGiven'), {k: amani.get(k) for k in ('code', 'keyGiven', 'count')} or log[-600:])
    check('C1', 'its answers: name, type, registered in Kenya, lists as codes, profile date today',
          amani.get('name') == f'{PREFIX} {RUN} Amani' and amani.get('csoType') == 'national_ngo'
          and amani.get('countryRegistered') == 'KEN' and amani.get('roles') == ['risk_communication', 'wash']
          and amani.get('offers') == ['training', 'logistics'] and amani.get('lastProfile') == date.today().isoformat(),
          {k: amani.get(k) for k in ('name', 'csoType', 'countryRegistered', 'roles', 'offers', 'lastProfile')})
    check('C1', 'in CSO: Kenya only (its country), listed', amani.get('teamsIds') == [ken] and amani.get('listed') is True
          and amani.get('countries') == ['KEN'], {k: amani.get(k) for k in ('teamsNames', 'listed', 'countries')})
    places = rows('CPresence', amani)
    by_area = {p.get('adminAreaName'): p for p in places}
    kam = by_area.get('Kamukunji', {})
    check('C1', 'two places, each linked to its admin area (the deepest P-code given)',
          len(places) == 2 and set(by_area) == {'Kamukunji', 'Mombasa'}, sorted(by_area))
    check('C1', 'a place has its P-codes up its parents, its country, its name, and is current',
          kam.get('pcode1') == 'KE047' and kam.get('pcode2') == 'KE047288' and kam.get('country') == 'KEN'
          and kam.get('name') == 'Kamukunji, Nairobi' and kam.get('current') is True and kam.get('pcodeStatus') == 'given',
          {k: kam.get(k) for k in ('pcode1', 'pcode2', 'country', 'name', 'current', 'pcodeStatus')})
    check('C1', "a place has the CSO's teams and what the feeds read of it (name, type, settings, roles, listed)",
          kam.get('teamsIds') == [ken] and kam.get('csoName') == amani.get('name') and kam.get('csoType') == 'national_ngo'
          and kam.get('settings') == ['informal_settlements', 'rural'] and kam.get('roles') == ['risk_communication', 'wash']
          and kam.get('listed') is True, {k: kam.get(k) for k in ('teamsNames', 'csoName', 'csoType', 'settings', 'listed')})
    amani = a.call('GET', f'/CCso/{amani["id"]}')
    account = a.call('GET', f'/Account/{amani["accountId"]}') if amani.get('accountId') else {}
    check('C1', 'its Account: made with it, named after it, in its team', account.get('name') == amani['name']
          and account.get('teamsIds') == [ken], {k: account.get(k) for k in ('name', 'teamsNames')})
    check('C1', 'its places on its Account too', all(p.get('accountId') == amani['accountId'] for p in places),
          [p.get('accountId') for p in places])
    fps = rows('Contact', amani)
    check('C1', "two contacts (its focal points): its Account's, in its team, position as title, names split",
          len(fps) == 2 and all(f.get('accountId') == amani['accountId'] and f.get('teamsIds') == [ken] for f in fps)
          and {f.get('title') for f in fps} == {'Coordinator', 'Director'}
          and {(f.get('firstName'), f.get('lastName')) for f in fps} == {('Amina', 'Focal'), ('Baraka', 'Second')},
          [(f.get('name'), f.get('accountName'), f.get('teamsNames')) for f in fps])
    shared = amani.get('sharedContact') or ''
    check('C1', 'it said yes to sharing: both focal points in its shared contact',
          'Amina Focal (Coordinator)' in shared and f'baraka-{RUN}@example.org' in shared, shared)

    # --- C2: consent shapes what the directory reads ----------------------------------------------
    a.call('PUT', f'/CCso/{amani["id"]}', body={'sharing': 'profile_only'})
    got = a.call('GET', f'/CCso/{amani["id"]}')
    check('C2', 'profile only: still listed, no shared contact', got.get('listed') is True and not got.get('sharedContact'),
          {k: got.get(k) for k in ('listed', 'sharedContact')})
    a.call('PUT', f'/CCso/{amani["id"]}', body={'sharing': 'no'})
    got = a.call('GET', f'/CCso/{amani["id"]}')
    place = a.call('GET', f'/CPresence/{kam["id"]}')
    check('C2', 'no: not listed, and its places say so (what the feeds filter on)',
          got.get('listed') is False and place.get('listed') is False, (got.get('listed'), place.get('listed')))
    a.call('PUT', f'/CCso/{amani["id"]}', body={'sharing': 'yes'})
    got = a.call('GET', f'/CCso/{amani["id"]}')
    check('C2', 'yes again: listed, its contacts shared again', got.get('listed') is True
          and 'Amina Focal' in (got.get('sharedContact') or ''), {k: got.get(k) for k in ('listed', 'sharedContact')})
    check('C2', "its key can't be set through the API (read-only)",
          (a.call('PUT', f'/CCso/{amani["id"]}', body={'updateKey': 'x' * 16}) or True)
          and a.call('GET', f'/CCso/{amani["id"]}')['updateKey'] == amani['updateKey'])

    # --- C3: the profile sent again from its link (code and key) ----------------------------------
    s2 = kobo.submit(uids['cso-profile-ken'], profile('Amani', [('KE047', 'KE047289')], focal=(('Chege New', 'Officer'),),
                                                      cso=amani['code'], key=amani['updateKey'], roles='risk_communication mhpss'))
    code, log, st = bridges['cso-profile-ken'].once()
    same = by(a, 'CCso', 'code', amani['code'])
    got = a.call('GET', f'/CCso/{amani["id"]}')
    check('C3', 'sent again with its code and key: the same CSO, updated', len(same) == 1
          and got.get('roles') == ['risk_communication', 'mhpss'] and got.get('cKoboSubmissionUuid') == s2['_uuid'],
          (len(same), got.get('roles')) if len(same) == 1 else log[-600:])
    current = rows('CPresence', amani, current=True)
    check('C3', "its places now the new submission's: the old ones no longer current",
          [p.get('adminAreaName') for p in current] == [a.call('GET', '/CAdminArea', {'maxSize': 1, **where('pcode', 'KE047289')})['list'][0]['name']]
          and len(rows('CPresence', amani)) == 3, [(p.get('name'), p.get('current')) for p in rows('CPresence', amani)])
    check('C3', 'the new place has the new roles (copied when made)', current and current[0].get('roles') == ['risk_communication', 'mhpss'],
          current and current[0].get('roles'))
    old = a.call('GET', f'/CPresence/{kam["id"]}')
    check('C3', "an old place got the CSO's new roles too (the CSO's formula keeps its places' copies)",
          old.get('roles') == ['risk_communication', 'mhpss'], old.get('roles'))
    fps = rows('Contact', amani)
    got = a.call('GET', f'/CCso/{amani["id"]}')
    check('C3', 'a new focal point is a new contact; the others stay (the portal is where they are removed)',
          sorted(f.get('name') for f in fps) == ['Amina Focal', 'Baraka Second', 'Chege New']
          and 'Chege New' in (got.get('sharedContact') or '') and 'Amina' in (got.get('sharedContact') or ''),
          ([f.get('name') for f in fps], got.get('sharedContact')))
    s2b = kobo.submit(uids['cso-profile-ken'], profile('Amani', [('KE047', 'KE047289')], focal=(('Chege Newer', 'Lead'),),
                                                       cso=amani['code'], key=amani['updateKey'], roles='risk_communication mhpss',
                                                       **{'FOCAL_POINTS': [{'FOCAL_POINTS/name': 'Chege Newer', 'FOCAL_POINTS/position': 'Lead',
                                                                            'FOCAL_POINTS/email': f'chege-{RUN}@example.org'}]}))
    bridges['cso-profile-ken'].once()
    fps = rows('Contact', amani)
    check('C3', 'the same person again (their email): the same contact, updated, not a second one',
          sorted(f.get('name') for f in fps) == ['Amina Focal', 'Baraka Second', 'Chege Newer']
          and next(f for f in fps if f.get('firstName') == 'Chege').get('title') == 'Lead', [(f.get('name'), f.get('title')) for f in fps])
    s3 = kobo.submit(uids['cso-profile-ken'], profile('Amani hijacked', [('KE001', None)], cso=amani['code']))
    code, log, st = bridges['cso-profile-ken'].once()
    got = a.call('GET', f'/CCso/{amani["id"]}')
    failed = bridges['cso-profile-ken'].failed()
    check('C3', 'sent with the code but no key: refused, recorded with its reason, the CSO unchanged',
          got.get('name') == f'{PREFIX} {RUN} Amani' and got.get('cKoboSubmissionUuid') == s2b['_uuid']
          and f'submission {s3["_id"]}' in failed and "key" in failed, failed[-400:])

    # --- C4: teams by country ---------------------------------------------------------------------
    s4 = kobo.submit(uids['cso-profile'], profile('Mto', [('UGA', f'{0.3476} {32.5825} 1200 5')], registered='UGA', generic=True))
    s5 = kobo.submit(uids['cso-profile-ken'], profile('Pamoja', [('KE047', 'KE047288')],
                                                      **{'where/other_countries': 'UGA'}))
    s6 = kobo.submit(uids['cso-profile'], profile('Lointain', [('FRA', '48.85 2.35 0 5')], registered='FRA', generic=True))
    bridges['cso-profile'].once()
    bridges['cso-profile-ken'].once()
    mto, pamoja, far = (one('CCso', 'cKoboSubmissionUuid', s['_uuid']) for s in (s4, s5, s6))
    check('C4', 'a Ugandan CSO (the generic form): in CSO: Uganda', mto.get('teamsIds') == [uga], mto.get('teamsNames'))
    check('C4', 'a Kenyan CSO also working in Uganda: in both countries\' teams',
          set(pamoja.get('teamsIds') or []) == {ken, uga} and set(pamoja.get('countries') or []) == {'KEN', 'UGA'},
          {k: pamoja.get(k) for k in ('teamsNames', 'countries')})
    check('C4', 'a CSO in a country with no team: CSO: Unassigned', far.get('teamsIds') == [none], far.get('teamsNames'))
    pin = (rows('CPresence', mto) or [{}])[0]
    check('C4', "the generic form's pin: latitude and longitude, P-coding pending, no area yet",
          pin.get('latitude') == 0.3476 and pin.get('longitude') == 32.5825 and pin.get('pcodeStatus') == 'pending'
          and not pin.get('adminAreaId') and pin.get('country') == 'UGA',
          {k: pin.get(k) for k in ('latitude', 'longitude', 'pcodeStatus', 'adminAreaId', 'country')})

    # --- C5: the P-coding step: the geocode tool (the real geocoder) on the pin, its values written
    values, line = tools.geocode(pin)
    kampala = next((x for x in uga_areas if x['pcode'] == values.get('pcode2')), {})
    check('C5', 'the geocoder finds the pin\'s areas (Kampala), deeper than EspoCRM has (admin3)',
          values.get('pcodeStatus') == 'done' and kampala.get('level') == 'admin2' and values.get('pcode3'), line)
    a.call('PUT', f'/CPresence/{pin["id"]}', body=values)
    got = a.call('GET', f'/CPresence/{pin["id"]}')
    check('C5', "P-coded: linked to the deepest area EspoCRM has (the district), named after it",
          got.get('adminAreaName') == kampala.get('name') and got.get('pcodeStatus') == 'done'
          and got.get('name', '').startswith(kampala.get('name') or '-'),
          {k: got.get(k) for k in ('adminAreaName', 'pcodeStatus', 'name')})
    far_pin = (rows('CPresence', far) or [{}])[0]
    values, line = tools.geocode(far_pin)
    check('C5', 'a pin where the geocoder has no boundaries (Paris): outside', values == {'pcodeStatus': 'outside'}, line)

    # --- C6: who sees what ------------------------------------------------------------------------
    k_user, u_user = as_user('cso-kenya'), as_user('cso-uganda')

    def seen(u, entity='CCso'):
        try:
            return {r['name'] for r in u.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name',
                                                                   **where('name', f'{PREFIX} {RUN}', 'startsWith')})['list']}
        except BridgeError as e:
            return e.status
    n = lambda *xs: {f'{PREFIX} {RUN} {x}' for x in xs}  # noqa: E731
    check('C6', "cso-kenya: Kenya's CSOs (Amani, Pamoja), not Uganda's or the unassigned", seen(k_user) == n('Amani', 'Pamoja'),
          seen(k_user))
    check('C6', "cso-uganda: Uganda's (Mto, Pamoja), not Kenya's", seen(u_user) == n('Mto', 'Pamoja'), seen(u_user))
    k_fps = {r['name'] for r in k_user.call('GET', '/Contact', {'maxSize': 50, 'select': 'name', **where('cCsoId', amani['id'])})['list']}
    check('C6', "cso-kenya: reads a Kenyan CSO's contacts; cso-uganda doesn't",
          'Chege Newer' in k_fps and not u_user.call('GET', '/Contact', {'maxSize': 50, **where('cCsoId', amani['id'])})['list'],
          k_fps)
    check('C6', "cso-uganda: opening a Kenyan CSO refused", status(lambda: u_user.call('GET', f'/CCso/{amani["id"]}')) == 403)
    viewer = as_user('cluster-viewer')
    check('C6', 'a 5W cluster viewer: no CSOs at all', status(lambda: viewer.call('GET', '/CCso', {'maxSize': 1})) == 403)

    # --- C7: updates: the CSO's key, superseded, data checks --------------------------------------
    key = amani['updateKey']
    u1 = kobo.submit(uids['cso-update-ken'], update(amani['code'], key, area='KE047289'))
    bridges['cso-update-ken'].once()
    first = one('CCsoUpdate', 'cKoboSubmissionUuid', u1['_uuid'])
    check('C7', "an update with the CSO's code and key: its CSO, key ok, counted, in its team, the key not kept",
          first.get('csoId') == amani['id'] and first.get('keyCheck') == 'ok' and first.get('current') is True
          and first.get('teamsIds') == [ken] and not first.get('keyGiven'),
          {k: first.get(k) for k in ('csoName', 'keyCheck', 'current', 'teamsNames', 'keyGiven', 'count')})
    check('C7', 'its place: area, P-codes, status, and no data checks (a place and roles in the profile)',
          first.get('pcode2') == 'KE047289' and first.get('pcode1') == 'KE047' and first.get('status') == 'active'
          and first.get('dataChecks') == [], {k: first.get(k) for k in ('pcode1', 'pcode2', 'status', 'dataChecks')})
    time.sleep(1.1)  # createdAt is to the second
    u2 = kobo.submit(uids['cso-update-ken'], update(amani['code'], key, area='KE047289', roles='mhpss', state='suspended'))
    bridges['cso-update-ken'].once()
    second = one('CCsoUpdate', 'cKoboSubmissionUuid', u2['_uuid'])
    first = a.call('GET', f'/CCsoUpdate/{first["id"]}')
    check('C7', 'a newer update in the same place: it counts, the older is superseded',
          second.get('current') is True and first.get('superseded') is True and first.get('current') is False,
          (second.get('current'), first.get('superseded'), first.get('current')))
    u3 = kobo.submit(uids['cso-update-ken'], update(amani['code'], None, area='KE047289', state='completed'))
    u4 = kobo.submit(uids['cso-update-ken'], update(amani['code'], 'not-the-key', area='KE047289'))
    bridges['cso-update-ken'].once()
    nokey, wrong = (one('CCsoUpdate', 'cKoboSubmissionUuid', s['_uuid']) for s in (u3, u4))
    second = a.call('GET', f'/CCsoUpdate/{second["id"]}')
    check('C7', 'without the key: kept, flagged, not counted; with a wrong one too; neither supersedes',
          nokey.get('keyCheck') == 'missing' and 'key_missing' in (nokey.get('dataChecks') or []) and nokey.get('current') is False
          and wrong.get('keyCheck') == 'wrong' and 'key_wrong' in (wrong.get('dataChecks') or []) and wrong.get('current') is False
          and second.get('current') is True,
          {'nokey': nokey.get('keyCheck'), 'wrong': wrong.get('keyCheck'), 'second': second.get('current')})
    k_user.call('PUT', f'/CCsoUpdate/{nokey["id"]}', body={'keyCheck': 'confirmed'})
    nokey, second = (a.call('GET', f'/CCsoUpdate/{r["id"]}') for r in (nokey, second))
    check('C7', 'cso-kenya confirms the one without a key: it counts, and supersedes the older',
          nokey.get('current') is True and second.get('superseded') is True, (nokey.get('current'), second.get('superseded')))
    u5 = kobo.submit(uids['cso-update-ken'], update(amani['code'], key, area='KE001001', admin1='KE001', roles='logistics'))
    bridges['cso-update-ken'].once()
    odd = one('CCsoUpdate', 'cKoboSubmissionUuid', u5['_uuid'])
    check('C7', "a county not in the CSO's places, a role not in its profile: flagged",
          set(odd.get('dataChecks') or []) == {'not_in_presence', 'role_not_in_profile'}, odd.get('dataChecks') or odd)

    # --- C8: an update from the generic form: a pin, P-coded afterwards ---------------------------
    mto_key = a.call('GET', f'/CCso/{mto["id"]}')['updateKey']
    u6 = kobo.submit(uids['cso-update'], update(mto['code'], mto_key, generic=('UGA', '0.35 32.58 0 5')))
    bridges['cso-update'].once()
    gen = one('CCsoUpdate', 'cKoboSubmissionUuid', u6['_uuid'])
    check('C8', 'a pin to P-code, counted, in CSO: Uganda', gen.get('pcodeStatus') == 'pending' and gen.get('current') is True
          and gen.get('teamsIds') == [uga] and gen.get('latitude') == 0.35,
          {k: gen.get(k) for k in ('pcodeStatus', 'current', 'teamsNames', 'latitude', 'count')})
    a.call('PUT', f'/CCsoUpdate/{gen["id"]}', body={'pcode1': uga2['parentPcode'], 'pcode2': uga2['pcode'], 'pcodeStatus': 'done'})
    got = a.call('GET', f'/CCsoUpdate/{gen["id"]}')
    check('C8', 'P-coded: its area, and named after the CSO and the place', got.get('adminAreaName') == uga2['name']
          and got.get('name') == f'{PREFIX} {RUN} Mto: {uga2["name"]}', {k: got.get(k) for k in ('adminAreaName', 'name')})

    # --- C9: the Kenya forms' list of admin areas -------------------------------------------------
    if hasattr(kobo, 'media_of') or hasattr(kobo, 'media'):
        media = kobo.media_of(uids['cso-update-ken']) if hasattr(kobo, 'media_of') else kobo.media[uids['cso-update-ken']]
        areas = list(csv.DictReader(io.StringIO(media.get('areas.csv', b'').decode())))
        levels = {r['level'] for r in areas}
        check('C9', "areas.csv on the Kenya forms: Kenya's country, 47 counties and 290 sub-counties, nothing else",
              len(areas) == 338 and all(r['name'].startswith('KE') for r in areas) and levels == {'admin0', 'admin1', 'admin2'},
              (len(areas), sorted(levels)))

    portal_tests(a, kobo, uids, bridges, amani, mto, one, rows)
    welcome_tests(a, kobo, uids, bridges, one, rows)


def welcome_tests(a, kobo, uids, bridges, one, rows):
    """C11: the welcome email a CSO's new focal point gets (deploy/instance.toml turns it on;
    on staging only for Resend's test inbox): a scheduled email with the CSO's code, the
    update form's link filled in with its code and key, the portal."""
    F = 'FOCAL_POINTS'
    inbox = f'delivered+cso-{RUN}@resend.dev'
    s = kobo.submit(uids['cso-profile-ken'], profile('Karibu', [('KE047', 'KE047288')], **{F: [
        {f'{F}/name': 'Neema Inbox', f'{F}/position': 'Officer', f'{F}/email': inbox},
        {f'{F}/name': 'Juma Example', f'{F}/position': 'Officer', f'{F}/email': f'juma-{RUN}@example.org'}]}))
    bridges['cso-profile-ken'].once()
    cso = one('CCso', 'cKoboSubmissionUuid', s['_uuid'])
    mails = [a.call('GET', f'/Email/{m["id"]}') for m in a.call('GET', '/Email', {
        'maxSize': 10, 'select': 'id', **where('parentId', cso.get('accountId') or '-')})['list']]
    to = sorted(m.get('to') or '' for m in mails)
    check('C11', 'a new focal point gets one welcome email; one at example.org none (staging: the test inbox only)',
          to == [inbox], to)
    m = mails[0] if len(mails) == 1 else {}
    body = m.get('body') or ''
    check('C11', 'scheduled (EspoCRM sends it), from noreply@, on the CSO\'s Account',
          m.get('status') == 'Draft' and m.get('sendAt') and m.get('parentType') == 'Account'
          and 'noreply@' in (m.get('from') or m.get('fromAddress') or m.get('fromString') or ''),
          {k: m.get(k) for k in ('status', 'sendAt', 'parentType', 'from', 'fromAddress')})
    check('C11', "its code, the Kenya update form's link with the code and key filled in, the portal",
          cso.get('code', '-') in body and 'x/80mzANLS' in body and f'cso%5D={cso.get("code")}' in body
          and f'key%5D={cso.get("updateKey")}' in body and '/portal/cso/' in body, body[:300])


def portal_tests(a, kobo, uids, bridges, amani, mto, one, rows):
    """C10: a CSO's contact in the CSO portal, with their own password, through the portal's
    API (what its pages call)."""
    portal = by(a, 'Portal', 'name', 'CSO portal')
    role = by(a, 'PortalRole', 'name', 'CSO portal')
    check('C10', 'the CSO portal (customId cso) and its role are there', len(portal) == 1 and len(role) == 1
          and a.call('GET', f'/Portal/{portal[0]["id"]}').get('customId') == 'cso', (len(portal), len(role)))
    if not (portal and role):
        return
    chege = next(c for c in rows('Contact', amani) if c.get('firstName') == 'Chege')
    password = secrets.token_urlsafe(14)
    a.call('POST', '/User', body={'userName': f'csot-{RUN}', 'type': 'portal', 'password': password, 'contactId': chege['id'],
                                  'firstName': 'Chege', 'lastName': 'Newer', 'portalsIds': [portal[0]['id']],
                                  'portalRolesIds': [role[0]['id']], 'isActive': True,
                                  # its Accounts: what the portal's "account" level checks (EspoCRM's
                                  # "Create Portal User" on a contact fills them; the API doesn't)
                                  'accountsIds': [chege['accountId']]})
    me = Espo(URL, basic=f'csot-{RUN}:{password}')
    me.base = f'{URL}/api/v1/portal-access/{portal[0]["id"]}'
    seen = {r['name'] for r in me.call('GET', '/CCso', {'maxSize': 50, 'select': 'name'})['list']}
    check('C10', 'a contact sees their CSO only', seen == {amani['name']}, seen)
    got = me.call('GET', f'/CCso/{amani["id"]}')
    check('C10', "their CSO's profile, without its key", got.get('name') == amani['name'] and 'updateKey' not in got
          and 'keyGiven' not in got, sorted(k for k in got if 'ey' in k))
    check('C10', 'another CSO refused', status(lambda: me.call('GET', f'/CCso/{mto["id"]}')) == 403)
    me.call('PUT', f'/CCso/{amani["id"]}', body={'sharing': 'profile_only', 'updateKey': 'X' * 16})
    got = a.call('GET', f'/CCso/{amani["id"]}')
    check('C10', 'they change its sharing (the formulas follow: no shared contact), not its key',
          got.get('sharing') == 'profile_only' and not got.get('sharedContact') and got.get('updateKey') == amani['updateKey'],
          {k: got.get(k) for k in ('sharing', 'sharedContact')})
    me.call('PUT', f'/CCso/{amani["id"]}', body={'sharing': 'yes'})
    area = by(a, 'CAdminArea', 'pcode', 'KE001001')[0]
    place = me.call('POST', '/CPresence', body={'name': 'x', 'adminAreaId': area['id']})
    got = a.call('GET', f'/CPresence/{place["id"]}')
    check('C10', "a place they add: their CSO's (not picked), its Account and teams, P-codes, current",
          got.get('csoId') == amani['id'] and got.get('accountId') == amani['accountId'] and got.get('pcode2') == 'KE001001'
          and got.get('teamsIds') == amani['teamsIds'] and got.get('current') is True,
          {k: got.get(k) for k in ('csoName', 'accountName', 'pcode2', 'teamsNames', 'current')})
    new = me.call('POST', '/Contact', body={'firstName': 'Dalia', 'lastName': 'Joined', 'emailAddress': f'dalia-{RUN}@example.org'})
    got = a.call('GET', f'/Contact/{new["id"]}')
    shared = a.call('GET', f'/CCso/{amani["id"]}').get('sharedContact') or ''
    check('C10', "a contact they add: their CSO's, its Account and teams, in its shared contact",
          got.get('cCsoId') == amani['id'] and got.get('accountId') == amani['accountId'] and 'Dalia Joined' in shared,
          ({k: got.get(k) for k in ('cCsoName', 'accountName')}, shared))
    amina = next(c for c in rows('Contact', amani) if c.get('firstName') == 'Amina')
    me.call('PUT', f'/Contact/{amina["id"]}', body={'cCsoActive': False})
    shared = a.call('GET', f'/CCso/{amani["id"]}').get('sharedContact') or ''
    check('C10', 'someone who left: marked no longer its contact, gone from its shared contact',
          'Amina' not in shared and 'Dalia' in shared, shared)
    up = me.call('POST', '/CCsoUpdate', body={'name': 'x', 'adminAreaId': area['id'], 'status': 'active', 'roles': ['wash']})
    got = a.call('GET', f'/CCsoUpdate/{up["id"]}')
    check('C10', 'an update they make: their CSO\'s, counted without a key (they signed in)',
          got.get('csoId') == amani['id'] and got.get('keyCheck') == 'ok' and got.get('current') is True,
          {k: got.get(k) for k in ('csoName', 'keyCheck', 'current')})
    other = rows('CPresence', mto)
    check('C10', "another CSO's place refused", other and status(lambda: me.call('GET', f'/CPresence/{other[0]["id"]}')) == 403)
    s9 = kobo.submit(uids['cso-profile-ken'], profile('Amani', [('KE047', 'KE047288')], cso=amani['code'], key=amani['updateKey'],
                                                      roles='risk_communication mhpss wash'))
    bridges['cso-profile-ken'].once()
    got = a.call('GET', f'/CPresence/{place["id"]}')
    check('C10', 'the profile sent again from Kobo: the place added in the portal stays current', got.get('current') is True,
          got.get('current'))


if __name__ == '__main__':
    main()
