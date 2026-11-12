"""The response's 5W dashboard (site/pages/fivew.html, "Dashboard") on a local kobo-dash,
from the test droplet's EspoCRM: one dashboard, three pages (the 5W, the 3W across
clusters for the ICCG, the organisations by cluster), on two EspoCRM feeds
(site/dash-fivew-feeds.py makes their users) read in the response's team, for the demo
response (site/demo-data.py, site/demo-fivew-people.py).

Run in kobo-dash's environment, with its settings in an env file (DATABASE_URL, PUBLIC_URL,
MCP_URL, DASH_PUBLIC_KEY and SIGNING_KEY, its Ed25519 pair, SECRET_KEY, CRED_KEYS):

    cd ../kobo-dash; set -a; . <env file>; set +a
    PYTHONPATH=src uv run python ../kobo-espo/site/dash-fivew.py

ASSET: the 5W activity report project on the Kobo test account (a dashboard belongs to a
Kobo project; its data here is EspoCRM's). BOUNDARIES: Jamaica's parishes from the geocoder
(espo/seed/admin_areas.py JM --boundaries DIR), the P-codes EspoCRM has.
Keys come from secrets/dash-fivew.json and are never printed.
"""
import asyncio
import base64
import json
import os
import secrets
import time
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from kobo_dash import boundaries, db, espo
from kobo_dash.dashboards import owned
from kobo_dash.models import Owner

DASH, MCP = os.environ['PUBLIC_URL'], os.environ['MCP_URL']
SEED = base64.urlsafe_b64decode(os.environ['SIGNING_KEY'] + '==')
KEY = Ed25519PrivateKey.from_private_bytes(SEED)
ESPO = 'https://staging.respond.kobolabs.dev'
USER = 'cso-demo'  # the local kobo-dash's demo owner
ASSET = 'an3jbyAKcM4nAQSoyawu2C'  # the 5W activity report project on the Kobo test account
FEEDS = json.loads((Path(__file__).resolve().parents[1] / 'secrets' / 'dash-fivew.json').read_text())
BOUNDARIES = Path(os.environ.get('BOUNDARIES', '/tmp/asm-build/boundaries'))  # jam-admin1.geojson


def token(**extra):
    now = int(time.time())
    return jwt.encode({'iss': MCP, 'aud': DASH, 'sub': f'kf.kobotoolbox.org/{USER}', 'srv': 'https://kf.kobotoolbox.org',
                       'usr': USER, 'pur': 'api', 'iat': now, 'exp': now + 60, 'jti': secrets.token_urlsafe(16), **extra},
                      KEY, algorithm='EdDSA')


def call(c, method, path, body=None, **claims):
    r = c.request(method, DASH + path, json=body, headers={'Authorization': f'Bearer {token(**claims)}'})
    if r.status_code >= 400:
        raise SystemExit(f'{method} {path}: {r.status_code} {r.text[:600]}')
    return r.json() if r.content else None


async def direct(fn):
    try:
        async with db.session() as s:  # one transaction, committed on success
            owner = await s.scalar(select(Owner).where(Owner.username == USER))
            return await fn(s, owner)
    finally:
        await db.dispose()  # each direct step runs in its own event loop


# (key, entity, connection, where): what each feed reads
SOURCES = [('melissa_5w_locations', 'CActivityLocation', 'Melissa: 5W communities', []),
           ('melissa_5w_organisations', 'CResponder', 'Melissa: 5W organisations', [])]
BAR = {'sort': 'count', 'horizontal': True}
STACK = {**BAR, 'stack': True}
SPEC = {'schema': 1, 'title': '5W: Hurricane Melissa', 'dataset': 'loc',
        'datasets': [{'id': 'loc', 'from': [{'source': 'loc'}]}, {'id': 'orgs', 'from': [{'source': 'orgs'}]}],
        'filters': [{'id': 'f_sector', 'field': 'sector', 'kind': 'select', 'label': 'Sector', 'also': {'orgs': 'clusters'}},
                    {'id': 'f_status', 'field': 'status', 'kind': 'select', 'label': 'Activity status'}],
        'pages': [
            {'id': 'fivew', 'title': 'The 5W', 'rows': [
                {'widgets': [
                    {'type': 'kpi', 'id': 'reached', 'title': 'People reached', 'decimals': 0,
                     'measure': {'op': 'sum', 'field': 'population_reached'}},
                    {'type': 'kpi', 'id': 'targeted', 'title': 'People targeted', 'decimals': 0,
                     'measure': {'op': 'sum', 'field': 'population_targeted'}},
                    {'type': 'kpi', 'id': 'communities', 'title': 'Communities reached', 'measure': {'op': 'count'}},
                    {'type': 'kpi', 'id': 'organisations', 'title': 'Organisations', 'decimals': 0,
                     'measure': {'op': 'distinct', 'field': 'account'}}]},
                {'widgets': [
                    {'type': 'choropleth', 'id': 'reached_map', 'title': 'People reached by parish', 'field': 'pcode1',
                     'boundary': 'parishes', 'measure': {'op': 'sum', 'field': 'population_reached'}, 'basemap': False},
                    {'type': 'bar', 'id': 'by_sector', 'title': 'Communities reached, by sector', 'field': 'sector', 'options': {**BAR, 'top': 6}},
                    {'type': 'bar', 'id': 'by_org', 'title': 'By organisation', 'field': 'account', 'options': {**BAR, 'top': 15}}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'by_type', 'title': 'What: activity types', 'field': 'activity_kind',
                     'options': {**BAR, 'top': 8}},
                    {'type': 'table', 'id': 'www', 'title': 'Who does what where',
                     'columns': ['account', 'sector', 'activity_kind', 'status', 'name', 'population_targeted', 'population_reached'],
                     'options': {'page_size': 25, 'search': True, 'sort': 'population_reached'}}]}]},
            {'id': 'iccg', 'title': '3W across clusters', 'rows': [
                {'widgets': [
                    {'type': 'bar', 'id': 'where_what', 'title': 'What, where: communities by parish and sector',
                     'field': 'parish', 'by': 'sector', 'options': {**STACK, 'top': 14}},
                    {'type': 'bar', 'id': 'who_what', 'title': 'Who, what: organisations by sector',
                     'field': 'account', 'by': 'sector', 'options': {**STACK, 'top': 15}}]},
                {'widgets': [
                    {'type': 'choropleth', 'id': 'gap_map', 'title': 'Gaps: choose a sector above',
                     'subtitle': 'Parishes left grey have no activity of that sector', 'field': 'pcode1',
                     'boundary': 'parishes', 'measure': 'count', 'basemap': False},
                    {'type': 'table', 'id': 'overlaps', 'title': 'Duplication: the same activity, community and sector',
                     'subtitle': "Another organisation's activity of the same type there, neither completed: the clusters "
                                 'put them in touch', 'where': [{'field': 'overlaps_with', 'op': 'exists'}],
                     'columns': ['name', 'account', 'sector', 'activity_kind', 'overlaps_with', 'population_reached'],
                     'options': {'page_size': 25, 'sort': 'population_reached'}}]}]},
            {'id': 'organisations', 'title': 'Organisations by cluster', 'rows': [
                {'widgets': [
                    {'type': 'kpi', 'id': 'n_orgs', 'dataset': 'orgs', 'title': 'Organisations registered', 'measure': {'op': 'count'}},
                    {'type': 'kpi', 'id': 'n_reporting', 'dataset': 'orgs', 'title': 'Reporting', 'measure': {'op': 'count'},
                     'where': [{'field': 'status', 'op': 'eq', 'value': 'active'}]}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'per_cluster', 'dataset': 'orgs', 'title': 'Organisations per cluster', 'field': 'clusters',
                     'options': BAR},
                    {'type': 'bar', 'id': 'org_types', 'dataset': 'orgs', 'title': 'Types', 'field': 'org_type', 'options': BAR}]},
                {'widgets': [
                    {'type': 'table', 'id': 'directory', 'dataset': 'orgs', 'title': 'The organisations, and their clusters',
                     'subtitle': 'Their people: the contact list (the EspoCRM MCP\'s contact_list), for the coordinators',
                     'columns': ['name', 'acronym', 'org_type', 'clusters', 'status', 'last_report'],
                     'options': {'page_size': 50, 'search': True, 'sort': 'name', 'descending': False}}]}]}]}


def main():
    with httpx.Client(timeout=120) as c:
        call(c, 'GET', '/api/me')
        for key, entity, conn, _ in SOURCES:  # the admin page's step: connections, by the same function
            asyncio.run(direct(lambda s, o, conn=conn, entity=entity: espo.save(s, o, conn, ESPO, FEEDS[entity]['key'])))
        have = {f['key'] for f in call(c, 'GET', '/api/espo').get('feeds', [])}
        for key, entity, conn, where in SOURCES:
            body = {'connection': conn, 'key': key, 'entity': entity, 'fields': ['name', *FEEDS[entity]['fields']],
                    'where': where, 'name': conn, 'refresh': 300}
            if key in have:
                call(c, 'PATCH', f'/api/espo/feeds/{key}', {k: body[k] for k in ('fields', 'where', 'refresh')})
            else:
                f = call(c, 'POST', '/api/espo/feeds', body)
                print(f'feed {key}: {len(f.get("sample") or [])} sample rows')
        # The columns' labels as the dashboard shows them (a feed made before kobo-dash took
        # EspoCRM's labels keeps the field names: an owner's own labels are kept on re-reads)
        for key, cols in (('melissa_5w_locations', {'name': 'Community', 'account': 'Organisation', 'activity_kind': 'Activity type',
                                                    'population_reached': 'Reached', 'population_targeted': 'Targeted'}),
                          ('melissa_5w_organisations', {'name': 'Organisation', 'clusters': 'Clusters', 'last_report': 'Last report'})):
            call(c, 'PATCH', f'/api/tables/{key}/columns', {'columns': [{'id': i, 'label': l} for i, l in cols.items()]})
        dash = next((d for d in call(c, 'GET', '/api/dashboards').get('dashboards', []) if d['title'] == SPEC['title']), None)
        if dash is None:
            dash = call(c, 'POST', '/api/dashboards', {'asset_uid': ASSET, 'title': SPEC['title']}, asset=ASSET)
        slug = dash['slug']
        aliases = {s.get('alias') for s in call(c, 'GET', f'/api/dashboards/{slug}/sources').get('sources', [])}
        for (key, _, _, _), alias in zip(SOURCES, ('loc', 'orgs')):
            if alias not in aliases:
                call(c, 'POST', f'/api/dashboards/{slug}/sources', {'table': key, 'alias': alias})

        async def layers(s, o):
            d, _ = await owned(s, o.id, slug)
            await boundaries.save(s, d, 'parishes', (BOUNDARIES / 'jam-admin1.geojson').read_bytes(), 'pcode')

        asyncio.run(direct(layers))
        saved = call(c, 'PUT', f'/api/dashboards/{slug}/spec', {'spec': SPEC, 'note': '5W, Hurricane Melissa: the 5W, the ICCG\'s 3W, organisations by cluster'})
        print('spec revision', saved.get('revision'), 'problems', saved.get('problems'))
        call(c, 'PATCH', f'/api/dashboards/{slug}/settings', {'access': 'public'})
        print('dashboard', f'{DASH}/d/{slug}')


main()
