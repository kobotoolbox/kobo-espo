#!/usr/bin/env python3
"""
T8-T11, T13, T15, T16: does access stay inside teams? (plan §11, "the key risk")

    python3 -I tests/cases/isolation.py

Makes its own fixtures (names starting "ISO "), removing earlier ones first: two responses
with tasks and sites, a case and a partner account per consortium, a standard. Then checks,
as each test user with their own password, through the API. The UI's list views, a record
opened by its URL, the Kanban board and global search call these same endpoints, so a
check here is the check for that view: a 403 or a missing row here is what the UI shows.

Changes team memberships for T13 and T16 and puts them back at the end (as espo/seed
defines them). Writes tests/results/isolation.json.
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, BridgeError, Espo, admin, as_user, secrets  # noqa: E402

PREFIX = 'ISO '
results = []


def check(test, name, ok, detail=''):
    detail = sorted(detail) if isinstance(detail, set) else detail
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def status(fn):
    """The HTTP status of a call (200 when it worked)."""
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


def search(espo, q):
    rows = espo.call('GET', '/GlobalSearch', {'q': q, 'maxSize': 50})['list']
    return {(r['_scope'], r['name']) for r in rows if r.get('name', '').startswith(PREFIX)}


def cleanup(a):
    for resp in a.call('GET', '/CResponse', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'startsWith',
                                            'where[0][attribute]': 'name', 'where[0][value]': PREFIX})['list']:
        for t in a.call('GET', '/Task', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'equals',
                                         'where[0][attribute]': 'cResponseId', 'where[0][value]': resp['id']})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')  # its starter tasks too
    for entity in ('Task', 'CSite', 'CResponse', 'Case', 'Contact', 'Account', 'CStandard'):
        rows = a.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name',
                                           'where[0][type]': 'startsWith', 'where[0][attribute]': 'name',
                                           'where[0][value]': PREFIX})['list']
        for r in rows:
            a.call('DELETE', f'/{entity}/{r["id"]}')


def main():
    a = admin()
    cleanup(a)
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    eq1, eq2 = team['Response: Test EQ 1'], team['Response: Test EQ 2']
    ca, cb = team['Project: Consortium A'], team['Project: Consortium B']

    r1 = a.call('POST', '/CResponse', body={'name': 'ISO EQ 1', 'status': 'Active', 'teamsIds': [eq1],
                                            'leadId': user['staff-1']})
    r2 = a.call('POST', '/CResponse', body={'name': 'ISO EQ 2', 'status': 'Active', 'teamsIds': [eq2],
                                            'leadId': user['staff-1']})

    def task(name, resp, who):
        return a.call('POST', '/Task', body={'name': name, 'cResponseId': resp['id'], 'status': 'Backlog',
                                             'assignedUserId': user[who]})
    t_r1_roster1 = task('ISO R1 task of roster-1', r1, 'roster-1')
    t_r1_vol2 = task('ISO R1 task of volunteer-2', r1, 'volunteer-2')
    task('ISO R1 task of roster-2', r1, 'roster-2')
    t_r2_vol1 = task('ISO R2 task of volunteer-1', r2, 'volunteer-1')
    # A roster expert as a collaborator on someone else's task
    a.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'collaboratorsIds': [user['roster-1']]})
    s1 = a.call('POST', '/CSite', body={'name': 'ISO Site R1', 'siteCode': 'ISO-S1', 'responseId': r1['id'], 'teamsIds': [eq1]})
    s2 = a.call('POST', '/CSite', body={'name': 'ISO Site R2', 'siteCode': 'ISO-S2', 'responseId': r2['id'], 'teamsIds': [eq2]})
    acc_a = a.call('POST', '/Account', body={'name': 'ISO Partner A1', 'teamsIds': [ca]})
    acc_b = a.call('POST', '/Account', body={'name': 'ISO Partner B1', 'teamsIds': [cb]})
    a.call('POST', '/Contact', body={'firstName': 'ISO', 'lastName': 'Contact A1', 'accountId': acc_a['id'], 'teamsIds': [ca]})
    a.call('POST', '/Contact', body={'firstName': 'ISO', 'lastName': 'Contact B1', 'accountId': acc_b['id'], 'teamsIds': [cb]})
    case_a = a.call('POST', '/Case', body={'name': 'ISO Case A', 'teamsIds': [ca], 'accountId': acc_a['id']})
    case_b = a.call('POST', '/Case', body={'name': 'ISO Case B', 'teamsIds': [cb], 'accountId': acc_b['id']})
    a.call('POST', '/CStandard', body={'name': 'ISO Standard', 'code': 'ISO-1', 'category': 'WASH'})
    r1_tasks = {n for n in names(a, 'Task') if n.startswith('ISO R1')}
    r2_tasks = {n for n in names(a, 'Task') if n.startswith('ISO R2')}

    # --- T8: Response 1 only (roster-1, volunteer-2) ----------------------------------------
    for who in ('roster-1', 'volunteer-2'):
        u = as_user(who)
        check('T8', f'{who}: responses list = Response 1 only', names(u, 'CResponse') == {'ISO EQ 1'},
              names(u, 'CResponse'))
        check('T8', f'{who}: Response 2 by id (its URL) refused', status(lambda: u.call('GET', f'/CResponse/{r2["id"]}')) == 403)
        tasks = names(u, 'Task')
        check('T8', f'{who}: tasks list = Response 1 tasks only', tasks != 403 and tasks == r1_tasks, tasks)
        check('T8', f'{who}: Response 2 task by id refused', status(lambda: u.call('GET', f'/Task/{t_r2_vol1["id"]}')) == 403)
        kanban = u.call('GET', '/Kanban/Task', {'maxSize': 200})
        board = {r['name'] for g in kanban.get('groups', []) for r in g['list'] if r['name'].startswith(PREFIX)}
        check('T8', f'{who}: Kanban board = Response 1 tasks only', board == r1_tasks, board)
        check('T8', f'{who}: Response 2 sites hidden', names(u, 'CSite') == {'ISO Site R1'}, names(u, 'CSite'))
        check('T8', f'{who}: Site 2 by id refused', status(lambda: u.call('GET', f'/CSite/{s2["id"]}')) == 403)
        check('T8', f'{who}: cases refused (list)', names(u, 'Case') == 403, names(u, 'Case'))
        check('T8', f'{who}: case A by id refused', status(lambda: u.call('GET', f'/Case/{case_a["id"]}')) == 403)
        check('T8', f'{who}: accounts and contacts refused', names(u, 'Account') == 403 and names(u, 'Contact') == 403)
        found = search(u, 'ISO')
        check('T8', f'{who}: global search finds nothing of Response 2 or the consortia',
              not {n for _, n in found} & ({'ISO EQ 2', 'ISO Site R2', 'ISO Case A', 'ISO Case B',
                                             'ISO Partner A1', 'ISO Partner B1'} | r2_tasks), sorted(found))
        stream = u.call('GET', '/Stream', {'maxSize': 100}).get('list', [])
        leaked = [n for n in stream if n.get('parentId') in (r2['id'], t_r2_vol1['id'], s2['id'], case_a['id'], case_b['id'])]
        check('T8', f'{who}: own stream has nothing from Response 2 or cases', not leaked, len(leaked))
        check('T8', f'{who}: standards readable (they are for everyone)', names(u, 'CStandard') == {'ISO Standard'})

    # --- T9: both responses (roster-2) -------------------------------------------------------
    u = as_user('roster-2')
    check('T9', 'roster-2: responses = both', names(u, 'CResponse') == {'ISO EQ 1', 'ISO EQ 2'}, names(u, 'CResponse'))
    check('T9', 'roster-2: tasks = both responses\' tasks', names(u, 'Task') == r1_tasks | r2_tasks, names(u, 'Task'))
    check('T9', 'roster-2: sites = both', names(u, 'CSite') == {'ISO Site R1', 'ISO Site R2'})
    check('T9', 'roster-2: still no cases, accounts or contacts',
          names(u, 'Case') == 403 and names(u, 'Account') == 403 and names(u, 'Contact') == 403)
    found = search(u, 'ISO')
    check('T9', 'roster-2: global search = both responses, their tasks and sites, the standard, nothing else',
          {n for _, n in found} <= {'ISO EQ 1', 'ISO EQ 2', 'ISO Site R1', 'ISO Site R2', 'ISO Standard'} | r1_tasks | r2_tasks,
          sorted(found))

    # --- T10: volunteer-2 (Response 1) -------------------------------------------------------
    v = as_user('volunteer-2')
    users_seen = {x['userName'] for x in v.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    eq1_members = {'staff-1', 'roster-1', 'roster-2', 'volunteer-2'}
    check('T10', 'volunteer-2: user list = Response 1 members only', users_seen <= eq1_members, sorted(users_seen))
    check('T10', 'volunteer-2: a user outside the team by id refused',
          status(lambda: v.call('GET', f'/User/{user["volunteer-1"]}')) == 403)
    check('T10', 'volunteer-2: assigning own task to someone outside the team refused',
          status(lambda: v.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'assignedUserId': user['volunteer-1']})) == 403)
    check('T10', 'volunteer-2: reassigning own task within the team refused too (Volunteer: no assignment)',
          status(lambda: v.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'assignedUserId': user['roster-1']})) == 403)
    check('T10', "volunteer-2: editing someone else's task refused",
          status(lambda: v.call('PUT', f'/Task/{t_r1_roster1["id"]}', body={'name': 'ISO hacked'})) == 403)
    check('T10', 'volunteer-2: creating a task refused', status(lambda: v.call('POST', '/Task', body={
        'name': 'ISO by volunteer', 'cResponseId': r1['id'], 'assignedUserId': user['volunteer-2']})) == 403)
    r = as_user('roster-1')
    check('T10', 'roster-1: assigning own task to someone outside the team refused',
          status(lambda: r.call('PUT', f'/Task/{t_r1_roster1["id"]}', body={'assignedUserId': user['volunteer-1']})) == 403)
    check('T10', 'roster-1: assigning own task within the team allowed',
          status(lambda: r.call('PUT', f'/Task/{t_r1_roster1["id"]}', body={'assignedUserId': user['roster-2']})) == 200)
    a.call('PUT', f'/Task/{t_r1_roster1["id"]}', body={'assignedUserId': user['roster-1']})
    check('T10', 'roster-1: a task in Response 2 can\'t be created by putting it under Response 2',
          status(lambda: r.call('POST', '/Task', body={'name': 'ISO sneaky', 'cResponseId': r2['id'],
                                                       'assignedUserId': user['roster-1']})) in (400, 403))

    # --- T11: partner staff --------------------------------------------------------------------
    for who, mine, theirs, acc_mine, acc_theirs in (('partner-a', 'ISO Case A', case_b, 'ISO Partner A1', acc_b),
                                                    ('partner-b', 'ISO Case B', case_a, 'ISO Partner B1', acc_a)):
        p = as_user(who)
        check('T11', f'{who}: cases = own consortium only', names(p, 'Case') == {mine}, names(p, 'Case'))
        check('T11', f'{who}: the other consortium\'s case by id refused', status(lambda: p.call('GET', f'/Case/{theirs["id"]}')) == 403)
        check('T11', f'{who}: accounts = own partner only', names(p, 'Account') == {acc_mine}, names(p, 'Account'))
        check('T11', f'{who}: the other partner account by id refused', status(lambda: p.call('GET', f'/Account/{acc_theirs["id"]}')) == 403)
        check('T11', f'{who}: contacts = own consortium only', names(p, 'Contact') == {f'ISO Contact {mine[-1]}1'},
              names(p, 'Contact'))
        check('T11', f'{who}: responses and tasks refused', names(p, 'CResponse') == 403 and names(p, 'Task') == 403)
        check('T11', f'{who}: moving a case into the other consortium refused',
              status(lambda: p.call('PUT', f'/Case/{(case_a if who == "partner-a" else case_b)["id"]}',
                                    body={'teamsIds': [cb if who == 'partner-a' else ca]})) == 403)
    t = as_user('triager')
    check('T11', 'triager (in both consortia): sees both cases', names(t, 'Case') == {'ISO Case A', 'ISO Case B'})

    # --- T15: Kanban moves ---------------------------------------------------------------------
    r = as_user('roster-1')
    check('T15', 'roster-1 moves own task Backlog -> In progress', status(lambda: r.call(
        'PUT', f'/Task/{t_r1_roster1["id"]}', body={'status': 'Started'})) == 200)
    # EspoCRM 10: a collaborator has the record shared with them, i.e. read and stream
    # (comments), not edit (Core/Acl/DefaultOwnershipChecker::checkShared)
    check('T15', "roster-1 as collaborator reads and comments on volunteer-2's task",
          status(lambda: r.call('GET', f'/Task/{t_r1_vol2["id"]}')) == 200 and status(lambda: r.call(
              'POST', '/Note', body={'type': 'Post', 'parentType': 'Task', 'parentId': t_r1_vol2['id'],
                                     'post': 'ISO collaborator comment'})) == 200)
    check('T15', "roster-1 as collaborator can't move volunteer-2's task (EspoCRM 10: shared = read only)",
          status(lambda: r.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'status': 'Started'})) == 403)
    outsider = as_user('volunteer-1')  # Response 2 only
    a.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'collaboratorsIds': [user['roster-1'], user['volunteer-1']]})
    check('T15', 'a collaborator from outside the response can read that one task (sharing crosses teams)',
          status(lambda: outsider.call('GET', f'/Task/{t_r1_vol2["id"]}')) == 200
          and status(lambda: outsider.call('GET', f'/CResponse/{r1["id"]}')) == 403,
          'by design: adding a collaborator shares the task, not its response')
    a.call('PUT', f'/Task/{t_r1_vol2["id"]}', body={'collaboratorsIds': [user['roster-1']]})
    v = as_user('volunteer-2')
    check('T15', 'volunteer-2 moves own task', status(lambda: v.call(
        'PUT', f'/Task/{t_r1_vol2["id"]}', body={'status': 'Started'})) == 200)
    check('T15', "volunteer-2 moves roster-1's task: refused", status(lambda: v.call(
        'PUT', f'/Task/{t_r1_roster1["id"]}', body={'status': 'Completed'})) == 403)
    check('T15', 'volunteer-2 can comment on a task of the response (stream: team)', status(lambda: v.call(
        'POST', '/Note', body={'type': 'Post', 'parentType': 'Task', 'parentId': t_r1_roster1['id'],
                               'post': 'ISO comment'})) == 200)

    try:
        membership_tests(a, user, eq1, r1, r1_tasks, t_r1_roster1)
    finally:  # memberships back as espo/seed defines them, whatever happened
        for who in ('roster-1', 'roster-2', 'volunteer-2'):
            a.call('POST', f'/Team/{eq1}/users', body={'id': user[who]})

    out = ROOT / 'tests' / 'results' / 'isolation.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'when': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'espo': URL,
                               'passed': sum(r['ok'] for r in results), 'failed': sum(not r['ok'] for r in results),
                               'results': results}, indent=2) + '\n')
    print(f'\n{sum(r["ok"] for r in results)}/{len(results)} passed; {out.relative_to(ROOT)}')
    sys.exit(0 if all(r['ok'] for r in results) else 1)


def membership_tests(a, user, eq1, r1, r1_tasks, t_r1_roster1):
    # --- T13: removing a user from a team revokes access at once -------------------------------
    # With a session token, as the browser has it, made before the change
    pw = secrets('seed')['PASSWORD_ROSTER_1']
    login = Espo(URL, basic='-:-')
    login.headers = {'Espo-Authorization': base64.b64encode(f'roster-1:{pw}'.encode()).decode(),
                     'Espo-Authorization-By-Token': 'false'}
    token = login.call('GET', '/App/user')['token']
    session = Espo(URL, basic='-:-')
    session.headers = {'Espo-Authorization': base64.b64encode(f'roster-1:{token}'.encode()).decode(),
                       'Espo-Authorization-By-Token': 'true'}
    check('T13', 'roster-1 (session) reads Response 1 before', status(lambda: session.call('GET', f'/CResponse/{r1["id"]}')) == 200)
    a.call('DELETE', f'/Team/{eq1}/users', body={'id': user['roster-1']})
    check('T13', 'roster-1 (same session) refused Response 1 right after leaving the team',
          status(lambda: session.call('GET', f'/CResponse/{r1["id"]}')) == 403)
    left = names(session, 'Task')
    left = set() if left == 403 else left
    others = r1_tasks - {'ISO R1 task of roster-1', 'ISO R1 task of volunteer-2'}  # not theirs, not collaborating
    check('T13', "roster-1 (same session): others' Response 1 tasks gone from the list", not (left & others), left)
    # Recorded, not judged: "own" (assignee, collaborator) access doesn't depend on teams
    own = status(lambda: session.call('GET', f'/Task/{t_r1_roster1["id"]}'))
    check('T13', 'roster-1 (same session): their own task after leaving (recorded)', True,
          f'HTTP {own}; 200 means still readable as its assignee: reassign tasks when someone leaves')
    a.call('POST', f'/Team/{eq1}/users', body={'id': user['roster-1']})

    # --- T16: closing a response and removing its members --------------------------------------
    a.call('PUT', f'/CResponse/{r1["id"]}', body={'status': 'Closed'})
    for who in ('roster-1', 'roster-2', 'volunteer-2'):
        a.call('DELETE', f'/Team/{eq1}/users', body={'id': user[who]})
    for who in ('roster-1', 'roster-2', 'volunteer-2'):
        u = as_user(who)
        check('T16', f'{who}: closed Response 1 refused after removal', status(lambda: u.call('GET', f'/CResponse/{r1["id"]}')) == 403)
        left = names(u, 'Task')
        # Closing gave their tasks back to the lead (CResponse formula): none left, not even their own
        check('T16', f'{who}: no Response 1 tasks listed after closing and removal, not even their own',
              left == 403 or not (left & r1_tasks), left)
        check('T16', f'{who}: their former task by id refused',
              status(lambda: u.call('GET', f'/Task/{t_r1_roster1["id"]}')) == 403)
    s = as_user('staff-1')
    back = a.call('GET', '/Task', {'select': 'name,assignedUserId,collaboratorsIds', 'maxSize': 200,
                                   'where[0][type]': 'equals', 'where[0][attribute]': 'cResponseId', 'where[0][value]': r1['id']})['list']
    # The lead is then their only collaborator (EspoCRM adds the assignee)
    lead_only = lambda t: set(t.get('collaboratorsIds') or []) <= {user['staff-1']}  # noqa: E731
    check('T16', 'closing gave every Response 1 task to the lead, with no other collaborators',
          all(t['assignedUserId'] == user['staff-1'] and lead_only(t) for t in back),
          [t['name'] for t in back if t['assignedUserId'] != user['staff-1'] or not lead_only(t)])
    check('T16', 'staff-1 (still in the team) reads the closed response and its tasks',
          status(lambda: s.call('GET', f'/CResponse/{r1["id"]}')) == 200 and r1_tasks <= names(s, 'Task'))


if __name__ == '__main__':
    main()
