"""The assessment registry's dashboard (site/pages/assessments.html, "Dashboard") on a local
kobo-dash, from the test droplet's EspoCRM: one dashboard, three pages (the registry,
coverage, gaps and overlaps), on two EspoCRM feeds (site/dash-assessments-feeds.py makes
their users), for the demo response (site/demo-assessments.py).

Run in kobo-dash's environment, with its settings in an env file (DATABASE_URL, PUBLIC_URL,
MCP_URL, DASH_PUBLIC_KEY and SIGNING_KEY, its Ed25519 pair, SECRET_KEY, CRED_KEYS):

    cd ../kobo-dash; set -a; . <env file>; set +a
    PYTHONPATH=src uv run python ../kobo-espo/site/dash-assessments.py

ASSET: the assessment registration project on the Kobo test account (a dashboard belongs
to a Kobo project; its data here is EspoCRM's). BOUNDARIES: Jamaica's parishes from the geocoder
(espo/seed/admin_areas.py JM --boundaries DIR), the P-codes EspoCRM has.
Keys come from secrets/dash-assessments.json and are never printed.
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
ASSET = os.environ['ASSET']  # the assessment registration project on the Kobo test account
FEEDS = json.loads((Path(__file__).resolve().parents[1] / 'secrets' / 'dash-assessments.json').read_text())
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


# (key, entity, connection, where): what each feed reads. Not the cancelled; the areas in each
# assessment's latest submission
SOURCES = [('melissa_assessments', 'CAssessment', 'Melissa: assessments', [{'type': 'notEquals', 'attribute': 'status', 'value': 'cancelled'}]),
           ('melissa_assessment_areas', 'CAssessmentArea', 'Melissa: assessment areas', [{'type': 'isTrue', 'attribute': 'current'},
                                                                                       {'type': 'notEquals', 'attribute': 'status', 'value': 'cancelled'}])]
BAR = {'sort': 'count', 'horizontal': True}
SPEC = {'schema': 1, 'title': 'Assessment registry: Hurricane Melissa', 'dataset': 'asm',
        'datasets': [{'id': 'asm', 'from': [{'source': 'asm'}]}, {'id': 'areas', 'from': [{'source': 'areas'}]}],
        'filters': [{'id': 'f_sector', 'field': 'sectors', 'kind': 'select', 'label': 'Sector', 'also': {'areas': 'sectors'}},
                    {'id': 'f_status', 'field': 'status', 'kind': 'select', 'label': 'Status', 'also': {'areas': 'status'}}],
        'pages': [
            {'id': 'registry', 'title': 'The registry', 'rows': [
                {'widgets': [
                    {'type': 'kpi', 'id': 'n_asm', 'title': 'Assessments', 'measure': {'op': 'count'}},
                    {'type': 'kpi', 'id': 'n_now', 'title': 'Planned or ongoing', 'measure': {'op': 'count'},
                     'where': [{'field': 'status', 'op': 'in', 'value': ['planned', 'ongoing']}]},
                    {'type': 'kpi', 'id': 'n_reports', 'title': 'Reports available', 'measure': {'op': 'count'},
                     'where': [{'field': 'report_available', 'op': 'eq', 'value': 'yes'}]},
                    {'type': 'kpi', 'id': 'n_new', 'title': 'Not checked yet', 'measure': {'op': 'count'},
                     'where': [{'field': 'review', 'op': 'eq', 'value': 'new'}]}]},
                {'widgets': [
                    {'type': 'bar', 'id': 'by_status', 'title': 'Status', 'field': 'status', 'options': {'sort': 'form'}},
                    {'type': 'bar', 'id': 'by_sector', 'title': 'Sectors', 'field': 'sectors', 'options': BAR},
                    {'type': 'bar', 'id': 'by_org', 'title': 'Who is assessing', 'field': 'organisation',
                     'options': {**BAR, 'top': 10}}]},
                {'widgets': [
                    {'type': 'table', 'id': 'registry', 'title': 'Every assessment',
                     'subtitle': '"Not checked yet": registered, not yet reviewed by the A&A Cell',
                     'columns': ['name', 'code', 'organisation', 'sectors', 'status', 'start_date', 'end_date',
                                 'report_available', 'report_sharing', 'review'],
                     'options': {'page_size': 25, 'search': True, 'sort': 'start_date'}}]}]},
            {'id': 'coverage', 'title': 'Coverage', 'rows': [
                {'widgets': [
                    {'type': 'choropleth', 'id': 'by_parish', 'dataset': 'areas', 'title': 'Assessments by parish',
                     'subtitle': 'Each assessment counted in every parish it covers', 'field': 'pcode1',
                     'boundary': 'parishes', 'measure': 'count', 'basemap': False},
                    {'type': 'bar', 'id': 'places', 'dataset': 'areas', 'title': 'Places assessed (parishes and communities)', 'field': 'admin_area',
                     'options': {**BAR, 'top': 20}}]},
                {'widgets': [
                    {'type': 'timeline', 'id': 'when', 'title': 'When they start', 'field': 'start_date'},
                    {'type': 'bar', 'id': 'how', 'title': 'Coordination', 'field': 'coordination', 'options': {'sort': 'form'}}]}]},
            {'id': 'gaps', 'title': 'Gaps and overlaps', 'rows': [
                {'widgets': [
                    {'type': 'table', 'id': 'overlaps', 'title': 'Overlaps: the same sector, place and time',
                     'subtitle': 'The A&A Cell puts these organisations in touch', 'where': [{'field': 'overlaps_with', 'op': 'exists'}],
                     'columns': ['name', 'code', 'organisation', 'sectors', 'overlaps_with', 'start_date', 'end_date'],
                     'options': {'page_size': 25, 'sort': 'start_date'}},
                    {'type': 'bar', 'id': 'checks', 'title': 'What to follow up', 'field': 'data_checks', 'options': BAR}]},
                {'widgets': [
                    {'type': 'choropleth', 'id': 'gap_map', 'dataset': 'areas', 'title': 'Gaps: choose a sector above',
                     'subtitle': 'Parishes left grey have no assessment of that sector', 'field': 'pcode1',
                     'boundary': 'parishes', 'measure': 'count', 'basemap': False},
                    {'type': 'table', 'id': 'upcoming', 'title': 'Planned and ongoing, by start',
                     'subtitle': 'To synchronise before they start', 'where': [{'field': 'status', 'op': 'in', 'value': ['planned', 'ongoing']}],
                     'columns': ['start_date', 'name', 'organisation', 'sectors', 'end_date'],
                     'options': {'page_size': 10, 'sort': 'start_date'}}]}]}]}


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
        for key, cols in (('melissa_assessments', {'name': 'Assessment', 'code': 'Code', 'organisation': 'Organisation',
                                                   'sectors': 'Sectors', 'status': 'Status', 'start_date': 'Start',
                                                   'end_date': 'End', 'report_available': 'Report', 'report_sharing': 'Sharing',
                                                   'review': 'Review', 'overlaps_with': 'Overlaps with',
                                                   'data_checks': 'To follow up', 'coordination': 'Coordination'}),
                          ('melissa_assessment_areas', {'admin_area': 'Place', 'assessment': 'Assessment', 'sectors': 'Sectors'})):
            call(c, 'PATCH', f'/api/tables/{key}/columns', {'columns': [{'id': i, 'label': l} for i, l in cols.items()]})
        dash = next((d for d in call(c, 'GET', '/api/dashboards').get('dashboards', []) if d['title'] == SPEC['title']), None)
        if dash is None:
            dash = call(c, 'POST', '/api/dashboards', {'asset_uid': ASSET, 'title': SPEC['title']}, asset=ASSET)
        slug = dash['slug']
        aliases = {s.get('alias') for s in call(c, 'GET', f'/api/dashboards/{slug}/sources').get('sources', [])}
        for (key, _, _, _), alias in zip(SOURCES, ('asm', 'areas')):
            if alias not in aliases:
                call(c, 'POST', f'/api/dashboards/{slug}/sources', {'table': key, 'alias': alias})

        async def layers(s, o):
            d, _ = await owned(s, o.id, slug)
            await boundaries.save(s, d, 'parishes', (BOUNDARIES / 'jam-admin1.geojson').read_bytes(), 'pcode')

        asyncio.run(direct(layers))
        saved = call(c, 'PUT', f'/api/dashboards/{slug}/spec', {'spec': SPEC, 'note': 'Assessment registry, Hurricane Melissa'})
        print('spec revision', saved.get('revision'), 'problems', saved.get('problems'))
        call(c, 'PATCH', f'/api/dashboards/{slug}/settings', {'access': 'public'})
        print('dashboard', f'{DASH}/d/{slug}')


main()
