#!/usr/bin/env python3
"""
Agents (plans/espo-agents-plan.md §11): the MVP's flow, triage and guard tests, with the
fake model, against the test droplet.

    python3 -I tests/cases/agents.py

Makes "Test: ..." copies of the example agents (the packs', workflows/*/agents.json) for the tests'
runner (runner = tests, mode active), gives them users (agents/sync.py), and runs the
runner in this process with the fake model (agents/llm.py Fake). The records it makes are
named "AGT ..." and removed first if an earlier run left them. Writes
tests/results/agents.json.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'espo' / 'seed'))
sys.path.insert(0, str(HERE.parent / 'agents'))
from lib import ROOT, URL, BridgeError, Espo, admin  # noqa: E402
import llm  # noqa: E402
import seed  # noqa: E402
from runner import Runner, key_name, where  # noqa: E402

SECRETS = ROOT / 'secrets' / 'agents.secrets'
TEST_SITE = 'https://agents.test.invalid'  # marks the test's accounts
# Not the example agents' teams (Response: Test EQ 1, Grants review); staff-1 leads, staff-2 reviews
TEST_TEAMS = {'CSite': 'Response: Test EQ 2', 'CApplication': 'Internal Kobo', 'CResponder': 'Response: Test EQ 2',
              'CPresence': 'Internal Kobo', 'CCsoUpdate': 'Internal Kobo'}  # (the CSO examples work in the CSO teams)
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def refused(fn):
    try:
        fn()
        return False
    except BridgeError as e:
        return e.status in (400, 403)


def named(a, entity, prefix):
    return a.call('GET', f'/{entity}', {**where(('startsWith', 'name', prefix)), 'maxSize': 200, 'select': 'id,name'})['list']


def clean(a):
    for agent in named(a, 'CAgent', 'Test: '):
        for entity in ('CAgentRoute', 'CAgentRun'):
            for row in a.call('GET', f'/{entity}', {**where(('equals', 'agentId', agent['id'])), 'maxSize': 200,
                                                    'select': 'id'})['list']:
                a.call('DELETE', f'/{entity}/{row["id"]}')
        a.call('DELETE', f'/CAgent/{agent["id"]}')
    for resp in named(a, 'CResponse', 'AGT '):
        for t in a.call('GET', '/Task', {**where(('equals', 'cResponseId', resp['id'])), 'maxSize': 200,
                                         'select': 'id'})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')
    for entity in ('CSite', 'CResponder', 'CResponse', 'CApplication'):
        for row in named(a, entity, 'AGT '):
            a.call('DELETE', f'/{entity}/{row["id"]}')
    for row in a.call('GET', '/Account', {**where(('equals', 'website', TEST_SITE)), 'maxSize': 200, 'select': 'id'})['list']:
        a.call('DELETE', f'/Account/{row["id"]}')


def test_agents(a, teams):
    """The example agents, as "Test: " copies for this runner, active, in teams the examples
    don't work in (TEST_TEAMS): the examples, running on the droplet, never see the test's records."""
    specs = seed.spec()['agents']
    made = {}
    for spec in specs:
        spec = {**spec, 'name': 'Test: ' + spec['name'], 'runner': 'tests', 'mode': 'active',
                'teams': [TEST_TEAMS[spec['entity']]]}
        spec['routes'] = [{**r, **({'assignAgent': 'Test: ' + r['assignAgent']} if r.get('assignAgent') else {})}
                          for r in spec['routes']]
        made[spec['name'][6:]] = seed.make_agent(a, spec, teams)
    return made


def runs(a, agent_id, record_id):
    return a.call('GET', '/CAgentRun', {**where(('equals', 'agentId', agent_id), ('equals', 'recordId', record_id)),
                                        'maxSize': 50, 'orderBy': 'createdAt', 'order': 'asc'})['list']


def tasks(a, response_id):
    return a.call('GET', '/Task', {**where(('equals', 'cResponseId', response_id)), 'maxSize': 50,
                                   'select': 'id,name,status,priority,assignedUserId'})['list']


def notes(a, entity, record_id, by):
    """The posts on a record by one agent's user, newest first."""
    return [n for n in a.call('GET', f'/{entity}/{record_id}/stream', {'maxSize': 30})['list']
            if n.get('type') == 'Post' and n.get('createdById') == by]


def visit(a, site, status, text):
    a.call('PUT', f'/CSite/{site["id"]}', body={'status': status, 'lastVisit': time.strftime('%Y-%m-%d')})
    a.call('POST', '/Note', body={'type': 'Post', 'parentType': 'CSite', 'parentId': site['id'],
                                  'post': f'**Site visit**\nBy: AGT tester\nCondition: {status}\nNotes: {text}'})
    time.sleep(1.1)  # EspoCRM's times are to the second


def main():
    a = admin()
    clean(a)
    teams = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    users = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
    agents = test_agents(a, teams)
    time.sleep(1.1)
    subprocess.run([sys.executable, '-I', str(ROOT / 'agents' / 'sync.py'), '--secrets', str(SECRETS)],
                   check=True, stdout=subprocess.DEVNULL)
    agents = {k: a.call('GET', f'/CAgent/{v["id"]}') for k, v in agents.items()}
    runner = Runner(URL, str(SECRETS), 'tests', 'fake')
    keys = runner.keys()
    as_agent = {k: Espo(URL, api_key=keys[key_name(v['userName'])]) for k, v in agents.items()}
    check('G1', 'each test agent has its own API user', all(v.get('userId') for v in agents.values()),
          {k: v.get('userName') for k, v in agents.items()})

    # --- Triage (Workflow E) ---------------------------------------------------------------
    tri = agents['Site visit triage']
    resp = a.call('POST', '/CResponse', body={'name': f'AGT Response {time.strftime("%H%M%S")}', 'status': 'Active',
                                              'teamsIds': [teams[TEST_TEAMS['CSite']]], 'leadId': users['staff-1']})
    for t in tasks(a, resp['id']):  # its starter tasks: not what these tests count
        a.call('DELETE', f'/Task/{t["id"]}')
    site = a.call('POST', '/CSite', body={'name': 'AGT Site well 1', 'siteCode': f'AGT-{time.strftime("%H%M%S")}',
                                          'siteType': 'water_point', 'status': 'operational', 'responseId': resp['id']})
    time.sleep(1.1)

    visit(a, site, 'needs_repair', 'Pump handle broken, people use the other well. FAKE_ROUTE=repair')
    calls = llm.Fake.calls
    runner.once()
    ts = tasks(a, resp['id'])
    r = runs(a, tri['id'], site['id'])
    check('E1', 'needs_repair: a Repair task on the response board, for its lead',
          [(t['name'], t['assignedUserId'] == users['staff-1']) for t in ts] == [('Repair: AGT Site well 1', True)], ts)
    check('E1', 'the model read the visit (needs_repair alone doesn\'t decide: the notes may say more)',
          len(r) == 1 and r[0]['routeBy'] == 'model' and llm.Fake.calls == calls + 1, r)

    visit(a, site, 'operational', 'Water looks fine but two children got sick after drinking from it. FAKE_ROUTE=ok')
    runner.once()
    ts = tasks(a, resp['id'])
    urgent = [t for t in ts if t['name'].startswith('Urgent:')]
    r = runs(a, tri['id'], site['id'])
    check('E2', 'the model chose ok, the after rule forced urgent_safety',
          len(r) == 2 and r[1]['route'] == 'urgent_safety' and r[1]['routeBy'] == 'rule_after', r[-1:])
    check('E2', 'an Urgent task for the response lead',
          len(urgent) == 1 and urgent[0]['priority'] == 'Urgent' and urgent[0]['assignedUserId'] == users['staff-1'], ts)
    posts = notes(a, 'CSite', site['id'], tri['userId'])
    check('E2', 'the fixed note, mentioning the lead', 'may describe a risk to people' in (posts[0].get('post') or '')
          and '@staff-1' in posts[0].get('post', ''), posts[0].get('post'))

    visit(a, site, 'operational', 'Routine visit, cleaned the apron, all fine.')
    runner.once()
    r = runs(a, tri['id'], site['id'])
    check('E3', 'a routine visit: ok, no task, the run gives the reason',
          len(r) == 3 and r[2]['route'] == 'ok' and r[2]['routeBy'] == 'model' and r[2].get('reason')
          and len(tasks(a, resp['id'])) == 2, r[-1:])
    runner.once()
    check('E4', 'the same visit again: no new run, no new task',
          len(runs(a, tri['id'], site['id'])) == 3 and len(tasks(a, resp['id'])) == 2)

    a.call('PUT', f'/CAgent/{tri["id"]}', body={'mode': 'dry_run'})
    visit(a, site, 'needs_repair', 'Solar pump stopped again.')
    runner.once()
    r = runs(a, tri['id'], site['id'])
    posts = notes(a, 'CSite', site['id'], tri['userId'])
    check('G3', 'dry run: a run and a note saying what it would do, no task',
          r[-1]['status'] == 'dry_run' and 'dry run' in (posts[0].get('post') or '') and len(tasks(a, resp['id'])) == 2,
          {'run': r[-1:], 'note': posts[0].get('post')})
    a.call('PUT', f'/CAgent/{tri["id"]}', body={'mode': 'active'})

    v0 = a.call('GET', f'/CAgent/{tri["id"]}')['version']
    a.call('PUT', f'/CAgent/{tri["id"]}', body={'instructions': a.call('GET', f'/CAgent/{tri["id"]}')['instructions']
                                                 + '\nA leaking tap is a repair, not urgent.'})
    v1 = a.call('GET', f'/CAgent/{tri["id"]}')['version']
    visit(a, site, 'operational', 'The tap is leaking a little. FAKE_ROUTE=repair')
    runner.once()
    r = runs(a, tri['id'], site['id'])
    check('G2', 'changing the instructions raises the version; the next run has it, at once',
          v1 == v0 + 1 and r[-1]['agentVersion'] == v1 and r[-1]['route'] == 'repair', {'v0': v0, 'v1': v1, 'run': r[-1:]})
    route = a.call('GET', '/CAgentRoute', {**where(('equals', 'agentId', tri['id']), ('equals', 'name', 'ok'))})['list'][0]
    a.call('PUT', f'/CAgentRoute/{route["id"]}', body={'description': 'A routine visit, nothing to do.'})
    check('G2', 'changing a route raises the version too', a.call('GET', f'/CAgent/{tri["id"]}')['version'] == v1 + 1)

    visit(a, site, 'needs_repair', 'The well cover is gone and children lean over the edge to look in. '
          'FAKE_ROUTE=urgent_safety')  # no word the safety rule knows: only the model can see it
    runner.once()
    r = runs(a, tri['id'], site['id'])
    urgent = [t for t in tasks(a, resp['id']) if t['name'].startswith('Urgent:')]
    check('E5', 'needs_repair, but a danger the safety rule\'s words miss: the model escalates it',
          r[-1]['route'] == 'urgent_safety' and r[-1]['routeBy'] == 'model' and len(urgent) == 2, r[-1:])

    # --- On a schedule: repair follow-up -------------------------------------------------
    fol = agents['Repair follow-up']
    resp2 = a.call('POST', '/CResponse', body={'name': f'AGT Response follow-up {time.strftime("%H%M%S")}',
                                               'status': 'Active', 'teamsIds': [teams[TEST_TEAMS['CSite']]],
                                               'leadId': users['staff-1']})
    for t in tasks(a, resp2['id']):
        a.call('DELETE', f'/Task/{t["id"]}')
    day = 86400
    ago = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 10 * day))
    today = time.strftime('%Y-%m-%d', time.gmtime())
    sites = {}
    for name, status, last in [('stale', 'needs_repair', ago), ('fresh', 'needs_repair', today), ('fine', 'operational', ago)]:
        sites[name] = a.call('POST', '/CSite', body={'name': f'AGT Site {name}', 'siteCode': f'AGT-F-{name}',
                                                     'siteType': 'water_point', 'status': status, 'lastVisit': last,
                                                     'responseId': resp2['id']})

    def follow_ups():
        return sorted(t['name'] for t in tasks(a, resp2['id']) if t['name'].startswith('Follow up repair'))

    runner.once()
    check('W1', 'on a schedule: nothing for a time before the agent was switched on', follow_ups() == [], follow_ups())
    now = time.time()
    runner.clock = lambda: now + 7 * day  # the next Monday 06:00 UTC has come round
    runner.once()
    r = runs(a, fol['id'], sites['stale']['id'])
    ts = [t for t in tasks(a, resp2['id']) if t['name'].startswith('Follow up repair')]
    check('W2', 'the next slot: a follow-up task for the response lead, only for the site needing a repair and '
          'not visited for 7 days', follow_ups() == [f'Follow up repair: AGT Site stale (last visit {ago})']
          and ts[0]['assignedUserId'] == users['staff-1'], ts)
    check('W2', 'taken by its rule (no model), keyed by the slot',
          len(r) == 1 and r[0]['routeBy'] == 'rule_before' and r[0]['triggerKey'].startswith('schedule:'), r)
    runner.once()
    check('W3', 'the same slot again: no new task', len(follow_ups()) == 1, follow_ups())
    runner.clock = lambda: now + 14 * day  # the Monday after
    runner.once()
    check('W4', 'a week later: again for the stale site, and now for the other one too (its visit is 14 days old)',
          follow_ups() == [f'Follow up repair: AGT Site fresh (last visit {today})']
          + [f'Follow up repair: AGT Site stale (last visit {ago})'] * 2, follow_ups())
    runner.clock = time.time

    # --- On a schedule: organisations that haven't reported (Workflow E) -------------------
    nr = agents['5W: no report']
    resp3 = a.call('POST', '/CResponse', body={'name': f'AGT Response 5W {time.strftime("%H%M%S")}', 'status': 'Active',
                                               'teamsIds': [teams[TEST_TEAMS['CResponder']]], 'leadId': users['staff-1']})
    for t in tasks(a, resp3['id']):
        a.call('DELETE', f'/Task/{t["id"]}')
    later = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 5 * day))  # recent, by the clock moved 8 days on
    orgs = {}
    for name, status, last in [('never', 'registered', None), ('stale', 'active', ago), ('fresh', 'active', later),
                               ('gone', 'inactive', ago)]:
        orgs[name] = a.call('POST', '/CResponder', body={'name': f'AGT Org {name}', 'status': status, 'lastReport': last,
                                                         'responseId': resp3['id'], 'clusters': ['WASH']})

    def chases():
        return sorted((t['name'], t['status']) for t in tasks(a, resp3['id']) if t['name'].startswith('No 5W report'))

    runner.clock = lambda: now + 8 * day
    runner.once()
    made = [t for t in tasks(a, resp3['id']) if t['name'].startswith('No 5W report')]
    check('N1', "a task for each organisation silent for a week: one that reported 10 days ago, and one that never "
          "did (registered over a week ago); not the one that reported recently, nor an inactive one",
          chases() == [('No 5W report from AGT Org never', 'Not Started'), ('No 5W report from AGT Org stale', 'Not Started')],
          chases())
    full = [a.call('GET', f'/Task/{t["id"]}') for t in made]
    check('N1', "for the response's lead, about the organisation (its Tasks panel)",
          all(t['assignedUserId'] == users['staff-1'] and t.get('parentType') == 'CResponder' for t in full)
          and {t['parentId'] for t in full} == {orgs['never']['id'], orgs['stale']['id']}, full)
    check('N2', 'the same morning again: nothing new', (runner.once(), len(chases()))[1] == 2, chases())
    runner.clock = lambda: now + 9 * day  # the next morning
    runner.once()
    stale_runs = runs(a, nr['id'], orgs['stale']['id'])
    check('N3', 'the next morning, their tasks still open: no second task, and the run done (not failed)',
          len(chases()) == 2 and [r['status'] for r in stale_runs] == ['done', 'done'],
          {'tasks': chases(), 'runs': [(r['status'], r.get('error')) for r in stale_runs]})
    said = notes(a, 'CResponder', orgs['stale']['id'], nr['userId'])
    check('N3', 'and its note says why, with a link to the open task',
          any('still open' in (n.get('post') or '') and '#Task/view/' in (n.get('post') or '') for n in said),
          [n.get('post') for n in said])
    stale_task = next(t for t in full if t['parentId'] == orgs['stale']['id'])
    a.call('PUT', f'/Task/{stale_task["id"]}', body={'status': 'Completed'})
    runner.clock = lambda: now + 10 * day
    runner.once()
    check('N4', 'its task done but still no report: a new one', chases().count(('No 5W report from AGT Org stale', 'Not Started')) == 1
          and len(chases()) == 3, chases())
    a.call('PUT', f'/CResponder/{orgs["never"]["id"]}', body={'lastReport': time.strftime('%Y-%m-%d', time.gmtime(now + 10 * day))})
    runner.clock = lambda: now + 11 * day
    runner.once()
    runs_never = runs(a, nr['id'], orgs['never']['id'])
    check('N5', 'it reports: no more runs for it', len(runs_never) == 3, [r['triggerKey'] for r in runs_never])
    runner.clock = time.time

    # --- Due diligence (Workflow D) --------------------------------------------------------
    scr, res = agents['DD screening'], agents['DD research']

    def application(org, leaders='Jane Example', purpose='Water trucking for 3 villages.'):
        acc = a.call('POST', '/Account', body={'name': org, 'website': TEST_SITE})  # (the name is what's screened)
        return a.call('POST', '/CApplication', body={
            'name': f'AGT {org}', 'accountId': acc['id'], 'country': 'Testland', 'registrationNumber': 'T-123',
            'amountRequested': 25000, 'purpose': purpose, 'leadership': leaders, 'stage': 'Submitted',
            'teamsIds': [teams[TEST_TEAMS['CApplication']]], 'noticeVersion': 'test-1'})

    clean_app = application('Clear Water Partners', purpose='Water trucking. FAKE_ddRisk=medium FAKE_ddFlags=new_org')
    match_app = application('Crimson Horizon Relief Brigade')
    near_app = application('Clear Sky Trust', leaders='Quentin Vexly')
    broken_app = application('Broken Output Org', purpose='FAKE_INVALID')
    sloppy_app = application('Sloppy Output Org', purpose='FAKE_SLOPPY FAKE_ROUTE=review')
    check('D1', 'a new application goes to Screening', a.call('GET', f'/CApplication/{clean_app["id"]}')['stage'] == 'Screening')
    runner.once()
    runner.once()
    got = a.call('GET', f'/CApplication/{clean_app["id"]}')
    check('D2', 'a clean organisation: Screening → Research → Review, for the reviewer',
          got['stage'] == 'Review' and got['assignedUserId'] == users['staff-2'],
          {k: got.get(k) for k in ('stage', 'assignedUserName')})
    check('D2', 'screening and research filled in their fields',
          got['ddSanctions'] == 'clear' and got['ddRegistry'] == 'not_checked' and got['ddRisk'] == 'medium'
          and got['ddFlags'] == ['new_org'] and got['ddSummary'] == 'Fake ddSummary.',
          {k: got.get(k) for k in ('ddSanctions', 'ddRegistry', 'ddRisk', 'ddFlags', 'ddSummary')})
    rs, rr = runs(a, scr['id'], clean_app['id']), runs(a, res['id'], clean_app['id'])
    check('D2', 'one screening run (rules) and one research run (model), each with cost and time',
          len(rs) == 1 and rs[0]['route'] == 'clear' and len(rr) == 1 and rr[0]['routeBy'] == 'model'
          and rr[0]['cost'] is not None and rr[0]['durationS'] is not None, {'screening': rs, 'research': rr})
    posts = notes(a, 'CApplication', clean_app['id'], res['userId'])
    check('D2', 'the dossier note mentions the reviewer', any('@staff-2' in (p.get('post') or '') for p in posts),
          [p.get('post') for p in posts])

    got = a.call('GET', f'/CApplication/{match_app["id"]}')
    check('D3', 'a sanctions match: straight to Review, research skipped',
          got['stage'] == 'Review' and got['ddSanctions'] == 'match' and not runs(a, res['id'], match_app['id']),
          {k: got.get(k) for k in ('stage', 'ddSanctions', 'ddSanctionsDetail')})
    got = a.call('GET', f'/CApplication/{near_app["id"]}')
    check('D4', 'a near miss (a leader\'s name misspelt): possible match, to Review',
          got['stage'] == 'Review' and got['ddSanctions'] == 'possible_match',
          {k: got.get(k) for k in ('stage', 'ddSanctions', 'ddSanctionsDetail')})

    got = a.call('GET', f'/CApplication/{broken_app["id"]}')
    rr = runs(a, res['id'], broken_app['id'])
    check('D6', 'the model keeps failing: 3 attempts, then the failure route (Review)',
          got['stage'] == 'Review' and len(rr) == 1 and rr[0]['status'] == 'failed' and rr[0]['attempts'] == 3
          and rr[0]['routeBy'] == 'failure' and 'invalid output' in (rr[0].get('error') or ''), rr)
    rr = runs(a, res['id'], sloppy_app['id'])
    check('G8', 'sloppy output (wrong case, a list as text, an extra key) is fixed in code',
          len(rr) == 1 and rr[0]['status'] == 'done' and rr[0]['attempts'] == 1, rr)

    a.call('PUT', f'/CApplication/{clean_app["id"]}', body={'stage': 'Research', 'assignedUserId': res['userId']})
    time.sleep(1.1)
    runner.once()
    check('D5', 'sent back to Research by a person: the agent runs again',
          len(runs(a, res['id'], clean_app['id'])) == 2
          and a.call('GET', f'/CApplication/{clean_app["id"]}')['stage'] == 'Review')

    # --- Guards ----------------------------------------------------------------------------
    ag = as_agent['DD research']
    app_id = sloppy_app['id']
    a.call('PUT', f'/CApplication/{app_id}', body={'stage': 'Research', 'assignedUserId': res['userId']})
    put = lambda body: ag.call('PUT', f'/CApplication/{app_id}', body=body)  # noqa: E731
    check('S1', 'an agent can\'t move a record to a stage its routes don\'t go to (Approved)',
          refused(lambda: put({'stage': 'Approved'})))
    try:  # refused by the guard, or dropped by field-level security: either way, unchanged
        put({'teamsIds': [teams[TEST_TEAMS['CApplication']], teams['Grants review']]})
    except BridgeError:
        pass
    check('S1', 'an agent can\'t change a record\'s teams',
          a.call('GET', f'/CApplication/{app_id}')['teamsIds'] == [teams[TEST_TEAMS['CApplication']]])
    check('S1', 'an agent can\'t assign to someone its routes don\'t name',
          refused(lambda: put({'assignedUserId': users['triager']})))
    before = a.call('GET', f'/CApplication/{app_id}')
    try:
        put({'country': 'Elsewhere', 'ddSanctions': 'clear'})
    except BridgeError:
        pass
    after = a.call('GET', f'/CApplication/{app_id}')
    check('S1', 'an agent can\'t write fields it doesn\'t fill in (field-level security)',
          after['country'] == before['country'] and after['ddSanctions'] == before['ddSanctions'],
          {'country': after['country'], 'ddSanctions': after['ddSanctions']})
    a.call('PUT', f'/CAgent/{res["id"]}', body={'mode': 'off'})
    check('S1', 'an agent that is off can\'t change anything', refused(lambda: put({'ddSummary': 'x'})))
    a.call('PUT', f'/CAgent/{res["id"]}', body={'mode': 'dry_run'})
    check('S1', '... nor in dry run', refused(lambda: put({'ddSummary': 'x'})))
    a.call('PUT', f'/CAgent/{res["id"]}', body={'mode': 'active'})
    check('S1', 'in its own route, it can (stage Review, assignee staff-2)',
          not refused(lambda: put({'stage': 'Review', 'assignedUserId': users['staff-2']})))
    check('S3', 'agent users can\'t read Cases or other teams\' sites',
          refused(lambda: ag.call('GET', '/Case')) and refused(lambda: as_agent['Site visit triage'].call('GET', '/Case'))
          and refused(lambda: ag.call('GET', '/CSite', {'maxSize': 5})))

    path = ROOT / 'tests' / 'results' / 'agents.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'agents: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
