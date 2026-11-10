#!/usr/bin/env python3
"""
The EspoCRM MCP's tools for responses, cluster projects and people (kobo-espo-bridge
espo_mcp/tools.py): U1-U8, against the test droplet. A response set up as an agent would:
the response, a project, a person invited into it, team changes, and what's refused; and a
contact's portal login (U8, the CSO portal's).

    python3 -I tests/cases/mcp_people.py

Runs the tools as functions (as tests/cases/mcp.py; these don't call Kobo, so there's no
fake Kobo or bridge service). Names start "MCPP <run>"; removes what it made at the end.
Writes tests/results/mcp_people.json.
"""
import json
import secrets as random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, BridgeError, Espo, admin, secrets  # noqa: E402

from bridges import BRIDGE_DIR, by  # noqa: E402

sys.path.insert(0, str(BRIDGE_DIR))
from espo_mcp import tools  # noqa: E402
from espo_mcp.confirm import Refused  # noqa: E402

RUN = str(int(time.time()))[-6:]
RESPONSE = f'MCPP {RUN} Hurricane'
USER = f'mcpp-{RUN}'
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def refused(fn):
    try:
        fn()
        return None
    except Refused as e:
        return str(e)


def twice(fn, *args, **kwargs):
    """The two calls: (the first's answer, the second's)."""
    first = fn(*args, **kwargs)
    return first, fn(*args, **kwargs, confirm=first['confirm'])


def main():
    a = admin()
    work = Path(tempfile.mkdtemp(prefix='mcp-people-'))
    (work / 'token').write_text('unused')
    (work / 'bridge.secrets').write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
    inst = tools.Instance({'ESPO_URL': URL, 'BRIDGE_SECRETS': str(work / 'bridge.secrets'),
                           'KOBO_URL': 'http://127.0.0.1:9', 'KOBO_TOKEN_FILE': str(work / 'token')})
    try:
        run(a, inst)
    finally:
        cleanup(a)
    path = ROOT / 'tests' / 'results' / 'mcp_people.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'mcp_people: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def run(a, inst):
    # --- U1: the roles people can have ------------------------------------------------------
    roles = tools.list_roles(inst)['roles']
    check('U1', "list_roles: the cluster roles, not the bridge's or the agents'",
          {'Cluster Lead', 'Cluster Partner', 'Cluster Viewer', 'Internal Staff'} <= set(roles)
          and 'Agent runner' not in roles and not any(r.startswith('Kobo connection') for r in roles), roles)

    # --- U2: a response ---------------------------------------------------------------------
    first = tools.create_response(inst, RESPONSE, emergency_type='Cyclone', country='Jamaica', lead='staff-2')
    check('U2', 'create_response, first call: shows it, changes nothing',
          first.get('confirm_required') and not by(a, 'CResponse', 'name', RESPONSE)
          and not by(a, 'Team', 'name', f'Response: {RESPONSE}'), first)
    done = tools.create_response(inst, RESPONSE, emergency_type='Cyclone', country='Jamaica', lead='staff-2',
                                 confirm=first['confirm'])
    resp = (by(a, 'CResponse', 'name', RESPONSE) or [{}])[0]
    team = (by(a, 'Team', 'name', f'Response: {RESPONSE}') or [{}])[0]
    staff2 = by(a, 'User', 'userName', 'staff-2')[0]
    check('U2', 'with the token: the response, in its new team, its lead in that team',
          done.get('changed') and team.get('id') in (a.call('GET', f'/CResponse/{resp["id"]}').get('teamsIds') or [])
          and team['id'] in (a.call('GET', f'/User/{staff2["id"]}').get('teamsIds') or []), done)
    check('U2', 'the same response again: refused', refused(lambda: tools.create_response(inst, RESPONSE)))
    other = tools.create_response(inst, RESPONSE + ' 2')
    check('U2', "a token for one response doesn't make another",
          refused(lambda: tools.create_response(inst, RESPONSE + ' 3', confirm=other['confirm'])))

    # --- U3: a cluster project --------------------------------------------------------------
    check('U3', 'a cluster that isn\'t one: refused',
          refused(lambda: tools.create_project(inst, RESPONSE, 'ETC', cluster='Telecoms')))
    check('U3', 'an admin as lead: refused', refused(lambda: tools.create_project(inst, RESPONSE, 'ETC', lead='admin')))
    first, done = twice(tools.create_project, inst, RESPONSE, 'ETC', cluster='Emergency Telecommunications')
    name = f'{RESPONSE} · ETC'
    proj = (by(a, 'CProject', 'name', name) or [{}])[0]
    pteam = (by(a, 'Team', 'name', f'Cluster: {name}') or [{}])[0]
    check('U3', "create_project: in its own new team and the response's",
          done.get('changed') and set(a.call('GET', f'/CProject/{proj["id"]}')['teamsIds']) == {pteam.get('id'), team['id']},
          done)
    check('U3', "the cluster asked for by its label is stored as its code",
          a.call('GET', f'/CProject/{proj["id"]}').get('cluster') == 'EMERGENCY_TELECOMS')
    by_code = tools.create_project(inst, a.call('GET', f'/CResponse/{resp["id"]}')['code'], 'WASH', cluster='WASH')
    check('U3', "the response named by its short code (first call only)",
          by_code.get('would_create', {}).get('response') == RESPONSE, by_code)
    listed = next((r for r in tools.list_projects(inst)['responses'] if r['response'] == RESPONSE), {})
    check('U3', 'list_projects: the response with its project, and their codes',
          [p['project'] for p in listed.get('projects', [])] == [name] and listed.get('code', '').startswith('RSP-')
          and listed['projects'][0]['code'].startswith('PRJ-'), listed)

    # --- U4: a person -----------------------------------------------------------------------
    team_name = f'Cluster: {name}'
    # Resend's test inbox: accepts everything, never bounces (the droplet sends with Resend)
    email = f'delivered+{USER}@resend.dev'
    # EspoCRM emails through the active group account with SMTP whose address is the system's
    sender = a.call('GET', '/Settings').get('outboundEmailFromAddress')
    emailing = any(r.get('emailAddress') == sender and r.get('status') == 'Active' and r.get('useSmtp')
                   for r in a.call('GET', '/InboundEmail', {'select': 'emailAddress,status,useSmtp'})['list'])
    args = dict(username=USER, first_name='Amina', last_name='Test', email=email, role='Cluster Partner',
                teams=[team_name])
    check('U4', 'invite_user: a bad username refused', refused(lambda: tools.invite_user(inst, **{**args, 'username': 'Amina K'})))
    check('U4', "invite_user: an agent's role refused", refused(lambda: tools.invite_user(inst, **{**args, 'role': 'Agent runner'})))
    check('U4', 'invite_user: an unknown team refused', refused(lambda: tools.invite_user(inst, **{**args, 'teams': ['Nope']})))
    check('U4', 'invite_user: an existing username refused', refused(lambda: tools.invite_user(inst, **{**args, 'username': 'staff-1'})))
    first = tools.invite_user(inst, **args)
    check('U4', 'first call: says whether EspoCRM will email them (as its outgoing email is set up or not)',
          first.get('confirm_required') and (f'emails {email}' if emailing else "isn't set up") in first.get('email', ''),
          first)
    done = tools.invite_user(inst, **args, confirm=first['confirm'])
    u = (by(a, 'User', 'userName', USER) or [{}])[0]
    got = a.call('GET', f'/User/{u["id"]}') if u else {}
    check('U4', f'the person: regular, active, the role, the team (and default team), {"" if emailing else "not "}emailed',
          done.get('changed') and got.get('type') == 'regular' and got.get('isActive')
          and list((got.get('rolesNames') or {}).values()) == ['Cluster Partner'] and got.get('teamsIds') == [pteam['id']]
          and got.get('defaultTeamId') == pteam['id'] and done.get('emailed') is emailing, {**done, 'user': got.get('teamsIds')})
    keys = lambda d: {k.lower() for k in d} | {x for v in d.values() if isinstance(v, dict) for x in keys(v)}  # noqa: E731
    check('U4', 'no password field in either answer', not any('password' in k for k in keys(first) | keys(done)),
          keys(first) | keys(done))

    # --- U5: what they see (a password set by hand here: the emailed link isn't followed)
    password = random.token_urlsafe(14)
    a.call('PUT', f'/User/{u["id"]}', body={'password': password})
    site = a.call('POST', '/CSite', body={'name': f'MCPP {RUN} site', 'siteCode': f'MCPP-{RUN}', 'projectId': proj['id']})
    elsewhere = a.call('POST', '/CSite', body={'name': f'MCPP {RUN} other site', 'siteCode': f'MCPP-{RUN}-X',
                                               'responseId': resp['id']})
    me = Espo(URL, basic=f'{USER}:{password}')
    seen = {r['name'] for r in me.call('GET', '/CSite', {'maxSize': 200, 'select': 'name'})['list']
            if r['name'].startswith('MCPP')}
    check('U5', "the invited partner sees the project's site, not the response's own", seen == {site['name']}, seen)

    # --- U6: team changes -------------------------------------------------------------------
    check('U6', 'add_to_team: an admin refused', refused(lambda: tools.add_to_team(inst, 'admin', team_name)))
    check('U6', 'add_to_team: an API user refused', refused(lambda: tools.add_to_team(inst, 'agent-runner', team_name)))
    first, done = twice(tools.add_to_team, inst, 'staff-1', team_name)
    staff1 = by(a, 'User', 'userName', 'staff-1')[0]
    check('U6', 'add_to_team: staff-1 in the project team', done.get('changed')
          and pteam['id'] in a.call('GET', f'/User/{staff1["id"]}')['teamsIds'], done)
    check('U6', 'add_to_team again: nothing to do', tools.add_to_team(inst, 'staff-1', team_name).get('changed') is False)
    first, done = twice(tools.remove_from_team, inst, 'staff-1', team_name)
    check('U6', 'remove_from_team: out again', done.get('changed')
          and pteam['id'] not in a.call('GET', f'/User/{staff1["id"]}')['teamsIds'], done)
    first, done = twice(tools.remove_from_team, inst, USER, team_name)
    check('U6', 'the partner taken out of the team: the site refused at once',
          status(lambda: me.call('GET', f'/CSite/{site["id"]}')) == 403)
    a.call('DELETE', f'/CSite/{elsewhere["id"]}')

    # --- U7: a stale token ------------------------------------------------------------------
    first = tools.add_to_team(inst, USER, team_name)
    a.call('POST', f'/Team/{pteam["id"]}/users', body={'id': u['id']})
    again = tools.add_to_team(inst, USER, team_name, confirm=first['confirm'])
    check('U7', 'add_to_team after someone else did it: nothing to do (the token not needed)', again.get('changed') is False,
          again)

    # --- U8: a contact's portal login (invite_portal_user) ---------------------------------------
    account = a.call('POST', '/Account', body={'name': f'MCPP {RUN} Organisation'})
    email = f'delivered+mcpp-portal-{RUN}@resend.dev'
    contact = a.call('POST', '/Contact', body={'firstName': 'Pia', 'lastName': f'Portal {RUN}', 'emailAddress': email,
                                               'accountId': account['id']}, headers={'X-Skip-Duplicate-Check': 'true'})
    loose = a.call('POST', '/Contact', body={'firstName': 'Lou', 'lastName': f'Noaccount {RUN}',
                                             'emailAddress': f'mcpp-loose-{RUN}@example.org'}, headers={'X-Skip-Duplicate-Check': 'true'})
    check('U8', 'invite_portal_user: an unknown contact, one on no Account, an unknown portal or role: refused',
          all(refused(f) for f in (lambda: tools.invite_portal_user(inst, 'nobody@example.org', 'CSO portal', 'CSO portal'),
                                   lambda: tools.invite_portal_user(inst, loose['id'], 'CSO portal', 'CSO portal'),
                                   lambda: tools.invite_portal_user(inst, email, 'Nope portal', 'CSO portal'),
                                   lambda: tools.invite_portal_user(inst, email, 'CSO portal', 'Nope role'))))
    first = tools.invite_portal_user(inst, email, 'CSO portal', 'CSO portal')
    check('U8', 'first call: what it would make (the contact, its Account, the portal and role), nothing made',
          first.get('would_create', {}).get('sees what belongs to') == [account['name']] and not by(a, 'User', 'contactId', contact['id']),
          first)
    done = tools.invite_portal_user(inst, email, 'CSO portal', 'CSO portal', confirm=first['confirm'])
    u = by(a, 'User', 'contactId', contact['id'])
    u = a.call('GET', f'/User/{u[0]["id"]}') if u else {}
    portal = by(a, 'Portal', 'name', 'CSO portal')[0]
    check('U8', "with the token: a portal user for the contact, on its Account, in the portal with its role",
          u.get('type') == 'portal' and u.get('contactId') == contact['id'] and u.get('accountsIds') == [account['id']]
          and u.get('portalsIds') == [portal['id']] and list((u.get('portalRolesNames') or {}).values()) == ['CSO portal']
          and done.get('changed'), {k: u.get(k) for k in ('type', 'contactName', 'accountsNames', 'portalsNames', 'portalRolesNames')})
    check('U8', 'the same contact again: refused (it has a login)',
          refused(lambda: tools.invite_portal_user(inst, contact['id'], 'CSO portal', 'CSO portal')))
    check('U8', 'no password field in either answer', not any('password' in k for k in keys(first) | keys(done)))
    for x in by(a, 'User', 'contactId', contact['id']):
        a.call('DELETE', f'/User/{x["id"]}')
    for x in (contact, loose):
        a.call('DELETE', f'/Contact/{x["id"]}')
    a.call('DELETE', f'/Account/{account["id"]}')


def status(fn):
    try:
        fn()
        return 200
    except BridgeError as e:
        return e.status


def cleanup(a):
    for u in by(a, 'User', 'userName', USER):
        a.call('DELETE', f'/User/{u["id"]}')
    for site in a.call('GET', '/CSite', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'startsWith',
                                         'where[0][attribute]': 'name', 'where[0][value]': f'MCPP {RUN}'})['list']:
        a.call('DELETE', f'/CSite/{site["id"]}')
    for resp in a.call('GET', '/CResponse', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'startsWith',
                                             'where[0][attribute]': 'name', 'where[0][value]': RESPONSE})['list']:
        for t in a.call('GET', '/Task', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'equals',
                                         'where[0][attribute]': 'cResponseId', 'where[0][value]': resp['id']})['list']:
            a.call('DELETE', f'/Task/{t["id"]}')
        for p in a.call('GET', '/CProject', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'equals',
                                             'where[0][attribute]': 'responseId', 'where[0][value]': resp['id']})['list']:
            a.call('DELETE', f'/CProject/{p["id"]}')
        a.call('DELETE', f'/CResponse/{resp["id"]}')
    for t in a.call('GET', '/Team', {'maxSize': 200, 'select': 'name', 'where[0][type]': 'contains',
                                     'where[0][attribute]': 'name', 'where[0][value]': f'MCPP {RUN}'})['list']:
        a.call('DELETE', f'/Team/{t["id"]}')


if __name__ == '__main__':
    main()
