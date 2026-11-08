#!/usr/bin/env python3
"""
P1-P9: cluster projects in a response (a cluster's work in it, e.g. Emergency
Telecommunications in Hurricane Melissa), and tasks on sites and cases.

    python3 -I tests/cases/projects.py

Makes its own fixtures (names starting "PRJ "), removing earlier ones first: a response in
team Response: Test EQ 1 with two projects, ETC (team Cluster: Test EQ 1 ETC: cluster-lead,
cluster-partner) and WASH (Cluster: Test EQ 1 WASH: cluster-viewer), a site and tasks in
each, a case. Then checks, as each test user with their own password, through the API (as
isolation.py: the UI's views call the same endpoints). staff-1, in the response's team,
stands for the response's coordinators. Writes tests/results/projects.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, BridgeError, admin, as_user  # noqa: E402

PREFIX = 'PRJ '
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


def names(espo, entity, **params):
    try:
        rows = espo.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name', **params})['list']
    except BridgeError as e:
        return e.status
    return {r['name'] for r in rows if r['name'].startswith(PREFIX)}


def starts(entity):
    return {'where[0][type]': 'startsWith', 'where[0][attribute]': 'name', 'where[0][value]': PREFIX}


def cleanup(a):
    for resp in a.call('GET', '/CResponse', {'maxSize': 200, 'select': 'name', **starts('CResponse')})['list']:
        for t in a.call('GET', '/Task', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'equals',
                                         'where[0][attribute]': 'cResponseId', 'where[0][value]': resp['id']})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')  # its starter tasks too
    for entity in ('Task', 'CSite', 'CProject', 'CResponse', 'Case'):
        for r in a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name', **starts(entity)})['list']:
            a.call('DELETE', f'/{entity}/{r["id"]}')


def teams_of(a, entity, rec):
    return set(a.call('GET', f'/{entity}/{rec["id"]}').get('teamsIds') or [])


def main():
    a = admin()
    cleanup(a)
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    eq1, etc, wash, ca = (team['Response: Test EQ 1'], team['Cluster: Test EQ 1 ETC'], team['Cluster: Test EQ 1 WASH'],
                          team['Project: Consortium A'])
    try:
        run(a, team, user, eq1, etc, wash, ca)
    finally:
        cleanup(a)
    path = ROOT / 'tests' / 'results' / 'projects.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'projects: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def run(a, team, user, eq1, etc, wash, ca):
    resp = a.call('POST', '/CResponse', body={'name': 'PRJ Hurricane', 'status': 'Active', 'teamsIds': [eq1],
                                              'leadId': user['staff-1']})
    p_etc = a.call('POST', '/CProject', body={'name': 'PRJ Hurricane ETC', 'cluster': 'Emergency Telecommunications',
                                              'status': 'Active', 'responseId': resp['id'], 'teamsIds': [etc],
                                              'leadId': user['cluster-lead']})
    p_wash = a.call('POST', '/CProject', body={'name': 'PRJ Hurricane WASH', 'cluster': 'WASH', 'status': 'Active',
                                               'responseId': resp['id'], 'teamsIds': [wash]})
    s_etc = a.call('POST', '/CSite', body={'name': 'PRJ VSAT hub', 'siteCode': 'PRJ-E1', 'projectId': p_etc['id']})
    s_wash = a.call('POST', '/CSite', body={'name': 'PRJ Water point', 'siteCode': 'PRJ-W1', 'projectId': p_wash['id']})
    t_etc = a.call('POST', '/Task', body={'name': 'PRJ ETC task of the lead', 'cProjectId': p_etc['id'], 'status': 'Backlog',
                                          'assignedUserId': user['cluster-lead']})
    t_wash = a.call('POST', '/Task', body={'name': 'PRJ WASH task', 'cProjectId': p_wash['id'], 'status': 'Backlog',
                                           'assignedUserId': user['staff-1']})

    # --- P1: teams follow the project, the project its response -------------------------------
    check('P1', "a project is in its own team and its response's", teams_of(a, 'CProject', p_etc) == {etc, eq1},
          teams_of(a, 'CProject', p_etc))
    site = a.call('GET', f'/CSite/{s_etc["id"]}')
    check('P1', "a project's site: the project's teams, and its response", set(site['teamsIds']) == {etc, eq1}
          and site.get('responseId') == resp['id'], site)
    task = a.call('GET', f'/Task/{t_etc["id"]}')
    check('P1', "a project's task: the project's teams, and its response", set(task['teamsIds']) == {etc, eq1}
          and task.get('cResponseId') == resp['id'], task)

    # --- P2: the response's coordinators see every project ------------------------------------
    s = as_user('staff-1')
    check('P2', 'staff-1 (response team): both projects', names(s, 'CProject') == {'PRJ Hurricane ETC', 'PRJ Hurricane WASH'},
          names(s, 'CProject'))
    check('P2', "staff-1: both projects' sites", names(s, 'CSite') == {'PRJ VSAT hub', 'PRJ Water point'}, names(s, 'CSite'))
    check('P2', "staff-1: both projects' tasks", {'PRJ ETC task of the lead', 'PRJ WASH task'} <= names(s, 'Task'),
          names(s, 'Task'))

    # --- P3: a project's people see only their project ----------------------------------------
    for who in ('cluster-lead', 'cluster-partner'):
        u = as_user(who)
        check('P3', f'{who}: projects = ETC only', names(u, 'CProject') == {'PRJ Hurricane ETC'}, names(u, 'CProject'))
        check('P3', f'{who}: sites = ETC only', names(u, 'CSite') == {'PRJ VSAT hub'}, names(u, 'CSite'))
        check('P3', f'{who}: tasks = ETC only', names(u, 'Task') == {'PRJ ETC task of the lead'}, names(u, 'Task'))
        check('P3', f'{who}: WASH site by id refused', status(lambda: u.call('GET', f'/CSite/{s_wash["id"]}')) == 403)
        check('P3', f'{who}: WASH task by id refused', status(lambda: u.call('GET', f'/Task/{t_wash["id"]}')) == 403)
        check('P3', f'{who}: the response itself refused (only its coordinators)',
              status(lambda: u.call('GET', f'/CResponse/{resp["id"]}')) == 403)
        kanban = u.call('GET', '/Kanban/Task', {'maxSize': 200})
        board = {r['name'] for g in kanban.get('groups', []) for r in g['list'] if r['name'].startswith(PREFIX)}
        check('P3', f'{who}: task board = ETC tasks only', board == {'PRJ ETC task of the lead'}, board)
    v = as_user('cluster-viewer')
    check('P3', 'cluster-viewer: projects, sites, tasks = WASH only',
          (names(v, 'CProject'), names(v, 'CSite'), names(v, 'Task'))
          == ({'PRJ Hurricane WASH'}, {'PRJ Water point'}, {'PRJ WASH task'}),
          [names(v, 'CProject'), names(v, 'CSite'), names(v, 'Task')])
    o = as_user('volunteer-1')  # Response 2 only
    check('P3', "volunteer-1 (another response): none of this response's projects, sites or tasks",
          all(names(o, e) in (403, set()) for e in ('CProject', 'CSite', 'Task')),  # (no access to projects at all: 403)
          [names(o, 'CProject'), names(o, 'CSite'), names(o, 'Task')])

    # --- P4: the viewer reads and comments, nothing else --------------------------------------
    check('P4', 'cluster-viewer: editing a site refused',
          status(lambda: v.call('PUT', f'/CSite/{s_wash["id"]}', body={'status': 'needs_repair'})) == 403)
    check('P4', 'cluster-viewer: making a task refused',
          status(lambda: v.call('POST', '/Task', body={'name': 'PRJ by viewer', 'cProjectId': p_wash['id'],
                                                     'assignedUserId': user['cluster-viewer']})) == 403)
    check('P4', 'cluster-viewer: making a site refused',
          status(lambda: v.call('POST', '/CSite', body={'name': 'PRJ by viewer', 'siteCode': 'PRJ-V',
                                                      'projectId': p_wash['id']})) == 403)
    note = status(lambda: v.call('POST', '/Note', body={'type': 'Post', 'parentType': 'CSite', 'parentId': s_wash['id'],
                                                       'post': 'PRJ the pump is leaking'}))
    check('P4', 'cluster-viewer: a note on a WASH site', note == 200, f'HTTP {note}')

    # --- P5: the partner registers sites, makes tasks on them ---------------------------------
    # As the UI sends them: with the person's default team (EspoCRM refuses a record with no
    # team from someone with "team" assignment); the formula adds the response's
    p = as_user('cluster-partner')
    made = p.call('POST', '/CSite', body={'name': 'PRJ Repeater', 'siteCode': 'PRJ-E2', 'projectId': p_etc['id'],
                                          'teamsIds': [etc]})
    check('P5', "cluster-partner: a new site in ETC takes the project's teams", teams_of(a, 'CSite', made) == {etc, eq1},
          teams_of(a, 'CSite', made))
    check('P5', 'cluster-partner: edits an ETC site',
          status(lambda: p.call('PUT', f'/CSite/{s_etc["id"]}', body={'status': 'operational'})) == 200)
    on_site = p.call('POST', '/Task', body={'name': 'PRJ Fix the generator', 'parentType': 'CSite', 'parentId': s_etc['id'],
                                            'assignedUserId': user['cluster-partner'], 'teamsIds': [etc]})
    got = a.call('GET', f'/Task/{on_site["id"]}')
    check('P5', "a task on a site: in the site's project, response and teams",
          got.get('cProjectId') == p_etc['id'] and got.get('cResponseId') == resp['id'] and set(got['teamsIds']) == {etc, eq1},
          {k: got.get(k) for k in ('cProjectId', 'cResponseId', 'teamsIds')})
    panel = {r['name'] for r in a.call('GET', f'/CSite/{s_etc["id"]}/tasks', {'select': 'name'})['list']}
    check('P5', "the site's Tasks panel lists it", 'PRJ Fix the generator' in panel, panel)
    check('P5', "cluster-partner: edits their own task, not the lead's",
          status(lambda: p.call('PUT', f'/Task/{on_site["id"]}', body={'status': 'Started'})) == 200
          and status(lambda: p.call('PUT', f'/Task/{t_etc["id"]}', body={'status': 'Started'})) == 403)
    check('P5', 'cluster-partner: a site in the WASH project refused',
          status(lambda: p.call('POST', '/CSite', body={'name': 'PRJ elsewhere', 'siteCode': 'PRJ-X',
                                                      'projectId': p_wash['id'], 'teamsIds': [etc]})) == 403)
    check('P5', 'cluster-partner: a task on a WASH site refused',
          status(lambda: p.call('POST', '/Task', body={'name': 'PRJ elsewhere', 'parentType': 'CSite',
                                                     'parentId': s_wash['id'],
                                                     'assignedUserId': user['cluster-partner'],
                                                     'teamsIds': [etc]})) == 403)

    # --- P6: the lead runs the project's tasks, inside its team -------------------------------
    lead = as_user('cluster-lead')
    check('P6', "cluster-lead: edits the partner's task",
          status(lambda: lead.call('PUT', f'/Task/{on_site["id"]}', body={'priority': 'High'})) == 200)
    check('P6', 'cluster-lead: gives an ETC task to the partner',
          status(lambda: lead.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['cluster-partner']})) == 200)
    # A coordinator sees every project's tasks, but EspoCRM lets people assign only those who
    # share a team with them: to hand out a project's work, they join its team
    who = status(lambda: s.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['cluster-lead']}))
    check('P6', "staff-1 (response team only): an ETC task to the ETC lead refused until they join the project's team",
          who == 403, f'HTTP {who}')
    for t in (etc, wash):
        a.call('POST', f'/Team/{t}/users', body={'id': user['staff-1']})
    try:
        s = as_user('staff-1')
        check('P6', "staff-1 in the ETC team: gives an ETC task to the ETC lead",
              status(lambda: s.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['cluster-lead']})) == 200)
        # In the WASH team too, EspoCRM would let them pick its viewer: the formula refuses
        who = status(lambda: s.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['cluster-viewer']}))
        check('P6', 'staff-1 in both teams: an ETC task to the WASH viewer refused (not in its teams)', who == 400,
              f'HTTP {who}')
        check('P6', "staff-1: an ETC task to roster-1 (response team) allowed: the response's people can take any project's work",
              status(lambda: s.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['roster-1']})) == 200)
        s.call('PUT', f'/Task/{t_etc["id"]}', body={'assignedUserId': user['cluster-partner']})
    finally:
        for t in (etc, wash):
            a.call('DELETE', f'/Team/{t}/users', body={'id': user['staff-1']})

    # --- P7: a task on a case ----------------------------------------------------------------
    case = a.call('POST', '/Case', body={'name': 'PRJ Case', 'teamsIds': [ca]})
    on_case = a.call('POST', '/Task', body={'name': 'PRJ Call back', 'parentType': 'Case', 'parentId': case['id'],
                                            'assignedUserId': user['triager']})
    check('P7', "a task on a case: the case's team", teams_of(a, 'Task', on_case) == {ca}, teams_of(a, 'Task', on_case))
    who = status(lambda: a.call('PUT', f'/Task/{on_case["id"]}', body={'assignedUserId': user['cluster-partner']}))
    check('P7', "a case's task to someone outside the case's team refused", who == 400, f'HTTP {who}')

    # --- P8: a team added to the project reaches its sites and tasks --------------------------
    extra = a.call('POST', '/Team', body={'name': 'PRJ partner organisation'})
    try:
        a.call('PUT', f'/CProject/{p_etc["id"]}', body={'teamsIds': [etc, eq1, extra['id']]})
        check('P8', "a team added to the project: on its sites and tasks",
              extra['id'] in teams_of(a, 'CSite', s_etc) and extra['id'] in teams_of(a, 'CSite', made)
              and extra['id'] in teams_of(a, 'Task', on_site),
              [teams_of(a, 'CSite', s_etc), teams_of(a, 'Task', on_site)])
        a.call('PUT', f'/CProject/{p_etc["id"]}', body={'teamsIds': [etc]})
        check('P8', "and taken off again; the response's team stays (the formula puts it back)",
              teams_of(a, 'CProject', p_etc) == {etc, eq1} and teams_of(a, 'Task', on_site) == {etc, eq1},
              [teams_of(a, 'CProject', p_etc), teams_of(a, 'Task', on_site)])
    finally:
        a.call('DELETE', f'/Team/{extra["id"]}')

    # --- P9: closing a project gives its tasks to its lead -------------------------------------
    a.call('PUT', f'/Task/{on_site["id"]}', body={'collaboratorsIds': [user['cluster-partner'], user['cluster-lead']]})
    a.call('PUT', f'/CProject/{p_etc["id"]}', body={'status': 'Closed'})
    back = a.call('GET', '/Task', {'select': 'name,assignedUserId,collaboratorsIds', 'maxSize': 200,
                                   'where[0][type]': 'equals', 'where[0][attribute]': 'cProjectId',
                                   'where[0][value]': p_etc['id']})['list']
    check('P9', "closing the project gave its tasks to its lead, with no other collaborators",
          back and all(t['assignedUserId'] == user['cluster-lead']
                       and set(t.get('collaboratorsIds') or []) <= {user['cluster-lead']} for t in back),
          [(t['name'], t['assignedUserId'], t.get('collaboratorsIds')) for t in back])


if __name__ == '__main__':
    main()
