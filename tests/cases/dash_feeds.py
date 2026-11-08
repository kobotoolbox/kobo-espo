#!/usr/bin/env python3
"""
D1-D5: the EspoCRM MCP's dashboard feeds (kobo-espo-bridge espo_mcp/tools.py; kobo-dash
plans/espo-source-plan.md, step 5): an API user per feed, which reads one team's records
of one entity, only the fields chosen, and writes nothing.

    python3 -I tests/cases/dash_feeds.py

Makes its own fixtures (a response "DASHF <run>" in team Response: Test EQ 1 with an ETC
and a WASH project, a site in each), removing them and the feed users at the end. Checks
with each feed user's own key, as kobo-dash reads. Writes tests/results/dash_feeds.json.
"""
import json
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
RESPONSE = f'DASHF {RUN} Hurricane'
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


def status(fn):
    try:
        fn()
        return 200
    except BridgeError as e:
        return e.status


def twice(fn, *args):
    first = fn(*args)
    return first, fn(*args, confirm=first['confirm'])


def key_of(a, user_name):
    u = by(a, 'User', 'userName', user_name)
    return a.call('GET', f'/User/{u[0]["id"]}')['apiKey'] if u else None


def main():
    a = admin()
    work = Path(tempfile.mkdtemp(prefix='dash-feeds-'))
    (work / 'token').write_text('unused')
    (work / 'bridge.secrets').write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
    inst = tools.Instance({'ESPO_URL': URL, 'BRIDGE_SECRETS': str(work / 'bridge.secrets'),
                           'KOBO_URL': 'http://127.0.0.1:9', 'KOBO_TOKEN_FILE': str(work / 'token')})
    made = {}
    try:
        run(a, inst, made)
    finally:
        for u in tools.list_dashboard_feeds(inst)['feeds']:
            if RUN.lower() in u['api_user'] or any(c.lower() in u['api_user'] for c in made.get('codes', [])):
                first = tools.remove_dashboard_feed(inst, u['api_user'])
                tools.remove_dashboard_feed(inst, u['api_user'], confirm=first['confirm'])
        for entity, rec in reversed(made.get('records', [])):
            a.call('DELETE', f'/{entity}/{rec["id"]}')
        for resp in by(a, 'CResponse', 'name', RESPONSE):
            for t in by(a, 'Task', 'cResponseId', resp['id']):
                a.call('DELETE', f'/Task/{t["id"]}')
            a.call('DELETE', f'/CResponse/{resp["id"]}')
    path = ROOT / 'tests' / 'results' / 'dash_feeds.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'dash_feeds: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


def run(a, inst, made):
    team = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
    eq1, etc, wash = team['Response: Test EQ 1'], team['Cluster: Test EQ 1 ETC'], team['Cluster: Test EQ 1 WASH']
    resp = a.call('POST', '/CResponse', body={'name': RESPONSE, 'status': 'Active', 'teamsIds': [eq1]})
    recs = made.setdefault('records', [])
    p_etc = a.call('POST', '/CProject', body={'name': f'DASHF {RUN} ETC', 'cluster': 'EMERGENCY_TELECOMS',
                                              'status': 'Active', 'responseId': resp['id'], 'teamsIds': [etc]})
    p_wash = a.call('POST', '/CProject', body={'name': f'DASHF {RUN} WASH', 'cluster': 'WASH', 'status': 'Active',
                                               'responseId': resp['id'], 'teamsIds': [wash]})
    recs += [('CProject', p_etc), ('CProject', p_wash)]
    s_etc = a.call('POST', '/CSite', body={'name': f'DASHF {RUN} VSAT hub', 'siteCode': f'DF-{RUN}-E',
                                           'projectId': p_etc['id'], 'status': 'operational', 'latitude': 18.0,
                                           'longitude': -76.8, 'equipment': 'Serial numbers: secret'})
    s_wash = a.call('POST', '/CSite', body={'name': f'DASHF {RUN} Water point', 'siteCode': f'DF-{RUN}-W',
                                            'projectId': p_wash['id'], 'status': 'needs_repair'})
    recs += [('CSite', s_etc), ('CSite', s_wash)]
    etc_code = a.call('GET', f'/CProject/{p_etc["id"]}')['code']
    resp_code = a.call('GET', f'/CResponse/{resp["id"]}')['code']
    made['codes'] = [etc_code, resp_code]
    fields = ['siteCode', 'status', 'latitude', 'longitude', 'project']

    # --- D1: what's refused, and the two calls -----------------------------------------------
    for entity, why in (('CFocalPoint', 'people'), ('Contact', 'people'), ('User', 'people')):
        check('D1', f'a feed of {entity}: refused', why in (refused(lambda: tools.create_dashboard_feed(
            inst, etc_code, entity, ['name'])) or ''))
    check('D1', 'a file field: refused', 'not for dashboards' in (refused(lambda: tools.create_dashboard_feed(
        inst, etc_code, 'CSite', ['photos'])) or ''))
    check('D1', 'a field that isn\'t there: refused', refused(lambda: tools.create_dashboard_feed(
        inst, etc_code, 'CSite', ['nope'])))
    first, done = twice(tools.create_dashboard_feed, inst, etc_code, 'CSite', fields)
    check('D1', "first call: what it would read (the ETC project's team), changing nothing",
          first.get('confirm_required') and 'ETC' in first['would_create']['reads'] and done.get('changed'), first)
    user_name = done['api_user']
    check('D1', 'its answer has no key: where to find it, and what to do next',
          'apiKey' not in json.dumps(done) and '#ApiUser/view/' in done['its_key'] and 'Never ask' in done['next'], done)

    # --- D2: what its key reads --------------------------------------------------------------
    key = key_of(a, user_name)
    feed = Espo(URL, api_key=key)
    me = feed.call('GET', '/App/user')['user']
    check('D2', 'an API user, not an admin (kobo-dash accepts it)', me.get('type') == 'api' and not me.get('isAdmin'), me)
    sites = feed.call('GET', '/CSite', {'maxSize': 200, 'select': 'name,siteCode,status,latitude,longitude,projectName,equipment'})['list']
    mine = [x for x in sites if x['name'].startswith(f'DASHF {RUN}')]
    check('D2', "its key reads the ETC project's sites only", [x['name'] for x in mine] == [s_etc['name']],
          [x['name'] for x in mine])
    check('D2', 'with the fields chosen, not the others (equipment)', mine and mine[0].get('status') == 'operational'
          and mine[0].get('latitude') == 18.0 and 'equipment' not in mine[0], mine[:1])
    check('D2', "another entity's records refused (CActivity)", status(lambda: feed.call('GET', '/CActivity', {'maxSize': 1})) == 403)
    check('D2', 'writes nothing: editing its own site refused',
          status(lambda: feed.call('PUT', f'/CSite/{s_etc["id"]}', body={'status': 'planned'})) == 403)
    defs = feed.call('GET', '/Metadata', {'key': 'entityDefs.CSite.fields'}) or {}
    labels = ((feed.call('GET', '/I18n') or {}).get('CSite') or {}).get('options') or {}
    check('D2', "it reads CSite's metadata and option labels (kobo-dash makes its columns from them)",
          'status' in defs and labels.get('status', {}).get('operational') == 'Operational',
          {'fields': len(defs), 'labels': list(labels)[:5]})

    # --- D3: a response's feed reads all its projects -------------------------------------------
    first, done = twice(tools.create_dashboard_feed, inst, resp_code, 'CSite', ['siteCode', 'status'])
    whole = Espo(URL, api_key=key_of(a, done['api_user']))
    got = {x['name'] for x in whole.call('GET', '/CSite', {'maxSize': 200, 'select': 'name'})['list']
           if x['name'].startswith(f'DASHF {RUN}')}
    check('D3', "a response's feed (its coordinators' team) reads every project's sites",
          got == {s_etc['name'], s_wash['name']}, got)
    check('D3', 'a second feed for the same scope and entity: refused (remove it first)',
          refused(lambda: tools.create_dashboard_feed(inst, resp_code, 'CSite', ['status'])))

    # --- D4: listed, and removed -----------------------------------------------------------------
    listed = [u['api_user'] for u in tools.list_dashboard_feeds(inst)['feeds']]
    check('D4', 'list_dashboard_feeds: both', {user_name, done['api_user']} <= set(listed), listed)
    first, gone = twice(tools.remove_dashboard_feed, inst, user_name)
    check('D4', 'removed: the user and its role gone, its key refused at once',
          gone.get('changed') and not by(a, 'User', 'userName', user_name)
          and not by(a, 'Role', 'name', f'Dashboard feed: {p_etc["name"]} · CSite')
          and status(lambda: feed.call('GET', '/App/user')) == 401, gone)
    check('D4', 'remove_dashboard_feed: only feed users (not the bridge\'s)',
          refused(lambda: tools.remove_dashboard_feed(inst, 'kobo-sites')))


if __name__ == '__main__':
    main()
