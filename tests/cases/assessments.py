#!/usr/bin/env python3
"""
A1-A7: the assessment registry (plans/assessment-registry-plan.md): the registration form
through the bridge (kobo/templates/assessment-registration.toml, generated with the form by
kobo/forms/assessment.py) into CAssessment (its Account, its Contact) and CAssessmentArea,
and their formulas: teams (the whole response's), areas and their P-codes, a submission sent
again, the review, overlaps, data checks, refused dates. Access as the cluster test users
and staff with their own passwords.

    python3 -I tests/cases/assessments.py [--kobo fake|real]

A fake Kobo by default (kobo-espo-bridge/fake_kobo.py); with --kobo real, the form on the
test account. Its response is "ASMT <run>" (team Response: Test EQ 1, an ETC and a WASH
project), its typed-in organisation "ASMT <run> Relief"; removed first and at the end.
Writes tests/results/assessments.json.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, BridgeError, admin, as_user, env  # noqa: E402

from bridges import Bridge, by, ensure_secrets  # noqa: E402

KIND = 'assessment-registration'
FORM = json.loads((ROOT / 'kobo' / 'forms' / f'{KIND}.json').read_text())
RUN = str(int(time.time()))[-6:]
PREFIX = 'ASMT'
CODE = re.compile(r'^ASM-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{4}$')
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


def days(n):
    return (date.today() + timedelta(days=n)).isoformat()


def cleanup(a):
    for asm in a.call('GET', '/CAssessment', {'maxSize': 200, 'select': 'id', **where('name', PREFIX, 'startsWith')})['list']:
        for r in a.call('GET', '/CAssessmentArea', {'maxSize': 200, 'select': 'id', **where('assessmentId', asm['id'])})['list']:
            a.call('DELETE', f'/CAssessmentArea/{r["id"]}')
        a.call('DELETE', f'/CAssessment/{asm["id"]}')
    for resp in a.call('GET', '/CResponse', {'maxSize': 20, 'select': 'id', **where('name', PREFIX, 'startsWith')})['list']:
        for entity, attr in (('Task', 'cResponseId'), ('CProject', 'responseId')):
            for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id', **where(attr, resp['id'])})['list']:
                a.call('DELETE', f'/{entity}/{r["id"]}')
        a.call('DELETE', f'/CResponse/{resp["id"]}')
    for acc in a.call('GET', '/Account', {'maxSize': 20, 'select': 'id', **where('name', PREFIX, 'startsWith')})['list']:
        a.call('DELETE', f'/Account/{acc["id"]}')
    for c in a.call('GET', '/Contact', {'maxSize': 50, 'select': 'id', **where('emailAddress', 'delivered+asmt-', 'startsWith')})['list']:
        a.call('DELETE', f'/Contact/{c["id"]}')
    for t in a.call('GET', '/Team', {'maxSize': 20, 'select': 'id', **where('name', PREFIX, 'startsWith')})['list']:
        a.call('DELETE', f'/Team/{t["id"]}')


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
        uid = kobo.add_form(FORM['settings']['form_title'], FORM)
    else:
        from staging import RealKobo
        kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
        uid = kobo.deploy_all({KIND: FORM})[KIND]
    bridge = Bridge(KIND, kobo.url, kobo.token)
    bridge.setup()
    print(f'setup done; Kobo {args.kobo} at {kobo.url}')
    try:
        run(a, kobo, uid, bridge)
    finally:
        cleanup(a)
    path = ROOT / 'tests' / 'results' / ('assessments.json' if args.kobo == 'fake' else 'assessments-real.json')
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'assessments: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def answers(response_code, title, org, sectors, areas, start, end=None, state='planned', code=None, level='admin2', **kw):
    """A submission's answers, as Kobo names them (group paths). areas: (admin1, admin2 or None)."""
    W = 'WHERE/AREAS'
    rows = [{f'{W}/admin1': p1, **({f'{W}/admin2': p2} if p2 else {}), f'{W}/area': p2 or p1} for p1, p2 in areas]
    return {**({'assessment': code} if code else {}), 'response': response_code,
            'REPORTER/organisation': org, **({'REPORTER/organisation_other': kw.pop('other')} if 'other' in kw else {}),
            'REPORTER/reporter_name': 'Ana Assessor', 'REPORTER/reporter_email': f'delivered+asmt-{RUN}@resend.dev',
            'ASSESSMENT/title': f'{PREFIX} {RUN} {title}', 'ASSESSMENT/sectors': ' '.join(sectors),
            'ASSESSMENT/coordination': 'harmonised', 'ASSESSMENT/methodology': 'key_informant direct_observation',
            'ASSESSMENT/frequency': 'single', 'ORGS/lead_organisation': org,
            **({'ORGS/participants': kw.pop('participants')} if 'participants' in kw else {}),
            'DATES/start_date': start, **({'DATES/end_date': end} if end else {}),
            'WHERE/geo_level': level, 'WHERE/AREAS': rows, 'WHERE/area_codes': ' '.join(r[f'{W}/area'] for r in rows),
            'STATUS/status': state, **kw}


def run(a, kobo, uid, bridge):
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 100})['list']}
    eq1, etc, wash = team['Response: Test EQ 1'], team['Cluster: Test EQ 1 ETC'], team['Cluster: Test EQ 1 WASH']
    org = {c: a.call('GET', '/COrganisation', {'maxSize': 1, **where('code', c)})['list'][0]
           for c in ('ORG_ADRA', 'ORG_AMERICARES', 'other')}
    kingston = a.call('GET', '/CAdminArea', {'maxSize': 3, 'orderBy': 'pcode', **where('parentPcode', 'JM17')})['list']
    resp = a.call('POST', '/CResponse', body={'name': f'{PREFIX} {RUN} Response', 'status': 'Active', 'teamsIds': [eq1],
                                              'emergencyType': 'Cyclone', 'country': 'Jamaica'})
    rcode = a.call('GET', f'/CResponse/{resp["id"]}')['code']
    for name, cluster, t in (('ETC', 'EMERGENCY_TELECOMS', etc), ('WASH', 'WASH', wash)):
        a.call('POST', '/CProject', body={'name': f'{PREFIX} {RUN} {name}', 'cluster': cluster, 'status': 'Active',
                                          'responseId': resp['id'], 'teamsIds': [t]})
    get = lambda e, i: a.call('GET', f'/{e}/{i}')  # noqa: E731

    def submit(**kw):
        s = kobo.submit(uid, answers(rcode, **kw))
        code, log, _ = bridge.once()
        rows = by(a, 'CAssessment', 'cKoboSubmissionUuid', s['_uuid'])
        return (get('CAssessment', rows[0]['id']) if rows else {}), log

    def areas(asm, **filters):
        rows = [get('CAssessmentArea', r['id']) for r in by(a, 'CAssessmentArea', 'assessmentId', asm['id'])]
        return [r for r in rows if all(r.get(k) == v for k, v in filters.items())]

    # --- A1: an assessment registered --------------------------------------------------------------
    one, log = submit(title='Rapid WASH', org='ORG_ADRA', sectors=['WASH', 'HEALTH'],
                      areas=[('JM17', kingston[0]['pcode']), ('JM08', None)], start=days(2), end=days(12),
                      participants='ORG_AMERICARES ORG_ADRA')
    check('A1', 'a submission makes one assessment, with its ASM- code, planned, not checked yet',
          bool(one.get('code') and CODE.match(one['code'])) and (one.get('status'), one.get('review')) == ('planned', 'new'),
          {k: one.get(k) for k in ('code', 'status', 'review')} if one else log[-800:])
    adra = a.call('GET', '/Account', {'maxSize': 1, 'select': 'id', **where('cOrganisationId', org['ORG_ADRA']['id'])})['list']
    check('A1', "its organisation's Account (the list entry's), its registrant's Contact, its response",
          one.get('accountId') == (adra[0]['id'] if adra else 'none') and one.get('contactId') and one.get('responseId') == resp['id'],
          {k: one.get(k) for k in ('accountId', 'contactId', 'responseId')})
    check('A1', 'its answers: sectors and methodology as codes, dates, level, the participating organisations linked',
          one.get('sectors') == ['WASH', 'HEALTH'] and one.get('methodology') == ['key_informant', 'direct_observation']
          and (one.get('startDate'), one.get('endDate'), one.get('geoLevel')) == (days(2), days(12), 'admin2')
          and set(one.get('participantsIds') or []) == {org['ORG_ADRA']['id'], org['ORG_AMERICARES']['id']},
          {k: one.get(k) for k in ('sectors', 'methodology', 'startDate', 'endDate', 'geoLevel', 'participantsIds')})

    # --- A2: the whole response sees it ------------------------------------------------------------
    check('A2', "in the response's team and every cluster project's (ETC too, not one of its sectors)",
          set(one.get('teamsIds') or []) == {eq1, etc, wash}, one.get('teamsNames'))
    extra = a.call('POST', '/Team', body={'name': f'{PREFIX} {RUN} Shelter'})
    a.call('POST', '/CProject', body={'name': f'{PREFIX} {RUN} Shelter', 'cluster': 'SHELTER', 'status': 'Active',
                                      'responseId': resp['id'], 'teamsIds': [extra['id']]})
    check('A2', 'a new cluster project in the response: its team gets the assessment',
          extra['id'] in get('CAssessment', one['id'])['teamsIds'])
    viewer, partner, outsider = as_user('cluster-viewer'), as_user('cluster-partner'), as_user('staff-2')
    check('A2', 'cluster-viewer (WASH) and cluster-partner (ETC) read it; staff-2 (not in the response) does not',
          status(lambda: viewer.call('GET', f'/CAssessment/{one["id"]}')) == 200
          and status(lambda: partner.call('GET', f'/CAssessment/{one["id"]}')) == 200
          and status(lambda: outsider.call('GET', f'/CAssessment/{one["id"]}')) == 403)

    # --- A3: its areas ----------------------------------------------------------------------------
    rows = areas(one)
    k1 = next((r for r in rows if r.get('pcode') == kingston[0]['pcode']), {})
    check('A3', 'one row per area, each linked to its admin area, with its P-codes up its parents and its country',
          len(rows) == 2 and k1.get('adminAreaId') == kingston[0]['id'] and k1.get('pcode1') == 'JM17'
          and k1.get('pcode2') == kingston[0]['pcode'] and k1.get('country') == 'JAM',
          [{k: r.get(k) for k in ('pcode', 'pcode1', 'pcode2', 'country', 'adminAreaName')} for r in rows])
    check('A3', "a row has its assessment's teams, response, Account, sectors, status and dates; it's current",
          set(k1.get('teamsIds') or []) == set(get('CAssessment', one['id'])['teamsIds']) and k1.get('responseId') == resp['id']
          and k1.get('accountId') == one.get('accountId') and k1.get('sectors') == ['WASH', 'HEALTH']
          and (k1.get('status'), k1.get('startDate'), k1.get('current')) == ('planned', days(2), True)
          and k1.get('name', '').startswith(one['code'] + ': '),
          {k: k1.get(k) for k in ('responseId', 'accountId', 'sectors', 'status', 'startDate', 'current', 'name')})

    # --- A4: another organisation's, at the same time and place: an overlap -----------------------
    two, _ = submit(title='Health check', org='ORG_AMERICARES', sectors=['HEALTH'], areas=[('JM17', None)],
                    start=days(5), end=days(20), level='admin1')
    three, _ = submit(title='Shelter count', org='ORG_AMERICARES', sectors=['SHELTER'], areas=[('JM17', None)],
                      start=days(5), end=days(20), level='admin1')
    four, _ = submit(title='Later health', org='ORG_AMERICARES', sectors=['HEALTH'], areas=[('JM17', None)],
                     start=days(30), end=days(40), level='admin1')
    check('A4', "a Health assessment of Kingston (the parish) while ADRA's covers a community in it: flagged, naming ADRA's",
          'overlap' in (two.get('dataChecks') or []) and two.get('overlapsWith') == one['code'],
          {k: two.get(k) for k in ('dataChecks', 'overlapsWith')})
    check('A4', "another sector, or another time: no overlap",
          'overlap' not in (three.get('dataChecks') or []) and 'overlap' not in (four.get('dataChecks') or []),
          (three.get('dataChecks'), four.get('dataChecks')))

    # --- A5: reviewed, then sent again --------------------------------------------------------------
    staff = as_user('staff-1')
    staff.call('PUT', f'/CAssessment/{one["id"]}', body={'review': 'checked'})
    check('A5', 'staff-1 (the A&A Cell, the response\'s team) marks it checked; cluster-partner can\'t edit it',
          get('CAssessment', one['id'])['review'] == 'checked'
          and status(lambda: partner.call('PUT', f'/CAssessment/{one["id"]}', body={'notes': 'x'})) == 403)
    again, _ = submit(title='Rapid WASH', org='ORG_ADRA', sectors=['WASH', 'HEALTH'], areas=[('JM08', None)],
                      start=days(-30), end=days(-20), state='completed', code=one['code'])
    check('A5', 'sent again with its code: the same assessment, completed, its dates moved, not checked any more',
          again.get('id') == one['id'] and (again.get('status'), again.get('endDate'), again.get('review')) == ('completed', days(-20), 'new'),
          {k: again.get(k) for k in ('id', 'status', 'endDate', 'review')})
    current = areas(one, current=True)
    check('A5', "its areas: the new submission's current, the dropped one not",
          [r.get('pcode') for r in current] == ['JM08'] and len(areas(one)) == 3 and current[0].get('status') == 'completed',
          [(r.get('pcode'), r.get('current'), r.get('status')) for r in areas(one)])

    # --- A6: data checks ----------------------------------------------------------------------------
    check('A6', 'completed 20 days ago with no report: flagged; given a report link: the flag goes',
          'no_report' in (again.get('dataChecks') or []), again.get('dataChecks'))
    a.call('PUT', f'/CAssessment/{one["id"]}', body={'reportLink': 'https://reliefweb.int/report/x'})
    got = get('CAssessment', one['id'])
    check('A6', '... report available, no flag', got.get('reportAvailable') is True and 'no_report' not in (got.get('dataChecks') or []),
          {k: got.get(k) for k in ('reportAvailable', 'dataChecks')})
    late, _ = submit(title='Not started', org='other', other=f'{PREFIX} {RUN} Relief', sectors=['WASH'], areas=[],
                     start=days(-3), level='admin1')
    check('A6', 'planned, its start passed, no areas given: both flagged; a typed-in organisation gets an Account of its name',
          {'start_passed', 'no_areas'} <= set(late.get('dataChecks') or [])
          and get('Account', late['accountId'])['name'] == f'{PREFIX} {RUN} Relief' if late.get('accountId') else False,
          {k: late.get(k) for k in ('dataChecks', 'accountId')})

    # --- A7: refused --------------------------------------------------------------------------------
    check('A7', 'an end before its start: refused (any save through the API)',
          status(lambda: a.call('PUT', f'/CAssessment/{one["id"]}', body={'startDate': days(-10), 'endDate': days(-15)})) == 400)


if __name__ == '__main__':
    main()
