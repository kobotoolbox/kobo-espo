#!/usr/bin/env python3
"""
W1-W9: Workflow E, a response's 5W (plans/workflow-e-5w-plan.md) on the Hurricane Melissa
5W form's model, and the short codes.

    python3 -I tests/cases/fivew.py

Makes its own fixtures, removing earlier ones first: a response "FIVEW Hurricane" in team
Response: Test EQ 1 with an Emergency Telecommunications project (Cluster: Test EQ 1 ETC)
and a WASH project (Cluster: Test EQ 1 WASH), a registered organisation (ADRA, in both
sectors), activities with their locations (communities) and focal points. Then checks the
formulas as admin, and access as each test user with their own password. Writes
tests/results/fivew.json.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, BridgeError, admin, as_user  # noqa: E402

RESPONSE = 'FIVEW Hurricane'
CODE = re.compile(r'^(RSP|PRJ|REG|ACT|TSK)-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{4}$')
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
    for resp in a.call('GET', '/CResponse', {'maxSize': 50, 'select': 'name', **where('name', RESPONSE, 'startsWith')})['list']:
        acts = a.call('GET', '/CActivity', {'maxSize': 200, 'select': 'id', **where('responseId', resp['id'])})['list']
        for act in acts:
            for entity in ('CActivityLocation', 'CFocalPoint'):
                for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'id', **where('activityId', act['id'])})['list']:
                    a.call('DELETE', f'/{entity}/{r["id"]}')
            a.call('DELETE', f'/CActivity/{act["id"]}')
        for entity, attr in (('CResponder', 'responseId'), ('Task', 'cResponseId'), ('CProject', 'responseId')):
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
    org = {c: a.call('GET', '/COrganisation', {'maxSize': 1, **where('code', c)})['list'][0]
           for c in ('ORG_ADRA', 'ORG_AMERICARES', 'other')}
    area = {c: a.call('GET', '/CAdminArea', {'maxSize': 1, **where('pcode', c)})['list'][0]
            for c in ('JM17', 'JM08')}
    community = a.call('GET', '/CAdminArea', {'maxSize': 2, 'orderBy': 'pcode', **where('parentPcode', 'JM17')})['list']
    resp = a.call('POST', '/CResponse', body={'name': RESPONSE, 'status': 'Active', 'teamsIds': [eq1],
                                              'leadId': user['staff-1'], 'emergencyType': 'Cyclone', 'country': 'Jamaica'})
    p_etc = a.call('POST', '/CProject', body={'name': 'FIVEW ETC', 'cluster': 'EMERGENCY_TELECOMS', 'status': 'Active',
                                              'responseId': resp['id'], 'teamsIds': [etc], 'leadId': user['cluster-lead']})
    p_wash = a.call('POST', '/CProject', body={'name': 'FIVEW WASH', 'cluster': 'WASH', 'status': 'Active',
                                               'responseId': resp['id'], 'teamsIds': [wash]})
    adra = a.call('POST', '/CResponder', body={'name': 'x', 'organisationId': org['ORG_ADRA']['id'], 'responseId': resp['id'],
                                               'clusters': ['EMERGENCY_TELECOMS', 'WASH']})

    def activity(**kw):
        return a.call('POST', '/CActivity', body={'name': 'Water trucking', 'responseId': resp['id'],
                                                  'leadOrganisationId': org['ORG_ADRA']['id'], 'sector': 'WASH',
                                                  'activityType': 'other', 'status': 'IN_PROGRESS',
                                                  'startDate': '2026-11-01', 'reportDate': '2026-11-04', **kw})

    act = activity()
    act_etc = activity(name='Connectivity', sector='EMERGENCY_TELECOMS', leadOrganisationId=org['ORG_AMERICARES']['id'])

    # --- W1: short codes ---------------------------------------------------------------------
    got = {e: a.call('GET', f'/{e}/{r["id"]}').get('code') for e, r in
           (('CResponse', resp), ('CProject', p_etc), ('CResponder', adra), ('CActivity', act))}
    task = a.call('GET', '/Task', {'maxSize': 1, 'select': 'cCode', **where('cResponseId', resp['id'])})['list'][0]
    got['Task'] = task.get('cCode')
    check('W1', 'every new record has its short code (RSP-, PRJ-, REG-, ACT-, TSK-)',
          all(c and CODE.match(c) for c in got.values())
          and [c[:3] for c in got.values()] == ['RSP', 'PRJ', 'REG', 'ACT', 'TSK'], got)
    a.call('PUT', f'/CProject/{p_etc["id"]}', body={'code': 'PRJ-XXXX'})
    check('W1', "a code can't be changed through the API (read-only)",
          a.call('GET', f'/CProject/{p_etc["id"]}')['code'] == got['CProject'])
    found = a.call('GET', '/CProject', {'maxSize': 5, 'select': 'name', 'textFilter': got['CProject']})['list']
    check('W1', "a project found by its code in the list's search", [r['name'] for r in found] == ['FIVEW ETC'], found)

    # --- W2: a registered organisation ---------------------------------------------------------
    teams = lambda e, r: set(a.call('GET', f'/{e}/{r["id"]}')['teamsIds'])  # noqa: E731
    reg = a.call('GET', f'/CResponder/{adra["id"]}')
    check('W2', "registered: named after the organisation in the list, with its type",
          (reg['name'], reg.get('orgType')) == (org['ORG_ADRA']['name'], 'INTERNATIONAL_NGO'), (reg['name'], reg.get('orgType')))
    check('W2', "in the response's team and both sectors' projects'", teams('CResponder', adra) == {eq1, etc, wash},
          teams('CResponder', adra))
    a.call('PUT', f'/CResponder/{adra["id"]}', body={'clusters': ['WASH']})
    check('W2', 'no longer in Emergency Telecommunications: its team goes', teams('CResponder', adra) == {eq1, wash})
    a.call('PUT', f'/CResponder/{adra["id"]}', body={'clusters': ['WASH', 'SHELTER']})
    shelter = a.call('POST', '/Team', body={'name': 'FIVEW Shelter'})
    try:
        a.call('POST', '/CProject', body={'name': 'FIVEW Shelter', 'cluster': 'SHELTER', 'status': 'Active',
                                          'responseId': resp['id'], 'teamsIds': [shelter['id']]})
        check('W2', 'a new Shelter project: the organisation (in Shelter) gets its team',
              shelter['id'] in teams('CResponder', adra))
    finally:
        a.call('DELETE', f'/Team/{shelter["id"]}')

    # --- W3: an activity ---------------------------------------------------------------------
    got = a.call('GET', f'/CActivity/{act["id"]}')
    check('W3', "its sector's project (WASH), and that project's teams", got.get('projectId') == p_wash['id']
          and set(got['teamsIds']) == {eq1, wash}, {k: got.get(k) for k in ('projectId', 'teamsIds')})
    check('W3', 'the lead organisation implements it when no other is named',
          got.get('implementingOrganisationId') == org['ORG_ADRA']['id'])
    check('W3', "named after its organisation's code", got['name'] == 'ADRA · Water trucking', got['name'])
    check('W3', "linked to the organisation's registration, whose last report moves on",
          got.get('responderId') == adra['id'] and a.call('GET', f'/CResponder/{adra["id"]}').get('lastReport') == '2026-11-04')
    health = activity(name='Clinic', sector='HEALTH')
    got = a.call('GET', f'/CActivity/{health["id"]}')
    check('W3', "a sector with no project in the response: the response's team only (coordinators)",
          not got.get('projectId') and set(got['teamsIds']) == {eq1}, {k: got.get(k) for k in ('projectId', 'teamsIds')})

    # --- W4: its locations (communities) -------------------------------------------------------
    def location(activity_rec, comm, **kw):
        return a.call('POST', '/CActivityLocation', body={'name': 'x', 'activityId': activity_rec['id'],
                                                          'communityId': comm['id'], **kw})
    loc1 = location(act, community[0], quantity=10, budget=500, populationTargeted=100, populationReached=60,
                    populationGroups=['idp'], idpWomenReached=30, idpMenReached=20, idpChildrenReached=10)
    location(act, community[1], quantity=5, budget=250, populationTargeted=50, populationReached=40)
    got = a.call('GET', f'/CActivityLocation/{loc1["id"]}')
    check('W4', "a location: its activity's teams, project and response", set(got['teamsIds']) == {eq1, wash}
          and got.get('projectId') == p_wash['id'] and got.get('responseId') == resp['id'],
          {k: got.get(k) for k in ('teamsIds', 'projectId', 'responseId')})
    check('W4', 'its parish from the community, and named after both',
          got.get('parishId') == area['JM17']['id'] and got['name'] == f'{community[0]["name"]}, {area["JM17"]["name"]}',
          {k: got.get(k) for k in ('parishId', 'name')})
    act_now = a.call('GET', f'/CActivity/{act["id"]}')
    check('W4', "the activity's totals: 2 communities, 100 reached, 150 targeted, 15 units, 750 budget",
          [act_now.get(k) for k in ('communities', 'peopleReached', 'peopleTargeted', 'quantity', 'budget')]
          == [2, 100, 150, 15, 750], [act_now.get(k) for k in ('communities', 'peopleReached', 'peopleTargeted', 'quantity', 'budget')])
    a.call('PUT', f'/CActivityLocation/{loc1["id"]}', body={'populationReached': 80})
    check('W4', 'a location changed: the totals follow (120 reached)',
          a.call('GET', f'/CActivity/{act["id"]}').get('peopleReached') == 120)
    fp = a.call('POST', '/CFocalPoint', body={'name': 'Fola Point', 'activityId': act['id'], 'emailAddress': 'f@example.org'})
    check('W4', "a focal point: its activity's teams", teams('CFocalPoint', fp) == {eq1, wash})

    # --- W5: an organisation not in the list ---------------------------------------------------
    activity(name='Hot meals', leadOrganisationId=org['other']['id'], leadOrganisationOther='Kingston Kitchen Collective')
    todo = a.call('GET', '/Task', {'maxSize': 20, 'select': 'name,assignedUserId,teamsIds', **where('cResponseId', resp['id'])})['list']
    add = [t for t in todo if t['name'] == 'Add to the organisations list: Kingston Kitchen Collective']
    check('W5', "an organisation typed in: a task for the response's lead to add it to the list",
          len(add) == 1 and add[0]['assignedUserId'] == user['staff-1'], [t['name'] for t in todo])
    named = [r['name'] for r in a.call('GET', '/CActivity', {'maxSize': 20, 'select': 'name', **where('responseId', resp['id'])})['list']]
    check('W5', 'the activity named after the organisation typed', 'Kingston Kitchen Collective · Hot meals' in named, named)

    # --- W6: what's refused ------------------------------------------------------------------
    check('W6', 'an activity that ends before it starts: refused',
          status(lambda: activity(startDate='2026-11-05', endDate='2026-11-01')) == 400)

    # --- W7: who sees what -------------------------------------------------------------------
    rid = resp['id']
    for who in ('cluster-lead', 'cluster-partner'):
        u = as_user(who)
        check('W7', f'{who} (ETC): the ETC activity only', names(u, 'CActivity', rid) == {'AMERICARES · Connectivity'},
              names(u, 'CActivity', rid))
        check('W7', f'{who}: a WASH location by id refused',
              status(lambda: u.call('GET', f'/CActivityLocation/{loc1["id"]}')) == 403)
    v = as_user('cluster-viewer')
    check('W7', "cluster-viewer (WASH): the WASH activities' locations, and not their focal points",
          len(names(v, 'CActivityLocation', rid)) == 2 and status(lambda: v.call('GET', f'/CFocalPoint/{fp["id"]}')) == 403,
          names(v, 'CActivityLocation', rid))
    check('W7', 'cluster-viewer: editing a location refused',
          status(lambda: v.call('PUT', f'/CActivityLocation/{loc1["id"]}', body={'quantity': 1})) == 403)
    s = as_user('staff-1')
    check('W7', "staff-1 (the response's team): every activity", len(names(s, 'CActivity', rid)) == 4, names(s, 'CActivity', rid))
    p = as_user('cluster-partner')
    # A partner can't read the response, so links the activity to their project (EspoCRM
    # checks a link's record can be read); the formula gives it the project's response
    mine = p.call('POST', '/CActivity', body={'name': 'Charging', 'projectId': p_etc['id'], 'sector': 'EMERGENCY_TELECOMS',
                                              'leadOrganisationId': org['ORG_AMERICARES']['id'], 'activityType': 'other',
                                              'status': 'PLANNED', 'startDate': '2026-11-06', 'teamsIds': [etc],
                                              'assignedUserId': user['cluster-partner']})  # as the UI sends it
    got = a.call('GET', f'/CActivity/{mine["id"]}')
    check('W7', "cluster-partner: reports an activity in their project, in its teams and response",
          set(got['teamsIds']) == {eq1, etc} and got.get('responseId') == rid, {k: got.get(k) for k in ('teamsIds', 'responseId')})
    check('W7', "cluster-partner: edits their own activity, not one they didn't make",
          status(lambda: p.call('PUT', f'/CActivity/{mine["id"]}', body={'comments': 'x'})) == 200
          and status(lambda: p.call('PUT', f'/CActivity/{act_etc["id"]}', body={'comments': 'x'})) == 403)

    # --- W9: data checks: flags on what looks wrong, never a refusal ------------------------------
    chk = lambda e, r: set(a.call('GET', f'/{e}/{r["id"]}').get('dataChecks') or [])  # noqa: E731
    check('W9', 'a sound location: no flags', chk('CActivityLocation', loc1) == set(), chk('CActivityLocation', loc1))
    odd = location(act, community[0], populationTargeted=10, populationReached=50, populationGroups=['idp', 'hosting'],
                   idpPeopleReached=40, idpWomenReached=10, idpMenReached=10, idpChildrenReached=10, hostingPeopleReached=30)
    check('W9', 'more reached than targeted, groups over the total, a group whose parts don\'t add up: all three flagged, kept',
          chk('CActivityLocation', odd) == {'reached_over_targeted', 'groups_over_total', 'group_parts_dont_add_up'},
          chk('CActivityLocation', odd))
    a.call('PUT', f'/CActivityLocation/{odd["id"]}', body={'populationTargeted': 80, 'populationReached': 70,
                                                          'idpPeopleReached': 30, 'hostingPeopleReached': 30})
    check('W9', 'fixed: the flags go', chk('CActivityLocation', odd) == set(), chk('CActivityLocation', odd))
    empty = activity(name='Not yet anywhere', status='COMPLETED', startDate='2026-11-01', endDate='2099-01-01')
    check('W9', 'an activity with no community, completed but ending in the future: flagged',
          chk('CActivity', empty) == {'no_communities', 'completed_ends_later'}, chk('CActivity', empty))
    location(empty, community[1], populationTargeted=10)
    check('W9', 'a community with nobody reached: completed, nobody reached (and still ends later)',
          chk('CActivity', empty) == {'completed_nobody_reached', 'completed_ends_later'}, chk('CActivity', empty))

    # --- W8: reference lists: areas and organisations --------------------------------------------
    areas = a.call('GET', '/CAdminArea', {'maxSize': 1, **where('country', 'JAM')})['total']
    kingston = a.call('GET', '/CAdminArea', {'maxSize': 1, **where('pcode', 'JM17')})['list'][0]
    check('W8', "Jamaica's 14 parishes and 775 communities, Melissa's P-codes (JM17 Kingston)",
          areas == 789 and kingston['name'] == 'KINGSTON', (areas, kingston['name']))
    for who in ('cluster-viewer', 'cluster-partner'):
        u = as_user(who)
        orgs = u.call('GET', '/COrganisation', {'maxSize': 1})['total']
        parishes = u.call('GET', '/CAdminArea', {'maxSize': 1, **where('level', 'admin1')})['total']
        check('W8', f'{who}: reads the organisations (137) and the parishes', orgs == 137 and parishes >= 14, (orgs, parishes))
    check('W8', 'cluster-partner: editing an organisation refused',
          status(lambda: p.call('PUT', f'/COrganisation/{org["ORG_ADRA"]["id"]}', body={'name': 'x'})) == 403)


if __name__ == '__main__':
    main()
