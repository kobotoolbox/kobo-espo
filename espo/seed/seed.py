#!/usr/bin/env python3
"""
Set up this EspoCRM for the plan's workflows (A: request intake, B: response tasking,
C: sites and lists). Idempotent: run it again after changing anything here.

    python3 -I espo/seed/seed.py [--url https://espo-test.kobolabs.dev] [--users]

Makes, with the admin API only (no files on the server):
  - entities: Response (CResponse) and Site (CSite), Standard (CStandard), their fields,
    and the links Task -> Response, Site -> Response;
  - Task: board columns on its status (Backlog, To do, In progress, Blocked, Done; EspoCRM's
    own Not Started/Started/Completed are relabelled, not replaced, so its "completed" logic
    keeps working), Kanban on, a Task takes its Response's teams;
  - Case: source, category; one team only (API Before Save Script refuses a second);
  - Contact: profileType, availability;
  - teams and roles (staff, triager, partner staff, roster, volunteer), see TEAMS, ROLES;
  - formulas: espo/formula/*.formula, one per entity and script type;
  - settings: assignment notifications for cases and tasks.
--users makes the test users (USERS) with generated passwords, kept in
secrets/seed.secrets (gitignored).

The bridge's API users and roles aren't made here: kobo-bridge's setup.py makes them per
template (kobo/templates/*.toml), each with only what its template needs.
"""
import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import URL, Espo, admin, pw_key, secrets as read_secrets  # noqa: E402

TEAMS = ['Internal Kobo', 'Project: Consortium A', 'Project: Consortium B',
         'Response: Test EQ 1', 'Response: Test EQ 2', 'Roster and volunteers']

ENTITIES = {
    'Response': {'labelPlural': 'Responses', 'iconClass': 'fas fa-house-damage', 'fields': {
        'status': {'type': 'enum', 'options': ['Planning', 'Active', 'Closed'], 'default': 'Planning',
                   'style': {'Active': 'success', 'Closed': 'info'}},
        'emergencyType': {'type': 'enum', 'label': 'Emergency type',
                          'options': ['', 'Earthquake', 'Flood', 'Cyclone', 'Drought', 'Conflict', 'Epidemic', 'Other']},
        'country': {'type': 'varchar'},
        'startDate': {'type': 'date', 'label': 'Start date'},
        'endDate': {'type': 'date', 'label': 'End date'},
    }},
    'Site': {'labelPlural': 'Sites', 'iconClass': 'fas fa-map-marker-alt', 'fields': {
        'siteCode': {'type': 'varchar', 'label': 'Site code', 'required': True},
        # Values as the Kobo forms' choice names, labels as people read them
        'siteType': {'type': 'enum', 'label': 'Site type',
                     'options': ['', 'water_point', 'solar', 'health_post', 'shelter', 'other'],
                     'translatedOptions': {'water_point': 'Water point', 'solar': 'Solar installation',
                                           'health_post': 'Health post', 'shelter': 'Shelter', 'other': 'Other'}},
        'status': {'type': 'enum', 'options': ['planned', 'operational', 'needs_repair', 'decommissioned'],
                   'translatedOptions': {'planned': 'Planned', 'operational': 'Operational',
                                         'needs_repair': 'Needs repair', 'decommissioned': 'Decommissioned'},
                   'default': 'planned', 'style': {'operational': 'success', 'needs_repair': 'danger'}},
        'region': {'type': 'varchar'},
        'latitude': {'type': 'float', 'decimalPlaces': 6},
        'longitude': {'type': 'float', 'decimalPlaces': 6},
        'installedAt': {'type': 'date', 'label': 'Installed'},
        'equipment': {'type': 'text'},
        'lastVisit': {'type': 'date', 'label': 'Last visit'},
    }},
    'Standard': {'labelPlural': 'Standards', 'iconClass': 'fas fa-book', 'fields': {
        'code': {'type': 'varchar', 'required': True},
        'category': {'type': 'enum', 'options': ['', 'WASH', 'Shelter', 'Health', 'Energy', 'Protection']},
        'requirement': {'type': 'text'},
        'source': {'type': 'varchar'},
    }},
}
# (entity, link, foreign entity, foreign link, type). The link on Task, EspoCRM's own
# entity, gets a "c": Task.cResponse (cResponseId); on Site, a custom one, it's Site.response
LINKS = [('CResponse', 'tasks', 'Task', 'response', 'oneToMany'),
         ('CResponse', 'sites', 'CSite', 'response', 'oneToMany'),
         ('CResponse', 'lead', 'User', 'leadOfResponses', 'manyToOne')]

FIELDS = {
    'Case': {
        # cCategory comes from the support form (kobo/templates/support-request.toml)
        'source': {'type': 'enum', 'options': ['Kobo form', 'Email', 'Manual'], 'default': 'Manual'},
    },
    'Contact': {
        'profileType': {'type': 'enum', 'label': 'Profile type',
                        'options': ['', 'Roster', 'Volunteer', 'Partner contact']},
        'availability': {'type': 'text'},
        # cSkills, cLanguages come from the volunteer form (kobo/templates/volunteer.toml)
    },
}

# Board columns. EspoCRM's own statuses stay (its "completed" date and "actual" filters use
# them), relabelled; Backlog and Blocked are added
TASK_STATUS = ['Backlog', 'Not Started', 'Started', 'Blocked', 'Completed', 'Canceled', 'Deferred']
TASK_LABELS = {'Backlog': 'Backlog', 'Not Started': 'To do', 'Started': 'In progress',
               'Blocked': 'Blocked', 'Completed': 'Done', 'Canceled': 'Canceled', 'Deferred': 'Deferred'}

ALL, TEAM, OWN, NO = 'all', 'team', 'own', 'no'


def access(create, read, edit, stream=None, delete=NO):
    return {'create': create, 'read': read, 'edit': edit, 'delete': delete, 'stream': stream or read}


ROLES = {
    # Kobo staff: everything of their teams, no delete
    'Internal Staff': {
        'data': {e: access('yes', TEAM, TEAM) for e in
                 ('Case', 'Task', 'CResponse', 'CSite', 'Contact', 'Account')}
        | {'CStandard': access('yes', ALL, ALL), 'Team': {'read': ALL}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'yes',
    },
    # Triages a project's requests: its cases, the requesters, assigns within the team
    'Support Triager': {
        'data': {'Case': access('yes', TEAM, TEAM), 'Contact': access('no', TEAM, NO),
                 'Account': access('no', TEAM, NO), 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Partner organisation staff in a consortium: their project's cases
    'Partner Staff': {
        'data': {'Case': access('yes', TEAM, TEAM), 'Contact': access('no', TEAM, NO),
                 'Account': access('no', TEAM, NO), 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Roster experts: their response's tasks and sites; edit their own tasks
    'Roster Expert': {
        'data': {'Task': access('yes', TEAM, OWN, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CSite': access('no', TEAM, OWN, TEAM), 'CStandard': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': TEAM, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
    # Volunteers: as roster experts, but can't create tasks or edit sites
    'Volunteer': {
        'data': {'Task': access('no', TEAM, OWN, TEAM), 'CResponse': access('no', TEAM, NO),
                 'CSite': access('no', TEAM, NO), 'CStandard': access('no', ALL, NO),
                 'Team': {'read': TEAM}, 'User': {'read': TEAM}},
        'assignmentPermission': NO, 'userPermission': TEAM, 'mentionPermission': TEAM,
        'exportPermission': 'no', 'massUpdatePermission': 'no',
    },
}

INT, A, B, EQ1, EQ2, POOL = TEAMS
# (username, name, role, teams). Response 1 only: roster-1, volunteer-2; Response 2 only:
# volunteer-1; both: roster-2
USERS = [
    ('triager', 'Tess Triager', 'Support Triager', [A, B]),
    ('staff-1', 'Sam Staff', 'Internal Staff', [INT, A, EQ1, EQ2, POOL]),
    ('staff-2', 'Sasha Staff', 'Internal Staff', [INT, B]),
    ('partner-a', 'Pat Partner-A', 'Partner Staff', [A]),
    ('partner-b', 'Pam Partner-B', 'Partner Staff', [B]),
    ('roster-1', 'Rui Roster', 'Roster Expert', [EQ1]),
    ('roster-2', 'Rana Roster', 'Roster Expert', [EQ1, EQ2]),
    ('volunteer-1', 'Vic Volunteer', 'Volunteer', [EQ2]),
    ('volunteer-2', 'Val Volunteer', 'Volunteer', [EQ1]),
]


def find(espo, entity, attr, value):
    return espo.find(entity, attr, value)


def ensure(espo, entity, attr, value, body, update=False):
    row = find(espo, entity, attr, value)
    if row is None:
        row = espo.call('POST', f'/{entity}', body=body)
        print(f'{entity} created: {value}')
    elif update:
        espo.call('PUT', f'/{entity}/{row["id"]}', body=body)
    return row


def metadata(espo, key):
    return espo.call('GET', '/Metadata', {'key': key}) or {}


def ensure_field(espo, entity, name, spec):
    defs = metadata(espo, f'entityDefs.{entity}.fields')
    # Custom fields of EspoCRM's own entities get a "c" prefix; a custom entity's don't
    custom = metadata(espo, f'scopes.{entity}').get('isCustom')
    full = name if custom else 'c' + name[0].upper() + name[1:]
    body = {'label': spec.get('label', name[0].upper() + name[1:]), **{k: v for k, v in spec.items() if k != 'label'}}
    if full in defs:
        espo.call('PUT', f'/Admin/fieldManager/{entity}/{full}', body=body)
    else:
        espo.call('POST', f'/Admin/fieldManager/{entity}', body={'name': name, **body})
        print(f'field created: {entity}.{full}')
    return full


def ensure_entities(espo):
    scopes = metadata(espo, 'scopes')
    for name, spec in ENTITIES.items():
        if f'C{name}' not in scopes:
            espo.call('POST', '/EntityManager/action/createEntity', body={
                'name': name, 'type': 'Base', 'labelSingular': name, 'labelPlural': spec['labelPlural'],
                'stream': True, 'iconClass': spec['iconClass']})
            print(f'entity created: C{name}')
        if 'status' in spec['fields']:
            espo.call('POST', '/EntityManager/action/updateEntity', body={'name': f'C{name}', 'statusField': 'status'})
        for field, fspec in spec['fields'].items():
            ensure_field(espo, f'C{name}', field, fspec)
    for entity, link, foreign, link_foreign, kind in LINKS:
        if link not in metadata(espo, f'entityDefs.{entity}.links'):
            espo.call('POST', '/EntityManager/action/createLink', body={
                'entity': entity, 'link': link, 'linkForeign': link_foreign, 'entityForeign': foreign,
                'linkType': kind, 'label': link[0].upper() + link[1:], 'labelForeign': link_foreign[0].upper()
                + link_foreign[1:], 'relationName': None})
            print(f'link created: {entity}.{link} -> {foreign}.{link_foreign}')


def ensure_task_board(espo):
    status = metadata(espo, 'entityDefs.Task.fields.status')
    espo.call('PUT', '/Admin/fieldManager/Task/status', body={
        'type': 'enum', 'options': TASK_STATUS, 'translatedOptions': TASK_LABELS, 'default': 'Backlog',
        'style': {**status.get('style', {}), 'Blocked': 'danger', 'Backlog': 'default'},
        'notActualOptions': ['Completed', 'Canceled', 'Deferred']})
    espo.call('POST', '/EntityManager/action/updateEntity', body={
        'name': 'Task', 'kanbanViewMode': True, 'statusField': 'status',
        'kanbanStatusIgnoreList': ['Canceled', 'Deferred']})
    print('Task: board columns, Kanban on')


def ensure_formulas(espo):
    """espo/formula/<Entity>.<scriptType>.formula, e.g. Case.beforeSaveApiScript.formula"""
    by_entity = {}
    for path in sorted((ROOT / 'espo' / 'formula').glob('*.formula')):
        entity, kind = path.stem.split('.')
        by_entity.setdefault(entity, {})[kind] = path.read_text()
    for entity, scripts in by_entity.items():
        espo.call('POST', '/EntityManager/action/formula', body={'scope': entity, 'data': scripts})
        print(f'formula: {entity} ({", ".join(scripts)})')


def ensure_layout_fields(espo, entity, names, panel='Details'):
    """Add fields to the first panel of the detail layout if they aren't on it (and drop
    cells for fields that don't exist, e.g. from an earlier run with a wrong name)."""
    detail = espo.call('GET', f'/{entity}/layout/detail')
    fields = metadata(espo, f'entityDefs.{entity}.fields')
    stale = False
    for p in detail:
        for row in p.get('rows', []):
            for i, c in enumerate(row):
                if c and c.get('name') not in fields:
                    row[i], stale = False, True
    have = {c['name'] for p in detail for row in p.get('rows', []) for c in row if c}
    missing = [n for n in names if n not in have]
    if not missing:
        if stale:
            espo.call('PUT', f'/{entity}/layout/detail', body=detail)
        return
    rows = [[{'name': n} for n in missing[i:i + 2]] for i in range(0, len(missing), 2)]
    detail[0].setdefault('rows', []).extend(r + [False] * (2 - len(r)) for r in rows)
    espo.call('PUT', f'/{entity}/layout/detail', body=detail)
    print(f'layout: {entity} detail + {", ".join(missing)}')


def ensure_layouts(espo):
    ensure_layout_fields(espo, 'CResponse', ['status', 'emergencyType', 'country', 'lead', 'startDate', 'endDate'])
    ensure_layout_fields(espo, 'CSite', ['siteCode', 'siteType', 'status', 'region', 'response', 'installedAt',
                                         'lastVisit', 'latitude', 'longitude', 'equipment'])
    ensure_layout_fields(espo, 'CStandard', ['code', 'category', 'source', 'requirement'])
    ensure_layout_fields(espo, 'Task', ['cResponse'])  # EspoCRM's own entity: c-prefixed
    ensure_layout_fields(espo, 'Contact', ['cProfileType', 'cAvailability'])
    ensure_layout_fields(espo, 'Case', ['cSource'])
    for entity, cols in {'CResponse': ['name', 'status', 'emergencyType', 'country', 'lead', 'teams'],
                         'CSite': ['name', 'siteCode', 'siteType', 'status', 'region', 'response', 'lastVisit'],
                         'CStandard': ['name', 'code', 'category', 'source']}.items():
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True} if n == 'name' else {})} for n in cols])
    kanban = [{'name': 'name', 'link': True}, {'name': 'cResponse'}, {'name': 'assignedUser'}, {'name': 'dateEnd'}]
    espo.call('PUT', '/Task/layout/kanban', body=kanban)
    espo.call('PUT', '/Task/layout/filters',
              body=sorted(set(espo.call('GET', '/Task/layout/filters') or []) | {'cResponse', 'status', 'assignedUser'}))
    print('layouts: lists, task board card and filters')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    ap.add_argument('--users', action='store_true')
    args = ap.parse_args()
    espo = admin() if args.url == URL else Espo(args.url, basic=f'admin:{read_secrets()["ESPO_ADMIN_PASSWORD"]}')

    settings = espo.call('GET', '/Settings')
    espo.call('PUT', '/Settings', body={
        'assignmentNotificationsEntityList': sorted(set(settings.get('assignmentNotificationsEntityList') or [])
                                                    | {'Case', 'Task', 'CResponse', 'CSite'}),
        # In global search, so the isolation tests (T8) search them too
        'globalSearchEntityList': sorted(set(settings.get('globalSearchEntityList') or [])
                                         | {'Case', 'Contact', 'Account', 'Task', 'CResponse', 'CSite', 'CStandard'}),
        'applicationName': 'Kobo requests and responses (test)'})
    print('settings: assignment notifications for Case, Task, Response, Site; global search')

    ensure_entities(espo)
    for entity, fields in FIELDS.items():
        for name, spec in fields.items():
            ensure_field(espo, entity, name, spec)
    ensure_task_board(espo)
    ensure_formulas(espo)
    ensure_layouts(espo)

    # Reference data: standards (no team: everyone with read access sees them)
    import json
    for std in json.loads((ROOT / 'espo' / 'seed' / 'data' / 'standards.json').read_text()):
        ensure(espo, 'CStandard', 'code', std['code'], std, update=True)

    teams = {name: ensure(espo, 'Team', 'name', name, {'name': name})['id'] for name in TEAMS}
    roles = {}
    for name, spec in ROLES.items():
        roles[name] = ensure(espo, 'Role', 'name', name, {'name': name, 'fieldData': {}, **spec}, update=True)['id']
    print(f'teams: {len(teams)}, roles: {", ".join(roles)}')

    if args.users:
        path = ROOT / 'secrets' / 'seed.secrets'
        have = read_secrets('seed')
        out = dict(have)
        for username, full, role, team_names in USERS:
            first, last = full.split(' ', 1)
            key = pw_key(username)
            password = have.get(key) or secrets.token_urlsafe(14)
            body = {'userName': username, 'firstName': first, 'lastName': last, 'type': 'regular',
                    'isActive': True, 'rolesIds': [roles[role]], 'teamsIds': [teams[t] for t in team_names],
                    'defaultTeamId': teams[team_names[0]], 'emailAddress': f'{username}@example.org'}
            user = find(espo, 'User', 'userName', username)
            if user is None:
                espo.call('POST', '/User', body={**body, 'password': password})
                print(f'user created: {username} ({role}; {", ".join(team_names)})')
            else:  # teams and roles as defined here; the password too if it was lost
                espo.call('PUT', f'/User/{user["id"]}', body={**body, **({} if key in have else {'password': password})})
            out[key] = password
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_text(''.join(f'{k}={v}\n' for k, v in out.items()))
        path.chmod(0o600)
        print(f'users: {len(USERS)}, passwords in {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
