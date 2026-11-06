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

The bridge's API users and roles aren't made here: kobo-espo-bridge's setup.py makes them per
template (kobo/templates/*.toml), each with only what its template needs.
"""
import argparse
import json
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import URL, Espo, admin, pw_key, secrets as read_secrets  # noqa: E402

TEAMS = ['Internal Kobo', 'Project: Consortium A', 'Project: Consortium B',
         'Response: Test EQ 1', 'Response: Test EQ 2', 'Roster and volunteers', 'Grants review']

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
        'photos': {'type': 'attachmentMultiple'},  # from the registration form (kobo-espo-bridge media)
    }},
    'Standard': {'labelPlural': 'Standards', 'iconClass': 'fas fa-book', 'fields': {
        'code': {'type': 'varchar', 'required': True},
        'category': {'type': 'enum', 'options': ['', 'WASH', 'Shelter', 'Health', 'Energy', 'Protection']},
        'requirement': {'type': 'text'},
        'source': {'type': 'varchar'},
    }},
    # Agents (plans/espo-agents-plan.md): set up here, run by agents/runner.py
    'Agent': {'labelPlural': 'Agents', 'iconClass': 'fas fa-robot', 'stream': False, 'fields': {
        'mode': {'type': 'enum', 'options': ['off', 'dry_run', 'active'], 'default': 'off',
                 'translatedOptions': {'off': 'Off', 'dry_run': 'Dry run', 'active': 'Active'},
                 'style': {'active': 'success', 'dry_run': 'warning'}, 'audited': True},
        'runner': {'type': 'enum', 'options': ['droplet', 'tests'], 'default': 'droplet',
                   'tooltipText': 'Which runner runs it: the one on the server, or the tests.'},
        'entity': {'type': 'enum', 'label': 'Works on', 'options': ['CApplication', 'CSite', 'Case', 'Task'],
                   'translatedOptions': {'CApplication': 'Application', 'CSite': 'Site', 'Case': 'Case', 'Task': 'Task'}},
        'trigger': {'type': 'enum', 'options': ['stage', 'change', 'schedule'],
                    'translatedOptions': {'stage': 'Records in a stage', 'change': 'When a field changes',
                                          'schedule': 'On a schedule'}},
        'triggerStage': {'type': 'varchar', 'label': 'Stage'},
        'watchField': {'type': 'varchar', 'label': 'Watched field'},
        'scheduleEvery': {'type': 'enum', 'label': 'Repeats', 'options': ['', 'hour', 'day', 'week'],
                          'translatedOptions': {'': '', 'hour': 'Every hour', 'day': 'Every day', 'week': 'Every week'}},
        'scheduleAt': {'type': 'varchar', 'label': 'At (UTC)', 'maxLength': 5,
                       'tooltipText': 'HH:MM, e.g. 06:00. Every hour: only the minutes count.'},
        'scheduleWeekday': {'type': 'enum', 'label': 'On (every week)', 'options': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                            'default': 'Mon'},
        'idleField': {'type': 'varchar', 'label': 'Only if this date is older than',
                      'tooltipText': 'A date field, e.g. lastVisit or modifiedAt; with the days next to it.'},
        'idleDays': {'type': 'int', 'label': 'days', 'min': 1},
        'filterField': {'type': 'varchar', 'label': 'Only where field'},
        'filterValue': {'type': 'varchar', 'label': 'equals'},
        'readFields': {'type': 'array', 'label': 'Reads', 'audited': True},
        'readNotes': {'type': 'bool', 'label': 'Reads the latest note'},
        'readAttachments': {'type': 'varchar', 'label': 'Reads the files in field'},
        'tools': {'type': 'multiEnum', 'options': ['sanctions', 'registry', 'web_search', 'web_fetch'], 'audited': True},
        'instructions': {'type': 'text', 'audited': True},
        'outputFields': {'type': 'array', 'label': 'Fills in', 'audited': True},
        'model': {'type': 'enum', 'options': ['', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
                  'translatedOptions': {'': 'None (rules only)'}, 'default': 'claude-opus-5-5', 'audited': True},
        'maxAttempts': {'type': 'int', 'label': 'Max attempts', 'default': 3, 'min': 1, 'max': 10},
        'budgetPerRun': {'type': 'float', 'label': 'Budget per run (USD)', 'default': 0.5},
        'onFailure': {'type': 'varchar', 'label': 'Route on failure'},
        'version': {'type': 'int', 'default': 1, 'readOnly': True},
        'activeSince': {'type': 'datetime', 'label': 'Working since', 'readOnly': True},
    }},
    'AgentRoute': {'labelPlural': 'Agent routes', 'iconClass': 'fas fa-route', 'stream': False, 'fields': {
        'order': {'type': 'int', 'default': 10},
        'ruleField': {'type': 'varchar', 'label': 'Rule: field', 'tooltipText': 'A field, a tool result, or "text" (the read fields and note)'},
        'ruleOp': {'type': 'enum', 'label': 'Rule: test', 'options': ['', 'equals', 'in', 'contains', 'matches']},
        'ruleValue': {'type': 'varchar', 'label': 'Rule: value', 'maxLength': 500},
        'ruleWhen': {'type': 'enum', 'label': 'Rule applies', 'options': ['before', 'after'],
                     'translatedOptions': {'before': 'Before the model (skips it)', 'after': 'After the model (overrides it)'}},
        'moveToStage': {'type': 'varchar', 'label': 'Move to stage'},
        'clearAssignee': {'type': 'bool', 'label': 'Unassign'},
        'createTask': {'type': 'bool', 'label': 'Create a task'},
        'taskName': {'type': 'varchar', 'label': 'Task name', 'tooltipText': 'e.g. Urgent: {name}'},
        'taskStatus': {'type': 'varchar', 'label': 'Task status', 'default': 'Backlog'},
        'taskPriority': {'type': 'enum', 'label': 'Task priority', 'options': ['Low', 'Normal', 'High', 'Urgent'], 'default': 'Normal'},
        'taskAssignFrom': {'type': 'varchar', 'label': 'Task assignee from',
                           'tooltipText': 'A user link on the record or its response, e.g. response.lead'},
        'setFields': {'type': 'text', 'label': 'Set fields (JSON)'},
        'fixedNote': {'type': 'text', 'label': 'Fixed note', 'tooltipText': 'Posted instead of the model\'s words'},
        'notify': {'type': 'bool', 'label': 'Mention the assignee'},
    }},
    'AgentRun': {'labelPlural': 'Agent runs', 'iconClass': 'fas fa-history', 'stream': False, 'fields': {
        'status': {'type': 'enum', 'options': ['running', 'done', 'dry_run', 'failed'], 'default': 'running',
                   'style': {'done': 'success', 'failed': 'danger', 'dry_run': 'warning'}},
        'recordType': {'type': 'varchar'},
        'recordId': {'type': 'varchar'},
        'recordName': {'type': 'varchar'},
        'triggerKey': {'type': 'varchar', 'maxLength': 255},
        'agentVersion': {'type': 'int'},
        'model': {'type': 'varchar'},
        'promptHash': {'type': 'varchar'},
        'route': {'type': 'varchar'},
        'routeBy': {'type': 'enum', 'options': ['', 'rule_before', 'model', 'rule_after', 'failure']},
        'reason': {'type': 'text'},
        'output': {'type': 'text'},
        'error': {'type': 'text'},
        'attempts': {'type': 'int', 'default': 0},
        'inputTokens': {'type': 'int'},
        'outputTokens': {'type': 'int'},
        'cost': {'type': 'float', 'decimalPlaces': 4},
        'durationS': {'type': 'float', 'label': 'Duration (s)'},
    }},
    # Workflow D: an organisation's application for support, through due diligence
    'Application': {'labelPlural': 'Applications', 'iconClass': 'fas fa-file-signature', 'statusField': 'stage', 'fields': {
        'stage': {'type': 'enum', 'options': ['Submitted', 'Screening', 'Research', 'Review', 'Needs info', 'Decision',
                                              'Approved', 'Rejected'], 'default': 'Submitted',
                  'style': {'Review': 'primary', 'Needs info': 'warning', 'Approved': 'success', 'Rejected': 'danger'}},
        'country': {'type': 'varchar'},
        'registrationNumber': {'type': 'varchar', 'label': 'Registration number'},
        'website': {'type': 'url'},
        'amountRequested': {'type': 'float', 'label': 'Amount requested (USD)'},
        'purpose': {'type': 'text'},
        'leadership': {'type': 'text', 'tooltipText': 'Names of the organisation\'s leaders, one per line'},
        'documents': {'type': 'attachmentMultiple'},
        'noticeVersion': {'type': 'varchar', 'label': 'Notice version'},
        'ddSanctions': {'type': 'enum', 'label': 'Sanctions', 'options': ['', 'clear', 'possible_match', 'match'],
                        'translatedOptions': {'clear': 'Clear', 'possible_match': 'Possible match', 'match': 'Match'},
                        'style': {'clear': 'success', 'possible_match': 'warning', 'match': 'danger'}},
        'ddSanctionsDetail': {'type': 'text', 'label': 'Sanctions detail'},
        'ddRegistry': {'type': 'enum', 'label': 'Registry', 'options': ['', 'found', 'not_found', 'not_checked']},
        'ddRisk': {'type': 'enum', 'label': 'Risk', 'options': ['', 'low', 'medium', 'high', 'unknown'],
                   'style': {'low': 'success', 'medium': 'warning', 'high': 'danger'}},
        'ddFlags': {'type': 'multiEnum', 'label': 'Flags',
                    'options': ['name_mismatch', 'no_web_presence', 'doc_unreadable', 'new_org', 'adverse_media',
                                'inconsistent_figures', 'instructions_in_application']},
        'ddSummary': {'type': 'text', 'label': 'Due diligence summary'},
    }},
}
# The entities agents work on: their API Before Save Script starts with _agent-guard.formula
AGENT_GUARDED = ['CApplication', 'CSite', 'Task']
# (entity, link, foreign entity, foreign link, type). The link on Task, EspoCRM's own
# entity, gets a "c": Task.cResponse (cResponseId); on Site, a custom one, it's Site.response
LINKS = [('CResponse', 'tasks', 'Task', 'response', 'oneToMany'),
         ('CResponse', 'sites', 'CSite', 'response', 'oneToMany'),
         ('CStandard', 'sites', 'CSite', 'standard', 'oneToMany'),  # the standard a site follows
         ('CResponse', 'lead', 'User', 'leadOfResponses', 'manyToOne'),
         ('CAgent', 'routes', 'CAgentRoute', 'agent', 'oneToMany'),
         ('CAgent', 'user', 'User', 'agentProfiles', 'manyToOne'),  # its API user (agents/sync.py)
         ('CAgentRoute', 'assignUser', 'User', 'agentRoutes', 'manyToOne'),
         ('CAgentRoute', 'assignAgent', 'CAgent', 'routedHere', 'manyToOne'),  # hand over to another agent
         ('CAgent', 'runs', 'CAgentRun', 'agent', 'oneToMany'),
         ('CApplication', 'account', 'Account', 'applications', 'manyToOne'),
         ('CApplication', 'contact', 'Contact', 'applications', 'manyToOne')]

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
                 ('Case', 'Task', 'CResponse', 'CSite', 'Contact', 'Account', 'CApplication')}
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

INT, A, B, EQ1, EQ2, POOL, GRANTS = TEAMS
# (username, name, role, teams). Response 1 only: roster-1, volunteer-2; Response 2 only:
# volunteer-1; both: roster-2
USERS = [
    ('triager', 'Tess Triager', 'Support Triager', [A, B]),
    ('staff-1', 'Sam Staff', 'Internal Staff', [INT, A, EQ1, EQ2, POOL]),
    ('staff-2', 'Sasha Staff', 'Internal Staff', [INT, B, GRANTS]),  # reviews applications (Workflow D)
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
                'stream': spec.get('stream', True), 'iconClass': spec['iconClass']})
            print(f'entity created: C{name}')
        status = spec.get('statusField', 'status' if 'status' in spec['fields'] else None)
        if status:
            espo.call('POST', '/EntityManager/action/updateEntity', body={'name': f'C{name}', 'statusField': status})
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
    """espo/formula/<Entity>.<scriptType>.formula, e.g. Case.beforeSaveApiScript.formula;
    _agent-guard.formula goes first in the API Before Save Script of AGENT_GUARDED (its
    stage block only where the entity has a stage)."""
    by_entity = {}
    for path in sorted((ROOT / 'espo' / 'formula').glob('[!_]*.formula')):
        entity, kind = path.stem.split('.')
        by_entity.setdefault(entity, {})[kind] = path.read_text()
    guard = (ROOT / 'espo' / 'formula' / '_agent-guard.formula').read_text()
    for entity in AGENT_GUARDED:
        g = guard
        if 'stage' not in metadata(espo, f'entityDefs.{entity}.fields'):
            g = re.sub(r'\n *// stage:begin.*?// stage:end\n', '\n', g, flags=re.S)
        scripts = by_entity.setdefault(entity, {})
        scripts['beforeSaveApiScript'] = g + '\n' + scripts.get('beforeSaveApiScript', '')
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
    ensure_layout_fields(espo, 'CSite', ['siteCode', 'siteType', 'status', 'region', 'response', 'standard', 'installedAt',
                                         'lastVisit', 'latitude', 'longitude', 'equipment', 'photos'])
    ensure_layout_fields(espo, 'CStandard', ['code', 'category', 'source', 'requirement'])
    ensure_layout_fields(espo, 'Task', ['cResponse'])  # EspoCRM's own entity: c-prefixed
    ensure_layout_fields(espo, 'Contact', ['cProfileType', 'cAvailability'])
    ensure_layout_fields(espo, 'Case', ['cSource'])
    for entity, cols in {'CResponse': ['name', 'status', 'emergencyType', 'country', 'lead', 'teams'],
                         'CSite': ['name', 'siteCode', 'siteType', 'status', 'region', 'response', 'lastVisit'],
                         'CStandard': ['name', 'code', 'category', 'source']}.items():
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True} if n == 'name' else {})} for n in cols])
    # A response's page: its tasks and sites below it
    espo.call('PUT', '/CResponse/layout/relationships', body=[{'name': 'tasks'}, {'name': 'sites'}])
    kanban = [{'name': 'name', 'link': True}, {'name': 'cResponse'}, {'name': 'assignedUser'}, {'name': 'dateEnd'}]
    espo.call('PUT', '/Task/layout/kanban', body=kanban)
    task_fields = metadata(espo, 'entityDefs.Task.fields')
    espo.call('PUT', '/Task/layout/filters',  # (without fields that don't exist, e.g. from an earlier run)
              body=sorted(f for f in set(espo.call('GET', '/Task/layout/filters') or []) | {'cResponse', 'status', 'assignedUser'}
                          if f in task_fields))
    print('layouts: lists, task board card and filters')

    # Agents: set up on the Agent's page, its routes and runs below it
    agent_fields = list(ENTITIES['Agent']['fields'])
    ensure_layout_fields(espo, 'CAgent', ['description'] + agent_fields)
    ensure_layout_fields(espo, 'CAgentRoute', ['agent', 'description', 'assignUser', 'assignAgent']
                         + list(ENTITIES['AgentRoute']['fields']))
    ensure_layout_fields(espo, 'CAgentRun', ['agent'] + list(ENTITIES['AgentRun']['fields']))
    for entity, cols in {'CAgent': ['name', 'mode', 'entity', 'trigger', 'model', 'version', 'activeSince'],
                         'CAgentRoute': ['name', 'agent', 'order', 'ruleWhen', 'moveToStage', 'createTask'],
                         'CAgentRun': ['createdAt', 'agent', 'recordName', 'status', 'route', 'routeBy', 'cost'],
                         'CApplication': ['name', 'account', 'country', 'stage', 'ddSanctions', 'ddRisk', 'assignedUser']
                         }.items():
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True} if n in ('name', 'createdAt') else {})} for n in cols])
    espo.call('PUT', '/CAgent/layout/relationships', body=[{'name': 'routes'}, {'name': 'runs'}])

    # Applications: a board by stage
    ensure_layout_fields(espo, 'CApplication', ['stage', 'account', 'contact', 'country', 'registrationNumber', 'website',
                                                'amountRequested', 'noticeVersion', 'purpose', 'leadership', 'documents'])
    ensure_layout_fields(espo, 'CApplication', ['ddSanctions', 'ddRegistry', 'ddRisk', 'ddFlags', 'ddSanctionsDetail',
                                                'ddSummary'])
    espo.call('POST', '/EntityManager/action/updateEntity', body={
        'name': 'CApplication', 'kanbanViewMode': True, 'statusField': 'stage',
        'kanbanStatusIgnoreList': ['Approved', 'Rejected']})
    espo.call('PUT', '/CApplication/layout/kanban',
              body=[{'name': 'name', 'link': True}, {'name': 'account'}, {'name': 'ddRisk'}, {'name': 'assignedUser'}])
    print('layouts: agents, applications (board)')


def ensure_agents(espo, teams):
    """The example agents (agents/setup/*.json), made if missing, in their mode there
    (dry run or off): what someone changed on an agent since isn't overwritten."""
    for path in sorted((ROOT / 'agents' / 'setup').glob('*.json')):
        for spec in json.loads(path.read_text()):
            if find(espo, 'CAgent', 'name', spec['name']):
                continue
            make_agent(espo, spec, teams)
            print(f'agent created: {spec["name"]}')


def make_agent(espo, spec, teams):
    """An Agent and its routes from a spec as in agents/setup/*.json: route targets by name
    (assignUser: a user name, assignAgent: an agent's name), teams by name."""
    body = {k: v for k, v in spec.items() if k not in ('routes', 'teams')}
    body['teamsIds'] = [teams[t] for t in spec.get('teams', [])]
    agent = espo.call('POST', '/CAgent', body=body)
    for route in spec.get('routes', []):
        r = {k: v for k, v in route.items() if k not in ('assignUser', 'assignAgent')}
        if route.get('assignUser'):
            r['assignUserId'] = espo.find('User', 'userName', route['assignUser'])['id']
        if route.get('assignAgent'):
            r['assignAgentId'] = espo.find('CAgent', 'name', route['assignAgent'])['id']
        if isinstance(r.get('setFields'), dict):
            r['setFields'] = json.dumps(r['setFields'])
        espo.call('POST', '/CAgentRoute', body={**r, 'agentId': agent['id']})
    return agent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    ap.add_argument('--users', action='store_true')
    args = ap.parse_args()
    espo = admin() if args.url == URL else Espo(args.url, basic=f'admin:{read_secrets()["ESPO_ADMIN_PASSWORD"]}')

    settings = espo.call('GET', '/Settings')
    espo.call('PUT', '/Settings', body={
        'assignmentNotificationsEntityList': sorted(set(settings.get('assignmentNotificationsEntityList') or [])
                                                    | {'Case', 'Task', 'CResponse', 'CSite', 'CApplication'}),
        # In global search, so the isolation tests (T8) search them too
        'globalSearchEntityList': sorted(set(settings.get('globalSearchEntityList') or [])
                                         | {'Case', 'Contact', 'Account', 'Task', 'CResponse', 'CSite', 'CStandard', 'CApplication'}),
        'applicationName': 'Kobo requests and responses (test)'})
    print('settings: assignment notifications for Case, Task, Response, Site, Application; global search')

    ensure_entities(espo)
    for entity, fields in FIELDS.items():
        for name, spec in fields.items():
            ensure_field(espo, entity, name, spec)
    ensure_task_board(espo)
    ensure_formulas(espo)
    ensure_layouts(espo)

    # Reference data: standards (no team: everyone with read access sees them)
    for std in json.loads((ROOT / 'espo' / 'seed' / 'data' / 'standards.json').read_text()):
        ensure(espo, 'CStandard', 'code', std['code'], std, update=True)

    teams = {name: ensure(espo, 'Team', 'name', name, {'name': name})['id'] for name in TEAMS}
    roles = {}
    for name, spec in ROLES.items():
        roles[name] = ensure(espo, 'Role', 'name', name, {'name': name, 'fieldData': {}, **spec}, update=True)['id']
    print(f'teams: {len(teams)}, roles: {", ".join(roles)}')
    ensure_agents(espo, teams)

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
