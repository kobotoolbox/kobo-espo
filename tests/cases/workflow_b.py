#!/usr/bin/env python3
"""
T14: a new Response gets its starter tasks, and the Kanban board filtered by that response
shows them, in their columns, to its members.

    python3 -I tests/cases/workflow_b.py

Makes "WFB Response <time>" in Test EQ 2's team (removed first if an earlier run left one),
as staff-1. Writes tests/results/workflow_b.json.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, BridgeError, admin, as_user  # noqa: E402

STARTER = {'Set up the Kobo project', 'Confirm the roster', 'Comms plan', 'Agree site list and standards'}
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=sorted))  # sets, also inside dicts
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def board(espo, response_id):
    """The Kanban board of tasks, filtered by the response, as the UI asks for it."""
    k = espo.call('GET', '/Kanban/Task', {'maxSize': 50, 'where[0][type]': 'equals',
                                          'where[0][attribute]': 'cResponseId', 'where[0][value]': response_id})
    return {g['name']: {r['name'] for r in g['list']} for g in k['groups']}


def main():
    a = admin()
    for old in a.call('GET', '/CResponse', {'select': 'name', 'where[0][type]': 'startsWith',
                                            'where[0][attribute]': 'name', 'where[0][value]': 'WFB '})['list']:
        for t in a.call('GET', '/Task', {'select': 'name', 'maxSize': 50, 'where[0][type]': 'equals',
                                         'where[0][attribute]': 'cResponseId', 'where[0][value]': old['id']})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')
        a.call('DELETE', f'/CResponse/{old["id"]}')
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    user = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    staff = as_user('staff-1')

    resp = staff.call('POST', '/CResponse', body={
        'name': f'WFB Response {time.strftime("%H%M%S")}', 'status': 'Planning', 'emergencyType': 'Flood',
        'country': 'Testland', 'teamsIds': [team['Response: Test EQ 2']], 'leadId': user['staff-1'],
        'assignedUserId': user['staff-1']})
    tasks = a.call('GET', '/Task', {'select': 'name,status,teamsIds,assignedUserId', 'maxSize': 50,
                                    'where[0][type]': 'equals', 'where[0][attribute]': 'cResponseId',
                                    'where[0][value]': resp['id']})['list']
    check('T14', 'staff-1 creates a response: its 4 starter tasks appear', {t['name'] for t in tasks} == STARTER,
          {t['name'] for t in tasks})
    check('T14', 'in the response\'s team, assigned to its lead, in Backlog',
          all(t['teamsIds'] == [team['Response: Test EQ 2']] and t['assignedUserId'] == user['staff-1']
              and t['status'] == 'Backlog' for t in tasks))
    cols = board(staff, resp['id'])
    check('T14', 'board columns are Backlog, To do, In progress, Blocked, Done (Canceled, Deferred hidden)',
          list(cols) == ['Backlog', 'Not Started', 'Started', 'Blocked', 'Completed'], list(cols))
    check('T14', 'the board, filtered by the response, has the starter tasks in Backlog',
          cols.get('Backlog') == STARTER, cols)
    # Give one to a volunteer of the response, who moves it along
    roster = next(t for t in tasks if t['name'] == 'Confirm the roster')
    staff.call('PUT', f'/Task/{roster["id"]}', body={'assignedUserId': user['volunteer-1']})
    v = as_user('volunteer-1')
    for st in ('Not Started', 'Started'):
        v.call('PUT', f'/Task/{roster["id"]}', body={'status': st})
    cols = board(v, resp['id'])
    check('T14', 'volunteer-1 moved their task to In progress; the board shows it there',
          'Confirm the roster' in cols.get('Started', set()) and 'Confirm the roster' not in cols.get('Backlog', set()), cols)
    check('T14', "volunteer-1 sees the response's whole board (team read), not other responses'",
          set().union(*cols.values()) == STARTER)
    try:
        other = board(as_user('volunteer-2'), resp['id'])
        check('T14', 'volunteer-2 (Response 1 only): this board is empty for them', not any(other.values()), other)
    except BridgeError as e:
        check('T14', 'volunteer-2 (Response 1 only): this board is refused', e.status == 403)
    labels = a.call('GET', '/I18n').get('Task', {}).get('options', {}).get('status', {})
    check('T14', 'columns read To do / In progress / Done', (labels.get('Not Started'), labels.get('Started'),
                                                             labels.get('Completed')) == ('To do', 'In progress', 'Done'), labels)

    out = ROOT / 'tests' / 'results' / 'workflow_b.json'
    out.write_text(json.dumps({'when': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'espo': URL,
                               'passed': sum(r['ok'] for r in results), 'failed': sum(not r['ok'] for r in results),
                               'results': results}, indent=2) + '\n')
    print(f'\n{sum(r["ok"] for r in results)}/{len(results)} passed; {out.relative_to(ROOT)}')
    sys.exit(0 if all(r['ok'] for r in results) else 1)


if __name__ == '__main__':
    main()
