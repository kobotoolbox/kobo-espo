#!/usr/bin/env python3
"""A country's admin areas from the Humanitarian Geocoder (OCHA COD-AB boundaries), for
the seed (Workflow F, plans/cso-mapping-plan.md, 2):

    python3 -I espo/seed/admin_areas.py KE [--max-level N] [--boundaries DIR]

writes espo/seed/data/admin-areas-<iso3>.json: the country (admin0) and each level the
geocoder has, with P-codes and parents, as the seed loads them. --boundaries also saves
each level's GeoJSON there (<iso3>-admin<n>.geojson), the layers a kobo-dash choropleth
is shaded on (code property `pcode`). The country is its ISO2 or ISO3 code; --max-level
stops at a level (Uganda's admin4 is 1,520 parishes, more than a form's list wants).
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'
GEOCODER = os.environ.get('GEOCODER_URL', 'https://geocoder.kobolabs.dev')


def get(path, **params):
    url = f'{GEOCODER}{path}' + (f'?{urllib.parse.urlencode(params)}' if params else '')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json'}), timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('country', help='ISO2 or ISO3, e.g. KE or KEN')
    ap.add_argument('--max-level', type=int, default=4)
    ap.add_argument('--boundaries', type=Path, help="also save each level's GeoJSON here")
    args = ap.parse_args()
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
                          'parentPcode': p.get(f'adm{level - 1}_pcode', '') if level else '', 'country': iso3})
        if args.boundaries:
            args.boundaries.mkdir(parents=True, exist_ok=True)
            out = args.boundaries / f'{iso3.lower()}-admin{level}.geojson'
            out.write_text(json.dumps(layer))
            print(f'{out}: {len(layer["features"])} areas')
    if len({a['pcode'] for a in areas}) != len(areas):
        raise SystemExit(f'{iso3}: P-codes repeat in the geocoder\'s boundaries; check them before seeding')
    areas.sort(key=lambda a: (a['level'], a['pcode']))
    out = DATA / f'admin-areas-{iso3.lower()}.json'
    out.write_text(json.dumps(areas, indent=1, ensure_ascii=False) + '\n')
    counts = {lv: sum(a['level'] == lv for a in areas) for lv in dict.fromkeys(a['level'] for a in areas)}
    print(f'{out.name}: ' + ', '.join(f'{n} {lv}' for lv, n in counts.items()))


if __name__ == '__main__':
    main()
