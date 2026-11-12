#!/usr/bin/env python3
"""A country's admin areas from the Humanitarian Geocoder (OCHA COD-AB boundaries), for
the seed (Workflow F, plans/cso-mapping-plan.md, 2):

    python3 -I espo/seed/admin_areas.py KE [--max-level N] [--boundaries DIR]

writes workflows/core/data/admin-areas-<iso3>.json: the country (admin0) and each level the
geocoder has, with P-codes and parents, as the seed loads them. --boundaries also saves
each level's GeoJSON there (<iso3>-admin<n>.geojson), the layers a kobo-dash choropleth
is shaded on (code property `pcode`). The country is its ISO2 or ISO3 code; --max-level
stops at a level (Uganda's admin4 is 1,520 parishes, more than a form's list wants).

    python3 -I espo/seed/admin_areas.py JM --crosswalk melissa-5w [--crosswalk-file F]

also gives each area the code another set gives it (altPcode, altScheme): the geocoder's
crosswalk of that key (/crosswalks/<iso2>/<key>.json, docs: site/pages/running.html,
"P-codes"), or that file (the same JSON). The seed then re-keys the areas EspoCRM has under
the other codes in place (their records, and what links to them, stay).

    python3 -I espo/seed/admin_areas.py --countries

writes workflows/core/data/admin-areas-countries.json: the country row (admin0, its P-code
its ISO2 code) of every country the geocoder has and no file here has already (a country's
records are synced from one file only).
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'workflows' / 'core' / 'data'
GEOCODER = os.environ.get('GEOCODER_URL', 'https://geocoder.kobolabs.dev')


def get(path, **params):
    url = f'{GEOCODER}{path}' + (f'?{urllib.parse.urlencode(params)}' if params else '')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json'}), timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('country', nargs='?', help='ISO2 or ISO3, e.g. KE or KEN')
    ap.add_argument('--countries', action='store_true', help="every other country's admin0 row")
    ap.add_argument('--max-level', type=int, default=4)
    ap.add_argument('--boundaries', type=Path, help="also save each level's GeoJSON here")
    ap.add_argument('--crosswalk', help="the key of the geocoder's crosswalk of another set of codes, e.g. melissa-5w")
    ap.add_argument('--crosswalk-file', type=Path, help='the crosswalk as JSON (as the geocoder serves it)')
    args = ap.parse_args()
    if args.countries:
        return countries()
    if not args.country:
        ap.error('a country, or --countries')
    code = args.country.upper()
    country = next((c for c in get('/countries') if code in (c['code'], c['iso3'])), None)
    if country is None:
        raise SystemExit(f'{code}: not in the geocoder (it has the countries whose COD-AB it has loaded)')
    iso2, iso3 = country['code'], country['iso3']
    areas = []
    for level in [0, *(n for n in get('/api/available_levels', country=iso2)['levels'] if n <= args.max_level)]:
        layer = get('/boundaries.geojson', country=iso2, level=level)
        for f in layer['features']:
            p = f['properties']
            areas.append({'name': p['name'], 'pcode': p['pcode'], 'level': f'admin{level}',
                          'parentPcode': p.get(f'adm{level - 1}_pcode', '') if level else '', 'country': iso3,
                          # its admin1's (an admin1's is its own): a form's two-level list skips levels
                          'pcode1': (p['pcode'] if level == 1 else p.get('adm1_pcode', '')) if level else ''})
        if args.boundaries:
            args.boundaries.mkdir(parents=True, exist_ok=True)
            out = args.boundaries / f'{iso3.lower()}-admin{level}.geojson'
            out.write_text(json.dumps(layer))
            print(f'{out}: {len(layer["features"])} areas')
    if len({a['pcode'] for a in areas}) != len(areas):
        raise SystemExit(f'{iso3}: P-codes repeat in the geocoder\'s boundaries; check them before seeding')
    if args.crosswalk or args.crosswalk_file:
        cw = (json.loads(args.crosswalk_file.read_text()) if args.crosswalk_file
              else get(f'/crosswalks/{iso2}/{args.crosswalk}.json'))
        theirs = {}
        for e in cw['entries']:
            if e.get('pcode') and e['pcode'] not in theirs:
                theirs[e['pcode']] = e['code']
        left = [e['code'] for e in cw['entries'] if not e.get('pcode')]
        for a in areas:
            a['altPcode'], a['altScheme'] = (theirs[a['pcode']], cw['key']) if a['pcode'] in theirs else ('', '')
        print(f'crosswalk {cw["key"]}: {len(theirs)} areas have its code'
              + (f'; not matched, so not in EspoCRM: {", ".join(left[:20])}' if left else ''))
    areas.sort(key=lambda a: (a['level'], a['pcode']))
    out = DATA / f'admin-areas-{iso3.lower()}.json'
    out.write_text(json.dumps(areas, indent=1, ensure_ascii=False) + '\n')
    counts = {lv: sum(a['level'] == lv for a in areas) for lv in dict.fromkeys(a['level'] for a in areas)}
    print(f'{out.name}: ' + ', '.join(f'{n} {lv}' for lv, n in counts.items()))


def countries():
    out = DATA / 'admin-areas-countries.json'
    have = {a['country'] for p in DATA.glob('admin-areas-*.json') if p != out for a in json.loads(p.read_text())}
    rows = sorted(({'name': c['name'], 'pcode': c['code'], 'level': 'admin0', 'parentPcode': '', 'country': c['iso3']}
                   for c in get('/countries') if c['iso3'] not in have), key=lambda a: a['pcode'])
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + '\n')
    print(f'{out.name}: {len(rows)} countries (not {", ".join(sorted(have))}: their own files)')


if __name__ == '__main__':
    main()
