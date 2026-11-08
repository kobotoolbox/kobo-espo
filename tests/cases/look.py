#!/usr/bin/env python3
"""
Kobo's look (plans/espo-kobo-look-plan.md): L1-L4, against the test droplet. Whether it
looks right is checked by eye; this checks it's in place.

    python3 -I tests/cases/look.py

Reads only. Writes tests/results/look.json.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, URL, admin  # noqa: E402

LOOK = 'client/custom/kobo-look/'
results = []


def check(test, name, ok, detail=''):
    detail = json.loads(json.dumps(detail, default=str))
    results.append({'test': test, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {test}  {name}' + (f'  ({detail})' if detail and not ok else ''))


def get(path):
    with urllib.request.urlopen(f'{URL}/{path}', timeout=30) as r:
        return r.status, r.read().decode('utf-8', 'replace')


def main():
    a = admin()

    status, css = get(LOOK + 'kobo.css')
    check('L1', 'the stylesheet is served and sets Kobo blue as primary',
          status == 200 and '--brand-primary: #2095f3' in css, status)
    for name in ('logo.svg', 'favicon.svg', 'favicon.png'):
        status, _ = get(LOOK + name)
        check('L1', f'{name} is served', status == 200, status)

    _, page = get('')
    check('L2', 'the page loads the stylesheet after EspoCRM\'s', page.find('main-stylesheet') < page.find(LOOK + 'kobo.css'),
          [ln.strip() for ln in page.splitlines() if 'stylesheet' in ln])
    check('L2', 'the page\'s favicon is Kobo\'s', f'href="{LOOK}favicon.svg"' in page)

    meta = a.call('GET', '/Metadata')
    logo = meta.get('themes', {}).get('Espo', {}).get('logo')
    check('L3', 'the light theme\'s logo is Kobo\'s (shown when no company logo is set)', logo == LOOK + 'logo.svg', logo)

    s = a.call('GET', '/Settings')
    check('L4', 'everyone\'s theme is the light theme, users can\'t pick another',
          s.get('theme') == 'Espo' and s.get('userThemesDisabled') is True,
          {k: s.get(k) for k in ('theme', 'userThemesDisabled')})

    path = ROOT / 'tests' / 'results' / 'look.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    failed = [r for r in results if not r['ok']]
    print(f'look: {len(results) - len(failed)}/{len(results)} pass')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
