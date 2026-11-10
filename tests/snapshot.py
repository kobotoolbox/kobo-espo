#!/usr/bin/env python3
"""What the seed makes in EspoCRM, in a stable order, so that two runs can be compared
(plans/workflow-packs-plan.md, "Checking it changed nothing"):

    python3 -I tests/snapshot.py OUT.json
    diff <(python3 -m json.tool before.json) <(python3 -m json.tool after.json)

Dumps: the custom entities' scopes and entity definitions (fields, links), the custom
fields of EspoCRM's own entities (c-prefixed), Task's status and parent; their layouts
(detail, list, relationships, kanban, filters); formulas; roles; teams; the settings the
seed sets; the test users (roles, teams); agents and their routes; and how many reference
records there are (admin areas per country, organisations, standards). Never records'
personal data, keys or passwords.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import BridgeError, admin  # noqa: E402

OWN = ('Case', 'Contact', 'Account', 'Task', 'User', 'Team')
LAYOUTS = ('detail', 'list', 'relationships', 'kanban', 'filters')
SETTINGS = ('assignmentNotificationsEntityList', 'globalSearchEntityList', 'applicationName')
BRIDGE = ('cKobo',)  # what the bridge's setup adds, not the seed


def meta(espo, key):
    return espo.call('GET', '/Metadata', {'key': key}) or {}


def every(espo, entity, select, **params):
    out, offset = [], 0
    while True:
        page = espo.call('GET', f'/{entity}', {'maxSize': 200, 'offset': offset, 'select': select, **params})['list']
        out += page
        offset += 200
        if len(page) < 200:
            return out


def snapshot(espo):
    scopes = meta(espo, 'scopes')
    custom = sorted(s for s, v in scopes.items() if v.get('isCustom') and v.get('entity'))
    out = {'scopes': {s: {k: scopes[s].get(k) for k in ('stream', 'statusField', 'kanbanViewMode', 'kanbanStatusIgnoreList')}
                      for s in custom}, 'entities': {}, 'own': {}, 'layouts': {}, 'formulas': {}}
    for s in custom:
        defs = meta(espo, f'entityDefs.{s}')
        out['entities'][s] = {'fields': {f: v for f, v in sorted((defs.get('fields') or {}).items()) if not f.startswith(BRIDGE)},
                              'links': dict(sorted((defs.get('links') or {}).items())),
                              'textFilterFields': (defs.get('collection') or {}).get('textFilterFields')}
    for s in OWN:
        defs = meta(espo, f'entityDefs.{s}')
        out['own'][s] = {'fields': {f: v for f, v in sorted((defs.get('fields') or {}).items())
                                    if f.startswith('c') and f[1:2].isupper() and not f.startswith(BRIDGE)},
                         'links': {k: v for k, v in sorted((defs.get('links') or {}).items()) if k.startswith('c') and k[1:2].isupper()}}
    out['own']['Task']['status'] = meta(espo, 'entityDefs.Task.fields.status')
    out['own']['Task']['parent'] = meta(espo, 'entityDefs.Task.fields.parent')
    out['own']['Task']['scope'] = {k: scopes['Task'].get(k) for k in ('kanbanViewMode', 'statusField', 'kanbanStatusIgnoreList')}
    for s in custom + ['Task', 'Contact', 'Case']:
        out['layouts'][s] = {}
        for kind in LAYOUTS:
            try:
                out['layouts'][s][kind] = espo.call('GET', f'/{s}/layout/{kind}')
            except BridgeError:
                out['layouts'][s][kind] = None
    formula = meta(espo, 'formula')
    out['formulas'] = {s: formula[s] for s in sorted(formula)}
    out['roles'] = {r['name']: {k: r.get(k) for k in ('data', 'fieldData', 'assignmentPermission', 'userPermission',
                                                     'mentionPermission', 'exportPermission', 'massUpdatePermission')}
                    for r in sorted((espo.call('GET', f'/Role/{x["id"]}') for x in every(espo, 'Role', 'id')),
                                    key=lambda r: r['name']) if not r['name'].startswith(('Kobo ', 'Agent', 'Dashboard'))}
    out['teams'] = sorted(t['name'] for t in every(espo, 'Team', 'name'))
    settings = espo.call('GET', '/Settings')
    out['settings'] = {k: sorted(settings.get(k)) if isinstance(settings.get(k), list) else settings.get(k) for k in SETTINGS}
    out['users'] = {u['userName']: {'roles': sorted(u.get('rolesNames', {}).values()), 'teams': sorted(u.get('teamsNames', {}).values())}
                    for u in (espo.call('GET', f'/User/{x["id"]}') for x in every(espo, 'User', 'id', **{
                        'where[0][type]': 'equals', 'where[0][attribute]': 'type', 'where[0][value]': 'regular'}))}
    out['agents'] = {}
    for ag in every(espo, 'CAgent', 'id,name'):
        if ag['name'].startswith('Test: '):
            continue
        full = espo.call('GET', f'/CAgent/{ag["id"]}')
        routes = every(espo, 'CAgentRoute', 'id', **{'where[0][type]': 'equals', 'where[0][attribute]': 'agentId',
                                                     'where[0][value]': ag['id']})
        keep = [f for f in meta(espo, 'entityDefs.CAgent.fields') if f not in ('version', 'activeSince', 'mode')]
        out['agents'][ag['name']] = {
            'agent': {k: full.get(k) for k in sorted(keep) if k in full and not k.endswith(('Id', 'Ids', 'At'))},
            'teams': sorted((full.get('teamsNames') or {}).values()),
            'routes': sorted(({k: v for k, v in espo.call('GET', f'/CAgentRoute/{r["id"]}').items()
                               if k not in ('id', 'createdAt', 'modifiedAt', 'agentId', 'createdById', 'createdByName',
                                            'modifiedById', 'modifiedByName', 'assignUserId', 'assignAgentId', 'agentName')
                               and not k.endswith('Id')} for r in routes), key=lambda r: (r.get('order') or 0, r.get('name')))}
    counts = {}
    for area in every(espo, 'CAdminArea', 'country,level'):
        k = f'CAdminArea {area.get("country")} {area.get("level")}'
        counts[k] = counts.get(k, 0) + 1
    for entity in ('COrganisation', 'CStandard'):
        counts[entity] = espo.call('GET', f'/{entity}', {'maxSize': 1})['total']
    out['reference'] = dict(sorted(counts.items()))
    return out


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(json.dumps(snapshot(admin()), indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    print(path)
