"""Workflow packs (plans/workflow-packs-plan.md): each workflow a folder of data, applied to
an instance by one generic loader. The seed (espo/seed/seed.py) applies the packs an
instance names (deploy/instance.toml).

A pack, workflows/<name>/:

    workflow.toml   requires; conflicts (packs meant for other instances: a warning when
                    both are applied); entities and their fields; fields on others' entities; links
                    (and link_labels, where a name's words aren't the label: coLeads = "Co-leads";
                    a manyToMany's 6th entry its relation's name, when two link the same entities);
                    codes; teams; roles (merged across packs); users (tests only); layouts;
                    settings; data to load; removed fields and links; agent_entities,
                    agent_guarded, task_parents
    lists/*.json    choice lists with codes: an enum names one, "<file>.<list>"
    formulas/       <Entity>.<script>.formula: this pack's block of that entity's script
    [traits.<Entity>]            the shared formula patterns it uses (espo/traits.py):
                                 portal_default, pcodes, inherit (and its cascade),
                                 checks, supersede, teams_up, teams_from_clusters,
                                 account_from_organisation, find_or_make_contact,
                                 suggest_leads
    agents.json     its example agents
    data/           its reference data
    migrate.py      migrate(espo): what data can't say (old codes moved), run after applying

    [metadata.<type>.<Entity>]   metadata the admin API can't set (aclDefs: which link a
                                 portal's "account" level follows): installed as one
                                 extension, KoboWorkflows, when it changes
    [portal_roles.<Name>]        a portal's role (access by "account", "contact", "own")
    [[portals]]                  a portal: its name, customId (its URL), tabs, roles
    [params]                     what an instance sets for it (its own forms' links...):
                                 defaults here, the instance's in deploy/instance.toml
                                 [params.<pack>]; a formula says {{name}}, or
                                 {{pick name $variable}} for a table of values by key
                                 (e.g. by country, "default" for the rest)

    spec = load(['core', 'cso'])    # the packs and what they require, merged
    apply(espo, spec, users=False)  # idempotent; never deletes records

Merging: entities are each one pack's; `fields` add fields to any entity; a role is the
union of every pack's access to it (its permissions from the pack that defines it); ordered
lists (relationship panels, a board's card) are joined in `requires` order, an entry with
`before` going in front of that entry; settings' lists are joined.
"""
import base64
import hashlib
import io
import json
import re
import secrets
import sys
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / 'workflows'
FORMULA = ROOT / 'espo' / 'formula'  # the shared snippets: _code, _agent-guard
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'agents'))
sys.path.insert(0, str(ROOT / 'espo'))
from lib import pw_key, secrets as read_secrets  # noqa: E402
import tools as agent_tools  # noqa: E402  (the code tools an agent may use: its Tools field's options)
import traits  # noqa: E402  (espo/traits.py: the formulas' shared patterns)

ALL, TEAM, OWN, NO = 'all', 'team', 'own', 'no'
PERMISSIONS = ('assignmentPermission', 'userPermission', 'mentionPermission', 'exportPermission', 'massUpdatePermission')
CODE_FIELD = {'type': 'varchar', 'label': 'Code', 'maxLength': 12, 'readOnly': True,
              'tooltipText': 'Given by EspoCRM, e.g. PRJ-7K3Q: to name this record, and in Kobo lists'}
TASK_STATUS = ['Backlog', 'Not Started', 'Started', 'Blocked', 'Completed', 'Canceled', 'Deferred']
TASK_LABELS = {'Backlog': 'Backlog', 'Not Started': 'To do', 'Started': 'In progress',
               'Blocked': 'Blocked', 'Completed': 'Done', 'Canceled': 'Canceled', 'Deferred': 'Deferred'}


# --- loading ----------------------------------------------------------------------------------

def order(names, packs_dir=PACKS):
    """The packs named and those they require, each after what it requires."""
    out, seen = [], set()

    def visit(name, path=()):
        if name in path:
            raise ValueError(f'packs require each other: {" -> ".join(path + (name,))}')
        if name in seen:
            return
        meta = read(name, packs_dir)
        for r in meta.get('requires', []):
            visit(r, path + (name,))
        seen.add(name)
        out.append(name)
    for n in names:
        visit(n)
    return out


def read(name, packs_dir=PACKS):
    path = packs_dir / name / 'workflow.toml'
    if not path.exists():
        raise ValueError(f'no pack {name!r} ({path})')
    return tomllib.loads(path.read_text())


def lists_of(names, packs_dir=PACKS):
    """Every choice list of these packs: "<file stem>.<list>" -> [{code, label}]."""
    out = {}
    for name in names:
        for path in sorted((packs_dir / name / 'lists').glob('*.json')):
            for key, value in json.loads(path.read_text()).items():
                if isinstance(value, dict) and 'choices' in value:
                    value = value['choices']
                if isinstance(value, list):
                    out[f'{path.stem}.{key}'] = value
    return out


def expand(field, lists, where):
    """A field as EspoCRM takes it: an enum naming a list gets its options and labels (and
    those of `add`, first: a pack's own options on another pack's list)."""
    if 'list' not in field:
        return dict(field)
    f = {k: v for k, v in field.items() if k not in ('list', 'blank', 'add')}
    if field['list'] not in lists:
        raise ValueError(f'{where}: no list {field["list"]!r} (a pack it requires has it?)')
    opts = {**field.get('add', {}), **{c['code']: c['label'] for c in lists[field['list']]}}
    f.setdefault('type', 'enum')
    blank = field.get('blank', f['type'] == 'enum')
    return {'type': f.pop('type'), 'options': ([''] if blank else []) + list(opts), 'translatedOptions': opts, **f}


def merge_ordered(lists):
    """Ordered lists from several packs: entries in order, an entry {name, before} in front
    of `before` (or at the end if that isn't there)."""
    out = []
    for items in lists:
        for item in items:
            name, before = (item, None) if isinstance(item, str) else (item['name'], item.get('before'))
            if name in out:
                continue
            out.insert(out.index(before), name) if before in out else out.append(name)
    return out


def formula_value(v):
    return "'" + str(v).replace('\\', '\\\\').replace("'", "\\'") + "'"


def fill(text, params, where):
    """A pack's formula with its parameters: {{name}} a quoted string, {{pick name $var}}
    an expression choosing a table's value by $var's value (its "default" otherwise)."""
    def one(m):
        parts = m.group(1).split()
        if parts[0] == 'pick' and len(parts) == 3:
            table = params.get(parts[1]) or {}
            if not isinstance(table, dict):
                raise ValueError(f'{where}: {{{{pick {parts[1]} ...}}}} needs a table')
            expr = formula_value(table.get('default', ''))
            for key, value in reversed([(k, v) for k, v in table.items() if k != 'default']):
                expr = f"ifThenElse({parts[2]} == {formula_value(key)}, {formula_value(value)}, {expr})"
            return expr
        if len(parts) == 1:
            if parts[0] not in params:
                raise ValueError(f'{where}: no parameter {parts[0]!r} (the pack\'s [params] or the instance\'s)')
            return formula_value(params[parts[0]])
        raise ValueError(f'{where}: {{{{{m.group(1)}}}}}?')
    return re.sub(r'\{\{\s*([^}]+?)\s*\}\}', one, text)


def load(names, packs_dir=PACKS, params=None):
    """The packs (and what they require), merged into one spec for apply(). `params`: the
    instance's, by pack ({"cso": {...}}), over each pack's own [params]."""
    packs = order(names, packs_dir)
    for name in packs:  # meant for separate instances; staging has every pack to test them
        clash = [c for c in read(name, packs_dir).get('conflicts', []) if c in packs]
        if clash:
            print(f'warning: {name} and {", ".join(clash)} are meant for separate instances '
                  f'(both write the same records\' teams)', file=sys.stderr)
    lists = lists_of(packs, packs_dir)
    spec = {'packs': packs, 'lists': lists, 'entities': {}, 'fields': {}, 'links': [], 'codes': {}, 'teams': [],
            'roles': {}, 'users': [], 'layouts': {}, 'data': [], 'removed': {'fields': {}, 'links': []},
            'settings': {'assignment_notifications': [], 'global_search': []}, 'formulas': {}, 'agents': [], 'tabs': [],
            'migrations': [], 'agent_entities': {}, 'agent_guarded': [], 'task_parents': [],
            'metadata': {}, 'portal_roles': {}, 'portals': [], 'traits': {}, 'link_labels': {}}
    ordered = {}
    for name in packs:
        p, d = read(name, packs_dir), packs_dir / name
        for ent, e in p.get('entities', {}).items():
            if ent in spec['entities']:
                raise ValueError(f'{name}: entity {ent} is also {spec["entities"][ent]["pack"]}\'s')
            spec['entities'][ent] = {**{k: v for k, v in e.items() if k != 'fields'}, 'pack': name,
                                     'fields': {f: expand(v, lists, f'{name} {ent}.{f}') for f, v in e.get('fields', {}).items()}}
        for ent, fields in p.get('fields', {}).items():
            spec['fields'].setdefault(ent, {}).update({f: expand(v, lists, f'{name} {ent}.{f}') for f, v in fields.items()})
        spec['links'] += [tuple(x) for x in p.get('links', [])]
        spec['link_labels'].update(p.get('link_labels', {}))
        spec['codes'].update(p.get('codes', {}))
        spec['teams'] += [t for t in p.get('teams', []) if t not in spec['teams']]
        for role, r in p.get('roles', {}).items():
            have = spec['roles'].setdefault(role, {'data': {}, 'fieldData': {}, 'packs': []})
            have['packs'].append(name)
            for ent, access in r.get('data', {}).items():
                if ent in have['data'] and have['data'][ent] != access:
                    raise ValueError(f'{name}: role {role}: {ent} access differs from another pack\'s')
                have['data'][ent] = access
            have['fieldData'].update(r.get('fieldData', {}))
            for k in PERMISSIONS:
                if k in r:
                    if k in have and have[k] != r[k]:
                        raise ValueError(f'{name}: role {role}: {k} differs from another pack\'s')
                    have[k] = r[k]
        spec['users'] += p.get('users', [])
        for ent, lay in p.get('layouts', {}).items():
            have = spec['layouts'].setdefault(ent, {'detail': [], 'filters': []})
            have['detail'] += lay.get('detail', [])
            have['filters'] += lay.get('filters', [])
            for k in ('list', 'list_link', 'entity'):
                if k in lay:
                    have[k] = lay[k]
            for k in ('relationships', 'kanban'):
                if k in lay:
                    ordered.setdefault((ent, k), []).append(lay[k])
        for k in ('assignment_notifications', 'global_search'):
            spec['settings'][k] += [x for x in p.get('settings', {}).get(k, []) if x not in spec['settings'][k]]
        if p.get('tabs'):  # its group in the navigation: { label, entities }
            spec['tabs'].append(p['tabs'])
        spec['data'] += [{**x, 'pack': name} for x in p.get('data', [])]
        spec['removed']['links'] += [tuple(x) for x in p.get('removed', {}).get('links', [])]
        for ent, fields in p.get('removed', {}).get('fields', {}).items():
            spec['removed']['fields'].setdefault(ent, []).extend(fields)
        for kind, scopes in p.get('metadata', {}).items():
            for scope, value in scopes.items():
                spec['metadata'].setdefault(kind, {}).setdefault(scope, {}).update(value)
        spec['portal_roles'].update(p.get('portal_roles', {}))
        spec['portals'] += p.get('portals', [])
        spec['agent_entities'].update(p.get('agent_entities', {}))
        spec['agent_guarded'] += p.get('agent_guarded', [])
        spec['task_parents'] += p.get('task_parents', [])
        for ent, t in p.get('traits', {}).items():  # inherits, teams_down and checks add up; the others are one pack's
            have = spec['traits'].setdefault(ent, {})
            for k, v in t.items():
                if k in ('inherit', 'teams_down'):
                    have.setdefault(k, []).extend(v)
                elif k == 'checks':
                    have.setdefault(k, {}).update(v)
                elif k in have:
                    raise ValueError(f'{name}: {ent}: trait {k} is also another pack\'s')
                else:
                    have[k] = v
        mine = {**p.get('params', {}), **((params or {}).get(name) or {})}
        spec.setdefault('params', {})[name] = mine
        for path in sorted((d / 'formulas').glob('*.formula')):
            ent, kind = path.stem.split('.')
            spec['formulas'].setdefault(ent, {}).setdefault(kind, []).append(fill(path.read_text(), mine, f'{name} {path.name}'))
        if (d / 'agents.json').exists():
            spec['agents'] += json.loads((d / 'agents.json').read_text())
        if (d / 'migrate.py').exists():
            spec['migrations'].append(d / 'migrate.py')
    for (ent, k), parts in ordered.items():
        spec['layouts'][ent][k] = merge_ordered(parts)
    for ent, t in spec['traits'].items():
        if 'suggest_leads' in t:  # the trait reads its list's entries
            name = t['suggest_leads'].get('list')
            if name not in lists:
                raise ValueError(f'{ent}: suggest_leads: no list {name!r}')
            t['suggest_leads'] = {**t['suggest_leads'], 'entries': lists[name]}
        own = spec['entities'].get(ent[1:]) if ent.startswith('C') else None
        traits.check(ent, t, own['fields'] if own else None)
    # The agents' "Works on" and Tools: from the packs' entities and agents/tools.py
    agent = spec['entities'].get('Agent')
    if agent:
        agent['fields']['entity'].update(options=list(spec['agent_entities']), translatedOptions=dict(spec['agent_entities']))
        agent['fields']['tools']['options'] = [*agent_tools.TOOLS, *sorted(agent_tools.SERVER_TOOLS)]
    return spec


# --- applying ---------------------------------------------------------------------------------

class Admin:
    """The admin API, with EspoCRM's metadata writes retried once on a 500: its own jobs
    rebuilding the cache make a write fail now and then ("Error while clearing cache").
    Labels (I18n) read once per run, to write only what differs."""

    def __init__(self, espo):
        self.espo, self._i18n, self._meta = espo, None, {}

    def metadata(self, key):
        """Metadata read once per run (entity definitions, scopes); a write forgets it."""
        if key not in self._meta:
            self._meta[key] = self.espo.call('GET', '/Metadata', {'key': key}) or {}
        return self._meta[key]

    def __getattr__(self, name):
        return getattr(self.espo, name)

    def call(self, method, path, *args, **kw):
        if method != 'GET':
            self._meta.clear()
        try:
            return self.espo.call(method, path, *args, **kw)
        except Exception as e:
            if method == 'GET' or getattr(e, 'status', None) != 500 or not path.startswith(('/Admin/', '/EntityManager/')):
                raise
            print(f'retry: {method} {path} ({e})')
            time.sleep(5)
            return self.espo.call(method, path, *args, **kw)

    def i18n(self, refresh=False):
        if self._i18n is None or refresh:
            self._i18n = self.espo.call('GET', '/I18n')
        return self._i18n


def metadata(espo, key):
    if isinstance(espo, Admin):
        return espo.metadata(key)
    return espo.call('GET', '/Metadata', {'key': key}) or {}


def same_field(espo, entity, full, have, body):
    """Is the field already as `body` says? Labels, option labels and tooltips are in
    EspoCRM's I18n, the rest in its entity definitions. Unsure means no (it's written)."""
    lang = (espo.i18n() if isinstance(espo, Admin) else espo.call('GET', '/I18n')).get(entity) or {}
    for k, v in body.items():
        if k == 'label':
            ok = (lang.get('fields') or {}).get(full) == v
        elif k == 'translatedOptions':
            got = (lang.get('options') or {}).get(full) or {}
            ok = all(got.get(o) == t for o, t in v.items() if o != '')
        elif k == 'tooltipText':
            ok = (lang.get('tooltips') or {}).get(full) == v
        else:
            ok = have.get(k) == v or (v is False and k not in have)
        if not ok:
            return False
    return True


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


def every(espo, entity, select, **where):
    """All records of an entity, 200 a page (EspoCRM's most)."""
    out, offset = [], 0
    while True:
        page = espo.call('GET', f'/{entity}', {'maxSize': 200, 'offset': offset, 'select': select, **where})['list']
        out += page
        offset += 200
        if len(page) < 200:
            return out


def code_field(entity):
    return 'code' if entity.startswith('C') and entity not in ('Case', 'Contact') else 'cCode'


def link_label(link, labels=None):
    """leadOrganisation -> "Lead organisation", as the fields' labels are; or a pack's own
    (`link_labels`, by link name: e.g. coLeads = "Co-leads")."""
    if labels and link in labels:
        return labels[link]
    words = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', link).split(' ')
    return ' '.join([words[0].capitalize()] + [w.lower() for w in words[1:]])


def ensure_field(espo, entity, name, spec):
    defs = metadata(espo, f'entityDefs.{entity}.fields')
    # Custom fields of EspoCRM's own entities get a "c" prefix; a custom entity's don't
    custom = metadata(espo, f'scopes.{entity}').get('isCustom')
    full = name if custom else 'c' + name[0].upper() + name[1:]
    body = {'label': spec.get('label', name[0].upper() + name[1:]), **{k: v for k, v in spec.items() if k != 'label'}}
    if full in defs:
        if same_field(espo, entity, full, defs[full], body):
            return full
        espo.call('PUT', f'/Admin/fieldManager/{entity}/{full}', body=body)
        print(f'field updated: {entity}.{full}')
    else:
        espo.call('POST', f'/Admin/fieldManager/{entity}', body={'name': name, **body})
        print(f'field created: {entity}.{full}')
    return full


def ensure_entities(espo, spec):
    scopes = metadata(espo, 'scopes')
    for name, e in spec['entities'].items():
        if f'C{name}' not in scopes:
            espo.call('POST', '/EntityManager/action/createEntity', body={
                'name': name, 'type': 'Base', 'labelSingular': e.get('label', name), 'labelPlural': e['labelPlural'],
                'stream': e.get('stream', True), 'iconClass': e['iconClass']})
            print(f'entity created: C{name}')
        status = e.get('statusField', 'status' if 'status' in e['fields'] else None)
        if status and scopes.get(f'C{name}', {}).get('statusField') != status:
            espo.call('POST', '/EntityManager/action/updateEntity', body={'name': f'C{name}', 'statusField': status})
        for field, fspec in e['fields'].items():
            ensure_field(espo, f'C{name}', field, fspec)
    i18n = None
    label = lambda name: link_label(name, spec['link_labels'])  # noqa: E731
    for entity, link, foreign, link_foreign, kind, *relation in spec['links']:
        if link not in metadata(espo, f'entityDefs.{entity}.links'):
            espo.call('POST', '/EntityManager/action/createLink', body={
                'entity': entity, 'link': link, 'linkForeign': link_foreign, 'entityForeign': foreign,
                'linkType': kind, 'label': label(link), 'labelForeign': label(link_foreign),
                **({'linkMultipleField': True} if kind == 'manyToMany' else {}),  # its field on the record (participantsIds)
                'relationName': relation[0] if relation else None})
            print(f'link created: {entity}.{link} -> {foreign}.{link_foreign}')
        elif kind == 'manyToMany' and link not in metadata(espo, f'entityDefs.{entity}.fields'):
            espo.call('POST', '/EntityManager/action/updateLink', body={
                'entity': entity, 'link': link, 'entityForeign': foreign, 'linkForeign': link_foreign,
                'linkMultipleField': True})
            print(f'link field: {entity}.{link}')
            continue
        i18n = i18n or espo.call('GET', '/I18n')
        # On EspoCRM's own entities a custom link's name gets a "c" (Task.cResponse)
        on_foreign = link_foreign if foreign[0] == 'C' and foreign[1].isupper() else 'c' + link_foreign[0].upper() + link_foreign[1:]
        if any(((i18n.get(e) or {}).get('links') or {}).get(name) != label(label_of)
               for e, name, label_of in ((entity, link, link), (foreign, on_foreign, link_foreign))):  # made before
            espo.call('POST', '/EntityManager/action/updateLink', body={  # labels were split into words
                'entity': entity, 'link': link, 'entityForeign': foreign, 'linkForeign': on_foreign,
                'label': label(link), 'labelForeign': label(link_foreign)})
            print(f'link labels: {entity}.{link} "{label(link)}", {foreign}.{link_foreign} "{label(link_foreign)}"')


def remove_obsolete(espo, spec):
    for entity, link in spec['removed']['links']:
        if link in metadata(espo, f'entityDefs.{entity}.links'):
            espo.call('POST', '/EntityManager/action/removeLink', body={'entity': entity, 'link': link})
            print(f'link removed: {entity}.{link}')
    for entity, names in spec['removed']['fields'].items():
        defs = metadata(espo, f'entityDefs.{entity}.fields')
        for name in names:
            if name in defs:
                espo.call('DELETE', f'/Admin/fieldManager/{entity}/{name}')
                print(f'field removed: {entity}.{name}')


def ensure_codes(espo, spec):
    for entity in spec['codes']:
        ensure_field(espo, entity, 'code', CODE_FIELD)
        filters = metadata(espo, f'entityDefs.{entity}.collection').get('textFilterFields') or ['name']
        if code_field(entity) not in filters:  # found by its code in the list's search box
            espo.call('POST', '/EntityManager/action/updateEntity',
                      body={'name': entity, 'textFilterFields': filters + [code_field(entity)]})


def ensure_task_board(espo, spec):
    status = metadata(espo, 'entityDefs.Task.fields.status')
    espo.call('PUT', '/Admin/fieldManager/Task/status', body={
        'type': 'enum', 'options': TASK_STATUS, 'translatedOptions': TASK_LABELS, 'default': 'Backlog',
        'style': {**status.get('style', {}), 'Blocked': 'danger', 'Backlog': 'default'},
        'notActualOptions': ['Completed', 'Canceled', 'Deferred']})
    espo.call('POST', '/EntityManager/action/updateEntity', body={
        'name': 'Task', 'kanbanViewMode': True, 'statusField': 'status',
        'kanbanStatusIgnoreList': ['Canceled', 'Deferred']})
    print('Task: board columns, Kanban on')
    # A task's parent (EspoCRM's own "Parent" field, which takes a Case already) can be one
    # of the packs' records too (task_parents); they get a Tasks panel
    parent = metadata(espo, 'entityDefs.Task.fields.parent')
    ours = spec['task_parents']
    if ours and not set(ours) <= set(parent.get('entityList', [])):
        espo.call('POST', '/EntityManager/action/updateLink', body={
            'entity': 'Task', 'link': 'parent', 'linkForeign': 'tasks',
            'parentEntityTypeList': sorted(set(parent.get('entityList', [])) | set(ours)), 'foreignLinkEntityTypeList': ours})
        print(f'Task: a parent can be {", ".join(ours)}')


def scripts(spec):
    """Each entity's scripts from the packs: their blocks for it in `requires` order, and in
    its Before Save Custom Script its traits' snippets (espo/traits.py)."""
    by_entity = {e: {k: '\n'.join(blocks) for k, blocks in s.items()} for e, s in spec['formulas'].items()}
    extra = traits.derived(spec['traits'])
    for entity in {*spec['traits'], *extra}:
        blocks = spec['formulas'].get(entity, {}).get('beforeSaveCustomScript', [])
        by_entity.setdefault(entity, {})['beforeSaveCustomScript'] = traits.script(
            entity, blocks, spec['traits'].get(entity, {}), extra.get(entity))
    return by_entity


def ensure_formulas(espo, spec):
    """Each entity's scripts (scripts()); the short code (_code.formula) first in the Before
    Save Custom Script of each entity with a code, and the agent guard (_agent-guard.formula)
    first in the API Before Save Script of the agent_guarded (its stage block only where the
    entity has a stage)."""
    by_entity = scripts(spec)
    guard = (FORMULA / '_agent-guard.formula').read_text()
    code = (FORMULA / '_code.formula').read_text()
    for entity, prefix in spec['codes'].items():
        mine = by_entity.setdefault(entity, {})
        snippet = code.replace('FIELD', code_field(entity)).replace('PREFIX', prefix).replace('ENTITY', entity)
        mine['beforeSaveCustomScript'] = snippet + '\n' + mine.get('beforeSaveCustomScript', '')
    for entity in spec['agent_guarded']:
        g = guard
        if 'stage' not in metadata(espo, f'entityDefs.{entity}.fields'):
            g = re.sub(r'\n *// stage:begin.*?// stage:end\n', '\n', g, flags=re.S)
        mine = by_entity.setdefault(entity, {})
        mine['beforeSaveApiScript'] = g + '\n' + mine.get('beforeSaveApiScript', '')
    have = metadata(espo, 'formula')
    for entity, mine in by_entity.items():
        if all((have.get(entity) or {}).get(k) == v for k, v in mine.items()):
            continue
        espo.call('POST', '/EntityManager/action/formula', body={'scope': entity, 'data': mine})
        print(f'formula: {entity} ({", ".join(mine)})')


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


def put_layout(espo, entity, kind, body):
    if espo.call('GET', f'/{entity}/layout/{kind}') != body:
        espo.call('PUT', f'/{entity}/layout/{kind}', body=body)


def ensure_layouts(espo, spec):
    """Per entity: detail fields (each group added if missing), the list's columns, the
    relationship panels, a board's card, filters (added to EspoCRM's), board options."""
    for entity, lay in spec['layouts'].items():
        for group in lay['detail']:
            ensure_layout_fields(espo, entity, group)
        if 'list' in lay:
            link = set(lay.get('list_link', ['name']))
            put_layout(espo, entity, 'list', [{'name': n, **({'link': True} if n in link else {})} for n in lay['list']])
        if 'relationships' in lay:
            put_layout(espo, entity, 'relationships', [{'name': n} for n in lay['relationships']])
        if 'kanban' in lay:
            put_layout(espo, entity, 'kanban', [{'name': n, **({'link': True} if n == 'name' else {})} for n in lay['kanban']])
        if lay['filters']:
            defs = metadata(espo, f'entityDefs.{entity}.fields')
            espo.call('PUT', f'/{entity}/layout/filters',  # (without fields that don't exist, e.g. from an earlier run)
                      body=sorted(f for f in set(espo.call('GET', f'/{entity}/layout/filters') or []) | set(lay['filters']) if f in defs))
        if 'entity' in lay:
            espo.call('POST', '/EntityManager/action/updateEntity', body={'name': entity, **lay['entity']})
    for entity in spec['codes']:
        ensure_layout_fields(espo, entity, [code_field(entity)])
    print(f'layouts: {len(spec["layouts"])} entities')


def backfill_codes(espo, spec):
    """Records made before they had codes: saved once, so the formula gives them one (the
    field is read-only: the API can't set it)."""
    for entity in spec['codes']:
        field, done = code_field(entity), set()
        while True:
            rows = espo.call('GET', f'/{entity}', {'maxSize': 100, 'select': 'id,name',
                                                   'where[0][type]': 'isNull', 'where[0][attribute]': field})['list']
            rows = [r for r in rows if r['id'] not in done]
            if not rows:
                break
            for r in rows:
                espo.call('PUT', f'/{entity}/{r["id"]}', body={'name': r['name']})
                done.add(r['id'])
            print(f'codes: {entity} +{len(rows)}')


def ensure_settings(espo, spec, application_name=None):
    settings = espo.call('GET', '/Settings')
    s = spec['settings']
    body = {'assignmentNotificationsEntityList': sorted(set(settings.get('assignmentNotificationsEntityList') or [])
                                                        | set(s['assignment_notifications'])),
            # In global search, so the isolation tests (T8) search them too
            'globalSearchEntityList': sorted(set(settings.get('globalSearchEntityList') or []) | set(s['global_search']))}
    if application_name:
        body['applicationName'] = application_name
    # Each pack's group in the navigation, before EspoCRM's delimiter (what's after it is in
    # the "more" menu): a divider with its label, then its entities, moved there if elsewhere
    tabs = list(settings.get('tabList') or [])
    for group in spec['tabs']:
        mine = group['entities']
        if any(isinstance(t, dict) and t.get('text') == group['label'] for t in tabs):
            continue
        tabs = [t for t in tabs if t not in mine]
        at = tabs.index('_delimiter_') if '_delimiter_' in tabs else len(tabs)
        tabs[at:at] = [{'type': 'divider', 'text': group['label'], 'id': hashlib.md5(group['label'].encode()).hexdigest()[:6]}, *mine]
        body['tabList'] = tabs
    espo.call('PUT', '/Settings', body=body)
    print(f'settings: assignment notifications for {", ".join(s["assignment_notifications"])}; global search')


def load_data(espo, spec):
    """[[data]]: reference records from a file (or a pack's list), matched on a field; only
    what differs is written. With `sync_by`, the file holds every record of each value of
    that field (a country's admin areas): records of that value not in it are removed."""
    for d in spec['data']:
        pack_dir = PACKS / d['pack']
        if 'list' in d:
            sources = [(d['list'], spec['lists'][d['list']])]
        else:
            sources = [(p.name, json.loads(p.read_text())) for p in sorted(pack_dir.glob(d['file']))]
        for label, rows in sources:
            fmap = d.get('map')
            want = {}
            for r in rows:
                body = {k: (r.get(v) or '') for k, v in fmap.items()} if fmap else dict(r)
                want[body[d['match']]] = body
            if not want:
                continue
            select = ','.join(dict.fromkeys(['id', d['match'], *next(iter(want.values()))]))
            where = {}
            if d.get('sync_by'):
                value = next(iter(want.values()))[d['sync_by']]
                where = {'where[0][type]': 'equals', 'where[0][attribute]': d['sync_by'], 'where[0][value]': value}
            have = {r[d['match']]: r for r in every(espo, d['entity'], select, **where)}
            written = 0
            for key, body in want.items():
                if key not in have:
                    espo.call('POST', f'/{d["entity"]}', body=body, headers={'X-Skip-Duplicate-Check': 'true'})
                    written += 1
                elif any(have[key].get(k) != v for k, v in body.items()):
                    espo.call('PUT', f'/{d["entity"]}/{have[key]["id"]}', body=body)
                    written += 1
            gone = set(have) - set(want) if d.get('sync_by') else set()
            for key in gone:
                espo.call('DELETE', f'/{d["entity"]}/{have[key]["id"]}')
            print(f'data {d["entity"]} ({label}): {len(want)}, {written} written' + (f', {len(gone)} removed' if gone else ''))


def ensure_roles(espo, spec):
    """Each role: the packs' access to it, merged; access to entities no pack here defines
    (a Kobo connection's, granted through the bridge's MCP) is kept."""
    roles = {}
    for name, r in spec['roles'].items():
        if not any(k in r for k in PERMISSIONS):
            print(f'role {name}: only extended ({", ".join(r["packs"])}), not defined by a pack here: skipped')
            continue
        body = {k: r[k] for k in PERMISSIONS if k in r}
        have = find(espo, 'Role', 'name', name)
        have = espo.call('GET', f'/Role/{have["id"]}') if have else {}
        mine = set(r['data'])
        data = {**{e: v for e, v in (have.get('data') or {}).items() if e not in mine}, **r['data']}
        fields = {**{e: v for e, v in (have.get('fieldData') or {}).items() if e not in mine}, **r['fieldData']}
        roles[name] = ensure(espo, 'Role', 'name', name, {'name': name, **body, 'data': data, 'fieldData': fields},
                             update=True)['id']
    return roles


def make_agent(espo, spec, teams):
    """An Agent and its routes from a spec as in a pack's agents.json: route targets by name
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


MODULE = 'KoboWorkflows'


def module_zip(spec):
    """The packs' metadata as an EspoCRM extension: (zip bytes, its contents' hash)."""
    files = {f'files/custom/Espo/Modules/{MODULE}/Resources/module.json': json.dumps({'order': 40})}
    for kind, scopes in sorted(spec['metadata'].items()):
        for scope, value in sorted(scopes.items()):
            files[f'files/custom/Espo/Modules/{MODULE}/Resources/metadata/{kind}/{scope}.json'] = json.dumps(value, indent=1, sort_keys=True)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    manifest = {'name': 'Kobo workflows', 'version': f'1.0.{int(time.time())}', 'acceptableVersions': ['>=8.0.0'],
                'author': 'kobo-espo', 'releaseDate': time.strftime('%Y-%m-%d'),
                'description': f'Metadata of the workflow packs ({", ".join(spec["packs"])}). Contents {digest}'}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, indent=1))
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue(), digest


def ensure_module(espo, spec):
    """Install the packs' metadata (KoboWorkflows) if what's installed has other contents.
    Needs the instance's adminExtensionUpload (deploy/up.sh sets it)."""
    if not spec['metadata']:
        return
    data, digest = module_zip(spec)
    have = [x for x in espo.call('GET', '/Extension', {'maxSize': 50})['list'] if x.get('name') == 'Kobo workflows' and x.get('isInstalled')]
    if any(digest in (x.get('description') or '') for x in have):
        return
    raw = espo.espo if isinstance(espo, Admin) else espo
    req = urllib.request.Request(raw.base + '/Extension/action/upload', method='POST',
                                 data=('data:application/zip;base64,' + base64.b64encode(data).decode()).encode(),
                                 headers={**raw.headers, 'Content-Type': 'application/zip', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        uploaded = json.loads(r.read())
    espo.call('POST', '/Extension/action/install', body={'id': uploaded['id']})
    print(f'module: {MODULE} {uploaded["version"]} installed ({", ".join(f"{k} {", ".join(v)}" for k, v in spec["metadata"].items())})')


def ensure_portal_roles(espo, spec):
    ids = {}
    for name, r in spec['portal_roles'].items():
        ids[name] = ensure(espo, 'PortalRole', 'name', name, {'name': name, **r}, update=True)['id']
    return ids


def ensure_portals(espo, spec, portal_roles):
    """A portal by its name: its URL's customId, tabs, roles; made or brought to this."""
    for p in spec['portals']:
        body = {k: v for k, v in p.items() if k != 'roles'}
        body['portalRolesIds'] = [portal_roles[r] for r in p.get('roles', [])]
        body.setdefault('isActive', True)
        ensure(espo, 'Portal', 'name', p['name'], body, update=True)
        print(f'portal: {p["name"]} (/portal/{p.get("customId", "")})')


def ensure_agents(espo, spec, teams):
    """The packs' example agents, made if missing, in their mode there (dry run or off):
    what someone changed on an agent since isn't overwritten."""
    for a in spec['agents']:
        if find(espo, 'CAgent', 'name', a['name']):
            continue
        make_agent(espo, a, teams)
        print(f'agent created: {a["name"]}')


def ensure_users(espo, spec, teams, roles):
    """The packs' test users, their passwords in secrets/seed.secrets (kept across runs). A
    user's teams that no pack here has are left out."""
    path = ROOT / 'secrets' / 'seed.secrets'
    have = read_secrets('seed')
    out = dict(have)
    for u in spec['users']:
        first, last = u['name'].split(' ', 1)
        key = pw_key(u['username'])
        password = have.get(key) or secrets.token_urlsafe(14)
        team_ids = [teams[t] for t in u['teams'] if t in teams]
        body = {'userName': u['username'], 'firstName': first, 'lastName': last, 'type': 'regular',
                'isActive': True, 'rolesIds': [roles[u['role']]], 'teamsIds': team_ids,
                'defaultTeamId': team_ids[0], 'emailAddress': f'delivered+{u["username"]}@resend.dev'}
        user = find(espo, 'User', 'userName', u['username'])
        if user is None:
            espo.call('POST', '/User', body={**body, 'password': password})
            print(f'user created: {u["username"]} ({u["role"]}; {", ".join(u["teams"])})')
        else:  # teams and roles as defined here; the password too if it was lost
            espo.call('PUT', f'/User/{user["id"]}', body={**body, **({} if key in have else {'password': password})})
        out[key] = password
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(''.join(f'{k}={v}\n' for k, v in out.items()))
    path.chmod(0o600)
    print(f'users: {len(spec["users"])}, passwords in {path.relative_to(ROOT)}')


def migrate(espo, spec):
    for path in spec['migrations']:
        ns = {}
        exec(compile(path.read_text(), str(path), 'exec'), ns)
        ns['migrate'](espo)
        print(f'migrate: {path.parent.name}')


def apply(espo, spec, users=False, application_name=None, email=None):
    """Make EspoCRM as the packs say. `email` is the core's ensure_email (secrets/resend.key)."""
    espo = espo if isinstance(espo, Admin) else Admin(espo)
    ensure_settings(espo, spec, application_name)
    if email:
        email(espo)
    ensure_entities(espo, spec)
    remove_obsolete(espo, spec)
    for entity, fields in spec['fields'].items():
        for name, fspec in fields.items():
            ensure_field(espo, entity, name, fspec)
    ensure_codes(espo, spec)
    ensure_task_board(espo, spec)
    ensure_formulas(espo, spec)
    ensure_layouts(espo, spec)
    ensure_module(espo, spec)
    backfill_codes(espo, spec)
    load_data(espo, spec)
    migrate(espo, spec)
    teams = {name: ensure(espo, 'Team', 'name', name, {'name': name})['id'] for name in spec['teams']}
    roles = ensure_roles(espo, spec)
    print(f'teams: {len(teams)}, roles: {", ".join(roles)}')
    ensure_portals(espo, spec, ensure_portal_roles(espo, spec))
    ensure_agents(espo, spec, teams)
    if users:
        ensure_users(espo, spec, teams, roles)
