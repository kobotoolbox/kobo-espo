"""Assessments from before Jamaica's areas were the geocoder's (PRODUCT-428): when this
run re-keyed areas (their codes changed in place, the seed's `was`), an assessment's areas
as the form gave them (areaCodes, an area's pcode) take the new codes, and are saved again:
their formulas give them their P-codes up the parents again, and check overlaps with the
new codes. A rerun re-keys nothing, so changes nothing."""


def every(espo, entity, select, **eq):
    params = {'maxSize': 200, 'select': select}
    for i, (attr, value) in enumerate(eq.items()):
        params.update({f'where[{i}][type]': 'equals', f'where[{i}][attribute]': attr, f'where[{i}][value]': value})
    out, offset = [], 0
    while True:
        page = espo.call('GET', f'/{entity}', {**params, 'offset': offset})['list']
        out += page
        offset += 200
        if len(page) < 200:
            return out


def migrate(espo, rekeyed=None):
    codes = (rekeyed or {}).get('CAdminArea') or {}
    if not codes:
        return
    new = lambda text: ' '.join(codes.get(c, c) for c in (text or '').split())  # noqa: E731
    done = {}
    for r in every(espo, 'CAssessmentArea', 'id,name,pcode'):
        espo.call('PUT', f'/CAssessmentArea/{r["id"]}', body={'name': r['name'], 'pcode': new(r.get('pcode')) or r.get('pcode')})
        done['areas'] = done.get('areas', 0) + 1
    for r in every(espo, 'CAssessment', 'id,areaCodes'):
        if r.get('areaCodes') and new(r['areaCodes']) != r['areaCodes']:
            espo.call('PUT', f'/CAssessment/{r["id"]}', body={'areaCodes': new(r['areaCodes'])})
            done['assessments'] = done.get('assessments', 0) + 1
    # again, now that every one has the new codes: their overlaps with each other
    for r in every(espo, 'CAssessment', 'id,areaCodes'):
        if r.get('areaCodes'):
            espo.call('PUT', f'/CAssessment/{r["id"]}', body={'areaCodes': r['areaCodes']})
    if done:
        print('assessments: their areas\' new codes: ' + ', '.join(f'{n} {k}' for k, n in done.items()))
