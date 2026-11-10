"""The CSO mapping dashboard (site/pages/cso.html, "Dashboards") on a local kobo-dash, from
the test droplet's EspoCRM: one dashboard, three pages (the directory, presence and reach,
gaps and overlaps), on three EspoCRM feeds (site/dash-cso-feeds.py makes their users).

Run in kobo-dash's environment, with its settings in an env file (DATABASE_URL, PUBLIC_URL,
MCP_URL, DASH_PUBLIC_KEY and SIGNING_KEY, its Ed25519 pair, SECRET_KEY, CRED_KEYS):

    cd ../kobo-dash; set -a; . <env file>; set +a
    PYTHONPATH=src uv run python ../kobo-espo/site/dash-cso.py

The manual's dash-cso-* screenshots are its three pages at the view URL it prints.

Owner API calls go through HTTP with signed assertions, as kobo-mcp makes them. The two
steps kobo-dash only offers in its admin page (an EspoCRM connection, an uploaded boundary
layer) call the same functions that page calls. Keys come from secrets/dash-cso.json and are
never printed. BOUNDARIES: where espo/seed/admin_areas.py KE --boundaries DIR saved Kenya's layers.
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
USER = 'cso-demo'
ASSET = 'aLyYkWfcizAy93bkLaCoa9'  # the CSO profile (Kenya) project on the Kobo test account
FEEDS = json.loads((Path(__file__).resolve().parents[1] / 'secrets' / 'dash-cso.json').read_text())
BOUNDARIES = Path(os.environ.get('BOUNDARIES', '/tmp/cso-boundaries'))  # admin_areas.py --boundaries


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


# (key, entity, connection, where): what each feed reads. Only CSOs that agreed to be listed,
# places and updates that count now
SOURCES = [('cso_kenya', 'CCso', 'CSO Kenya: CSOs', [{'type': 'isTrue', 'attribute': 'listed'}]),
           ('cso_kenya_places', 'CPresence', 'CSO Kenya: places',
            [{'type': 'isTrue', 'attribute': 'current'}, {'type': 'isTrue', 'attribute': 'listed'}]),
           ('cso_kenya_updates', 'CCsoUpdate', 'CSO Kenya: updates',
            [{'type': 'isTrue', 'attribute': 'current'}, {'type': 'isTrue', 'attribute': 'listed'}])]

SPEC = {'schema': 1, 'title': 'CSO mapping: Kenya', 'dataset': 'csos',
        'datasets': [{'id': 'csos', 'from': [{'source': 'csos'}]}, {'id': 'places', 'from': [{'source': 'places'}]},
                     {'id': 'updates', 'from': [{'source': 'updates'}]}],
        'filters': [{'id': 'f_type', 'field': 'cso_type', 'kind': 'select', 'label': 'Type of CSO',
                     'also': {'places': 'cso_type', 'updates': 'cso_type'}},
                    {'id': 'f_roles', 'field': 'roles', 'kind': 'select', 'label': 'Role',
                     'also': {'places': 'roles', 'updates': 'roles'}}],
        'pages': [
            {'id': 'directory', 'title': 'Directory', 'rows': [
                {'widgets': [
                    {'type': 'kpi', 'id': 'n_csos', 'title': 'CSOs in the directory', 'measure': {'op': 'count'}},
                    {'type': 'kpi', 'id': 'n_places', 'dataset': 'places', 'title': 'Places where they work',
                     'measure': {'op': 'count'}},
                    {'type': 'kpi', 'id': 'n_active', 'dataset': 'updates', 'title': 'Active now',
                     'measure': {'op': 'count'}, 'where': [{'field': 'status', 'op': 'eq', 'value': 'active'}]}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'types', 'title': 'Types of CSO', 'field': 'cso_type',
                     'options': {'sort': 'count', 'horizontal': True, 'top': 6}},
                    {'type': 'bar', 'id': 'roles', 'title': 'What they do', 'field': 'roles',
                     'options': {'sort': 'count', 'horizontal': True, 'top': 6}},
                    {'type': 'bar', 'id': 'offers', 'title': 'What they offer other CSOs', 'field': 'offers',
                     'options': {'sort': 'count', 'horizontal': True, 'top': 6}}]},
                {'widgets': [
                    {'type': 'table', 'id': 'directory', 'title': 'The directory',
                     'subtitle': 'Contacts only where the CSO agreed to share them',
                     'columns': ['name', 'acronym', 'cso_type', 'roles', 'offers', 'seeks', 'shared_contact'],
                     'options': {'page_size': 25, 'search': True, 'sort': 'name'}}]}]},
            {'id': 'presence', 'title': 'Presence and reach', 'rows': [
                {'widgets': [
                    {'type': 'choropleth', 'id': 'by_subcounty', 'dataset': 'places', 'title': 'CSOs by sub-county',
                     'field': 'pcode2', 'boundary': 'subcounties', 'measure': 'count', 'basemap': False},
                    {'type': 'choropleth', 'id': 'by_county', 'dataset': 'places', 'title': 'CSOs by county',
                     'field': 'pcode1', 'boundary': 'counties', 'measure': 'count', 'basemap': False}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'settings', 'dataset': 'places', 'title': 'Settings they reach',
                     'field': 'settings', 'options': {'sort': 'count', 'horizontal': True, 'top': 6}},
                    {'type': 'bar', 'id': 'populations', 'dataset': 'places', 'title': 'Populations they work with',
                     'field': 'populations', 'options': {'sort': 'count', 'horizontal': True, 'top': 6}},
                    {'type': 'bar', 'id': 'where', 'dataset': 'places', 'title': 'Places', 'field': 'admin_area',
                     'options': {'sort': 'count', 'horizontal': True, 'top': 20}}]}]},
            {'id': 'gaps', 'title': 'Gaps and overlaps', 'rows': [
                {'widgets': [
                    {'type': 'choropleth', 'id': 'active_map', 'dataset': 'updates', 'title': 'Active or ready, by sub-county',
                     'field': 'pcode2', 'boundary': 'subcounties', 'measure': 'count', 'basemap': False,
                     'where': [{'field': 'status', 'op': 'in', 'value': ['active', 'ready']}]},
                    {'type': 'bar', 'id': 'needs', 'dataset': 'updates', 'title': 'Gaps: what they need',
                     'field': 'needs', 'options': {'sort': 'count', 'horizontal': True, 'top': 6}}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'overlap', 'dataset': 'updates', 'title': 'Overlaps: activities by sub-county',
                     'subtitle': 'Several CSOs doing the same thing in one place', 'field': 'admin_area', 'by': 'status',
                     'options': {'sort': 'count', 'horizontal': True, 'stack': True}},
                    {'type': 'bar', 'id': 'status', 'dataset': 'updates', 'title': 'Status of their work',
                     'field': 'status', 'options': {'sort': 'form'}}]},
                {'widgets': [
                    {'type': 'table', 'id': 'updates', 'dataset': 'updates', 'title': 'What each CSO is doing where',
                     'columns': ['admin_area', 'cso', 'status', 'roles', 'needs'],
                     'options': {'page_size': 25, 'search': True, 'sort': 'admin_area'}}]}]}]}


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
        for key, cols in (('cso_kenya', {'name': 'CSO', 'acronym': 'Acronym', 'cso_type': 'Type', 'roles': 'What it does',
                                         'offers': 'Offers', 'seeks': 'Seeks', 'shared_contact': 'Contact (shared)'}),
                          ('cso_kenya_updates', {'admin_area': 'Place', 'cso': 'CSO', 'status': 'Status',
                                                 'roles': 'What it does there', 'needs': 'Needs there'}),
                          ('cso_kenya_places', {'admin_area': 'Place', 'cso': 'CSO'})):
            call(c, 'PATCH', f'/api/tables/{key}/columns', {'columns': [{'id': i, 'label': l} for i, l in cols.items()]})
        dash = next((d for d in call(c, 'GET', '/api/dashboards').get('dashboards', []) if d['title'] == SPEC['title']), None)
        if dash is None:
            dash = call(c, 'POST', '/api/dashboards', {'asset_uid': ASSET, 'title': SPEC['title']}, asset=ASSET)
        slug = dash['slug']
        aliases = {s.get('alias') for s in call(c, 'GET', f'/api/dashboards/{slug}/sources').get('sources', [])}
        for (key, _, _, _), alias in zip(SOURCES, ('csos', 'places', 'updates')):
            if alias not in aliases:
                call(c, 'POST', f'/api/dashboards/{slug}/sources', {'table': key, 'alias': alias})

        async def layers(s, o):
            d, _ = await owned(s, o.id, slug)
            for level, key in ((1, 'counties'), (2, 'subcounties')):
                await boundaries.save(s, d, key, (BOUNDARIES / f'ken-admin{level}.geojson').read_bytes(), 'pcode')
        asyncio.run(direct(layers))
        saved = call(c, 'PUT', f'/api/dashboards/{slug}/spec', {'spec': SPEC, 'note': 'CSO mapping, Kenya'})
        print('spec revision', saved.get('revision'), 'problems', saved.get('problems'))
        call(c, 'PATCH', f'/api/dashboards/{slug}/settings', {'access': 'public'})
        print('dashboard', f'{DASH}/d/{slug}')


main()
