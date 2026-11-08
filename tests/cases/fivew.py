#!/usr/bin/env python3
"""
W1-W6: Workflow E, a response's 5W (plans/workflow-e-5w-plan.md), and the short codes.

    python3 -I tests/cases/fivew.py

Makes its own fixtures, removing earlier ones first: a response "FIVEW Hurricane" in team
Response: Test EQ 1 with an ETC project (Cluster: Test EQ 1 ETC) and a WASH project
(Cluster: Test EQ 1 WASH), two responding organisations (TELCO: ETC; RCJ: ETC and WASH)
and their activities. Then checks the formulas as admin, and access as each test user with
their own password. Writes tests/results/fivew.json.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, BridgeError, admin, as_user  # noqa: E402

RESPONSE = 'FIVEW Hurricane'
CODE = re.compile(r'^(RSP|PRJ|ORG|ACT|TSK)-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{4}$')
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


def names(espo, entity, resp_id):
    try:
        rows = espo.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name', **where('responseId', resp_id)})['list']
    except BridgeError as e:
        return e.status
    return {r['name'] for r in rows}


def cleanup(a):
    for resp in a.call('GET', '/CResponse', {'maxSize': 50, 'select': 'name', **where('name', RESPONSE)})['list']:
        for entity in ('CActivity', 'CResponder', 'Task', 'CProject'):
            attr = 'cResponseId' if entity == 'Task' else 'responseId'
            for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id', **where(attr, resp['id'])})['list']:
                a.call('DELETE', f'/{entity}/{r["id"]}')
        a.call('DELETE', f'/CResponse/{resp["id"]}')


def main():
    a = admin()
    cleanup(a)
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    try:
        run(a, team, user)
    finally:
        cleanup(a)
    path = ROOT / 'tests' / 'results' / 'fivew.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'fivew: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def run(a, team, user):
    eq1, etc, wash = team['Response: Test EQ 1'], team['Cluster: Test EQ 1 ETC'], team['Cluster: Test EQ 1 WASH']
    resp = a.call('POST', '/CResponse', body={'name': RESPONSE, 'status': 'Active', 'teamsIds': [eq1],
                                              'leadId': user['staff-1'], 'emergencyType': 'Cyclone', 'country': 'Jamaica'})
    p_etc = a.call('POST', '/CProject', body={'name': 'FIVEW ETC', 'cluster': 'etc', 'status': 'Active',
                                              'responseId': resp['id'], 'teamsIds': [etc], 'leadId': user['cluster-lead']})
    p_wash = a.call('POST', '/CProject', body={'name': 'FIVEW WASH', 'cluster': 'wash', 'status': 'Active',
                                               'responseId': resp['id'], 'teamsIds': [wash]})
    telco = a.call('POST', '/CResponder', body={'name': 'FIVEW Telecom Partners', 'acronym': 'TELCO', 'orgType': 'ingo',
                                                'clusters': ['etc'], 'responseId': resp['id']})
    rcj = a.call('POST', '/CResponder', body={'name': 'FIVEW Red Cross Jamaica', 'acronym': 'RCJ', 'orgType': 'rcrc',
                                              'clusters': ['etc', 'wash'], 'responseId': resp['id']})
    kingston = a.call('GET', '/CAdminArea', {'maxSize': 1, **where('pcode', 'JM01')})['list'][0]

    def activity(org, proj, **kw):
        return a.call('POST', '/CActivity', body={'name': kw.pop('name', 'Hygiene kits'), 'responderId': org['id'],
                                                  'projectId': proj['id'], 'adminAreaId': kingston['id'], **kw})

    act = activity(rcj, p_wash, activityType='wash_hygiene_kits', status='completed', startDate='2026-11-01',
                   endDate='2026-11-03', reportDate='2026-11-04', girls=10, boys=12, women=20, men=15, elderlyWomen=3,
                   elderlyMen=2, quantity=120, unit='hygiene kits')
    act_etc = activity(telco, p_etc, name='Connectivity', activityType='etc_connectivity', startDate='2026-11-02',
                       reportDate='2026-11-02')

    # --- W1: short codes ---------------------------------------------------------------------
    got = {e: a.call('GET', f'/{e}/{r["id"]}').get('code') for e, r in
           (('CResponse', resp), ('CProject', p_etc), ('CResponder', rcj), ('CActivity', act))}
    task = a.call('GET', '/Task', {'maxSize': 1, 'select': 'cCode', **where('cResponseId', resp['id'])})['list'][0]
    got['Task'] = task.get('cCode')
    check('W1', 'every new record has its short code (RSP-, PRJ-, ORG-, ACT-, TSK-)',
          all(c and CODE.match(c) for c in got.values()) and
          [c[:3] for c in got.values()] == ['RSP', 'PRJ', 'ORG', 'ACT', 'TSK'], got)
    a.call('PUT', f'/CProject/{p_etc["id"]}', body={'code': 'PRJ-XXXX'})
    check('W1', "a code can't be changed through the API (read-only)",
          a.call('GET', f'/CProject/{p_etc["id"]}')['code'] == got['CProject'])
    found = a.call('GET', '/CProject', {'maxSize': 5, 'select': 'name', 'textFilter': got['CProject']})['list']
    check('W1', "a project found by its code in the list's search", [r['name'] for r in found] == ['FIVEW ETC'], found)
    codes = [r['code'] for r in a.call('GET', '/CResponder', {'maxSize': 200, 'select': 'code'})['list']]
    check('W1', 'codes are unique (organisations)', len(codes) == len(set(codes)) and None not in codes, len(codes))

    # --- W2: an organisation's teams follow its clusters ----------------------------------------
    teams = lambda e, r: set(a.call('GET', f'/{e}/{r["id"]}')['teamsIds'])  # noqa: E731
    check('W2', "TELCO (ETC): the response's team and the ETC project's", teams('CResponder', telco) == {eq1, etc},
          teams('CResponder', telco))
    check('W2', 'RCJ (ETC, WASH): both projects\' teams', teams('CResponder', rcj) == {eq1, etc, wash}, teams('CResponder', rcj))
    a.call('PUT', f'/CResponder/{rcj["id"]}', body={'clusters': ['wash']})
    check('W2', 'RCJ no longer in ETC: the ETC team goes', teams('CResponder', rcj) == {eq1, wash}, teams('CResponder', rcj))
    a.call('PUT', f'/CResponder/{rcj["id"]}', body={'clusters': ['etc', 'wash', 'shelter']})
    shelter_team = a.call('POST', '/Team', body={'name': 'FIVEW Shelter'})
    try:
        a.call('POST', '/CProject', body={'name': 'FIVEW Shelter', 'cluster': 'shelter', 'status': 'Active',
                                          'responseId': resp['id'], 'teamsIds': [shelter_team['id']]})
        check('W2', "a new Shelter project: RCJ (in Shelter) gets its team, TELCO doesn't",
              shelter_team['id'] in teams('CResponder', rcj) and shelter_team['id'] not in teams('CResponder', telco),
              [teams('CResponder', rcj), teams('CResponder', telco)])
    finally:
        a.call('DELETE', f'/Team/{shelter_team["id"]}')

    # --- W3: an activity --------------------------------------------------------------------
    got = a.call('GET', f'/CActivity/{act["id"]}')
    check('W3', "an activity: its project's teams and response", set(got['teamsIds']) == {eq1, wash}
          and got.get('responseId') == resp['id'], {k: got.get(k) for k in ('teamsIds', 'responseId')})
    check('W3', 'people reached: the six groups summed (62)', got.get('peopleReached') == 62, got.get('peopleReached'))
    check('W3', "named after its organisation's acronym", got['name'] == 'RCJ · Hygiene kits', got['name'])
    org = a.call('GET', f'/CResponder/{rcj["id"]}')
    check('W3', "the organisation's last report and status follow", (org.get('lastReport'), org.get('status'))
          == ('2026-11-04', 'active'), (org.get('lastReport'), org.get('status')))
    activity(rcj, p_wash, name='Older report', activityType='wash_water_trucking', startDate='2026-10-30',
             reportDate='2026-10-31')
    check('W3', 'an older report leaves the last report as it was',
          a.call('GET', f'/CResponder/{rcj["id"]}').get('lastReport') == '2026-11-04')
    a.call('PUT', f'/CActivity/{act["id"]}', body={'girls': 20})
    check('W3', 'changed: summed again (72)', a.call('GET', f'/CActivity/{act["id"]}').get('peopleReached') == 72)

    # --- W4: what's refused ------------------------------------------------------------------
    def refused(**kw):
        try:
            activity(**kw)
            return None
        except BridgeError as e:
            return e.status
    check('W4', 'an activity that ends before it starts: refused',
          refused(org=rcj, proj=p_wash, startDate='2026-11-05', endDate='2026-11-01') == 400)
    check('W4', "TELCO (ETC only) reporting under the WASH project: refused",
          refused(org=telco, proj=p_wash, startDate='2026-11-05') == 400)
    other = a.call('POST', '/CResponse', body={'name': RESPONSE + ' other', 'status': 'Active', 'teamsIds': [eq1]})
    try:
        stranger = a.call('POST', '/CResponder', body={'name': 'FIVEW Stranger', 'acronym': 'STR', 'clusters': ['etc'],
                                                       'responseId': other['id']})
        check('W4', "an organisation of another response under this response's project: refused",
              refused(org=stranger, proj=p_etc, startDate='2026-11-05') == 400)
        a.call('DELETE', f'/CResponder/{stranger["id"]}')
    finally:
        for t in a.call('GET', '/Task', {'maxSize': 20, 'select': 'id', **where('cResponseId', other['id'])})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')
        a.call('DELETE', f'/CResponse/{other["id"]}')

    # --- W5: who sees what -------------------------------------------------------------------
    rid = resp['id']
    for who in ('cluster-lead', 'cluster-partner'):
        u = as_user(who)
        check('W5', f'{who} (ETC): the ETC activity only', names(u, 'CActivity', rid) == {'TELCO · Connectivity'},
              names(u, 'CActivity', rid))
        check('W5', f'{who} (ETC): the organisations in ETC', names(u, 'CResponder', rid)
              == {'FIVEW Telecom Partners', 'FIVEW Red Cross Jamaica'}, names(u, 'CResponder', rid))
        check('W5', f'{who}: a WASH activity by id refused',
              status(lambda: u.call('GET', f'/CActivity/{act["id"]}')) == 403)
    v = as_user('cluster-viewer')
    check('W5', 'cluster-viewer (WASH): the WASH activities, and RCJ only',
          (names(v, 'CActivity', rid), names(v, 'CResponder', rid))
          == ({'RCJ · Hygiene kits', 'RCJ · Older report'}, {'FIVEW Red Cross Jamaica'}),
          [names(v, 'CActivity', rid), names(v, 'CResponder', rid)])
    check('W5', 'cluster-viewer: editing an activity refused',
          status(lambda: v.call('PUT', f'/CActivity/{act["id"]}', body={'unit': 'x'})) == 403)
    s = as_user('staff-1')
    check('W5', 'staff-1 (the response\'s team): every activity', len(names(s, 'CActivity', rid)) == 3,
          names(s, 'CActivity', rid))
    p = as_user('cluster-partner')
    mine = p.call('POST', '/CActivity', body={'name': 'Charging', 'responderId': telco['id'], 'projectId': p_etc['id'],
                                              'activityType': 'etc_charging', 'startDate': '2026-11-06',
                                              'adminAreaId': kingston['id'], 'teamsIds': [etc],
                                              # as the UI sends it: assigned to its maker, in their team
                                              'assignedUserId': user['cluster-partner']})
    check('W5', "cluster-partner: reports an ETC activity, in the project's teams",
          set(a.call('GET', f'/CActivity/{mine["id"]}')['teamsIds']) == {eq1, etc})
    check('W5', "cluster-partner: edits their own activity, not one they didn't make",
          status(lambda: p.call('PUT', f'/CActivity/{mine["id"]}', body={'unit': 'phones'})) == 200
          and status(lambda: p.call('PUT', f'/CActivity/{act_etc["id"]}', body={'unit': 'x'})) == 403)
    lead = as_user('cluster-lead')
    check('W5', 'cluster-lead: edits any of the project\'s activities',
          status(lambda: lead.call('PUT', f'/CActivity/{act_etc["id"]}', body={'status': 'completed'})) == 200)

    # --- W6: admin areas ---------------------------------------------------------------------
    for who in ('cluster-viewer', 'cluster-partner', 'staff-1'):
        u = as_user(who)
        areas = u.call('GET', '/CAdminArea', {'maxSize': 50, 'select': 'pcode', **where('country', 'JAM')})['list']
        check('W6', f"{who}: reads Jamaica's 14 parishes", len(areas) == 14, len(areas))
    check('W6', 'cluster-partner: editing a parish refused',
          status(lambda: p.call('PUT', f'/CAdminArea/{kingston["id"]}', body={'name': 'x'})) == 403)


if __name__ == '__main__':
    main()
