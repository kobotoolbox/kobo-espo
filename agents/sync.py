#!/usr/bin/env python3
"""
Give every Agent set up in EspoCRM its own API user and role, made from its setup, and the
runner its user. Admin only; run it after adding an Agent or changing what it writes.

    python3 -I agents/sync.py [--url https://staging.respond.kobolabs.dev] [--secrets secrets/agents.secrets]

Each agent's role (plan §4 "Sync"):
  - the entity it works on: read, edit and stream for its teams (the Agent's own teams),
    with field-level security: only its output fields, and what its routes set (stage,
    assignee, set fields), are writable;
  - Task: create, if a route creates tasks; the Response, read, if a task's assignee comes
    from it;
  - users of its teams (mentions, assignees); nothing else; no delete, no export.
The runner's user ("agent-runner") reads Agents and routes and writes runs; it can't read
the records agents work on.

Keys go to the secrets file (AGENT_RUNNER_API_KEY, AGENT_KEY_<USER>), mode 600.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'agents'))
from lib import URL, Espo, admin, secrets as read_secrets  # noqa: E402
from runner import key_name, read_secrets as read_file, where  # noqa: E402

NONE = {'create': 'no', 'read': 'no', 'edit': 'no', 'delete': 'no', 'stream': 'no'}
BASE = {'assignmentPermission': 'no', 'userPermission': 'no', 'exportPermission': 'no',
        'massUpdatePermission': 'no', 'mentionPermission': 'no', 'portalPermission': 'no',
        'groupEmailAccountPermission': 'no'}
RUNNER_ROLE = {**BASE, 'data': {'CAgent': {**NONE, 'read': 'all'}, 'CAgentRoute': {**NONE, 'read': 'all'},
                                'CAgentRun': {**NONE, 'create': 'yes', 'read': 'all', 'edit': 'all'},
                                'User': {'read': 'all'}}, 'fieldData': {}, 'userPermission': 'all'}


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def role_for(agent, routes, fields):
    entity = agent['entity']
    writable = set(agent.get('outputFields') or [])
    for r in routes:
        writable |= set(json.loads(r.get('setFields') or '{}'))
        if r.get('moveToStage'):
            writable.add('stage')
        if r.get('assignUserId') or r.get('assignAgentId') or r.get('clearAssignee'):
            writable.add('assignedUser')
    edits = bool(writable)
    data = {entity: {**NONE, 'read': 'team', 'edit': 'team' if edits else 'no', 'stream': 'team'},
            'User': {'read': 'team'}, 'Team': {'read': 'team'}}
    if any(r.get('createTask') for r in routes):
        data['Task'] = {**NONE, 'create': 'yes', 'read': 'team', 'stream': 'team'}
    if any((r.get('taskAssignFrom') or '').startswith('response.') for r in routes):
        data['CResponse'] = {**NONE, 'read': 'team'}
    field_data = {entity: {f: {'read': 'yes', 'edit': 'yes' if f in writable else 'no'} for f in fields
                           if not f.endswith(('Id', 'Ids', 'Name', 'Names', 'Types'))}}
    return {**BASE, 'data': data, 'fieldData': field_data, 'assignmentPermission': 'team',
            'userPermission': 'team', 'mentionPermission': 'team'}


def ensure_user(espo, username, role_name, role_spec, teams=None):
    role = espo.find('Role', 'name', role_name)
    if role is None:
        role = espo.call('POST', '/Role', body={'name': role_name, **role_spec})
        print(f'role created: {role_name}')
    else:
        espo.call('PUT', f'/Role/{role["id"]}', body=role_spec)
    body = {'rolesIds': [role['id']], 'teamsIds': teams or [], 'isActive': True}
    user = espo.find('User', 'userName', username)
    if user is None:
        user = espo.call('POST', '/User', body={'userName': username, 'type': 'api', 'authMethod': 'ApiKey', **body})
        print(f'api user created: {username}')
    else:
        espo.call('PUT', f'/User/{user["id"]}', body=body)
    user = espo.call('GET', f'/User/{user["id"]}')
    if not user.get('apiKey'):
        raise SystemExit(f'{username} has no API key in the response; open it in the UI to generate one')
    return user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    ap.add_argument('--secrets', default=str(ROOT / 'secrets' / 'agents.secrets'))
    args = ap.parse_args()
    espo = admin() if args.url == URL else Espo(args.url, basic=f'admin:{read_secrets()["ESPO_ADMIN_PASSWORD"]}')
    keys = {}
    runner = ensure_user(espo, 'agent-runner', 'Agent runner', RUNNER_ROLE)
    keys['AGENT_RUNNER_API_KEY'] = runner['apiKey']
    for agent in espo.call('GET', '/CAgent', {'maxSize': 200})['list']:
        agent = espo.call('GET', f'/CAgent/{agent["id"]}')
        routes = espo.call('GET', '/CAgentRoute', {**where(('equals', 'agentId', agent['id'])), 'maxSize': 50})['list']
        fields = espo.call('GET', '/Metadata', {'key': f'entityDefs.{agent["entity"]}.fields'}) or {}
        username = 'agent-' + slug(agent['name'])
        user = ensure_user(espo, username, f'Agent: {agent["name"]}', role_for(agent, routes, fields),
                           agent.get('teamsIds'))
        if agent.get('userId') != user['id']:
            espo.call('PUT', f'/CAgent/{agent["id"]}', body={'userId': user['id']})
        keys[key_name(username)] = user['apiKey']
        print(f'agent: {agent["name"]} -> {username} ({agent["mode"]})')
    path = Path(args.secrets)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    have = read_file(path)
    path.write_text(''.join(f'{k}={v}\n' for k, v in {**have, **keys}.items()))
    path.chmod(0o600)
    print(f'keys: {len(keys)} in {path}')


if __name__ == '__main__':
    main()
