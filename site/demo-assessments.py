#!/usr/bin/env python3
"""
Demo data for the manual's assessment registry page and its dashboard: ten made-up
assessments in the demo response "Hurricane Melissa response, Jamaica" (its team Response:
Hurricane Melissa, its WASH, Shelter and ETC clusters), most of them in the parishes the
hurricane hit hardest. Everything is made up; the organisations are the 5W list's.

    python3 -I site/demo-assessments.py

Idempotent: its own assessments (by title, in that response) and their areas are removed
and made again, nothing else is touched. Made through the admin API, as the form's records
would be (the same formulas run: codes, teams, Accounts, P-codes, overlaps, data checks);
dates relative to today.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import admin  # noqa: E402

RESPONSE = 'Hurricane Melissa response, Jamaica'
AREAS = json.loads((ROOT / 'workflows' / 'core' / 'data' / 'admin-areas-jam.json').read_text())
PARISH = {a['name']: a['pcode'] for a in AREAS if a['level'] == 'admin1'}


def community(parish, n):
    """A parish's n-th community (by P-code): made-up places need real P-codes."""
    return sorted(a['pcode'] for a in AREAS if a.get('pcode1') == PARISH[parish] and a['level'] == 'admin3')[n]


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


# title, organisation, participants, sectors, coordination, methodology, frequency, start, end, level, areas,
# status, review, report (link or file name), sharing
ASSESSMENTS = [
    ('Multi-sector initial rapid assessment', 'ORG_OCHA', ['ORG_UNICEF', 'ORG_WFP', 'ORG_IFRC', 'ORG_JRC', 'ORG_PAHO'],
     ['INTER_CLUSTER'], 'joint', ['key_informant', 'direct_observation', 'secondary_data'], 'single', -24, -10,
     'admin1', ['Saint Elizabeth', 'Westmoreland', 'Hanover', 'Saint James', 'Trelawny'], 'report_shared', 'checked',
     'https://reliefweb.int/report/jamaica/demo-mira', 'public'),
    ('Water systems rapid assessment', 'ORG_UNICEF', [], ['WASH'], 'harmonised', ['key_informant', 'direct_observation'],
     'single', -12, 6, 'admin2', [('Saint Elizabeth', 0), ('Saint Elizabeth', 1), ('Westmoreland', 0)], 'ongoing', 'checked', None, None),
    ('Shelter damage assessment', 'ORG_IFRC', ['ORG_JRC'], ['SHELTER'], 'harmonised', ['household_survey', 'direct_observation'],
     'single', -15, 5, 'admin1', ['Westmoreland', 'Hanover'], 'ongoing', 'checked', None, None),
    ('Health facility functionality', 'ORG_PAHO', [], ['HEALTH'], 'uncoordinated', ['key_informant'], 'single', -30, -18,
     'admin1', ['Saint Elizabeth', 'Manchester', 'Westmoreland'], 'completed', 'checked', None, None),
    ('Food security and markets', 'ORG_WFP', [], ['FOOD_SECURITY'], 'harmonised', ['household_survey', 'key_informant'],
     'single', 3, 17, 'admin1', ['Saint Elizabeth', 'Westmoreland', 'Saint James'], 'planned', 'new', None, None),
    ('Displacement tracking', 'ORG_IOM', [], ['SHELTER', 'PROTECTION'], 'harmonised', ['key_informant', 'direct_observation'],
     'weekly', -20, 40, 'sites', [('Saint Elizabeth', 2), ('Westmoreland', 1)], 'ongoing', 'checked', None, None),
    ('Household WASH survey', 'ORG_MERCYCORPS', [], ['WASH'], 'uncoordinated', ['household_survey'], 'single', -5, 9,
     'admin2', [('Saint Elizabeth', 1)], 'ongoing', 'new', None, None),
    ('Child protection rapid assessment', 'ORG_ADRA', [], ['CHILD_PROTECTION'], 'uncoordinated', ['focus_groups'], 'single',
     -4, 10, 'admin1', ['Hanover'], 'planned', 'new', None, None),
    ('Connectivity assessment', 'ORG_WFP', [], ['EMERGENCY_TELECOMS'], 'uncoordinated', ['direct_observation', 'remote'],
     'single', -22, -12, 'admin1', ['Saint Elizabeth', 'Westmoreland'], 'report_shared', 'checked', 'ETC-connectivity-report.pdf',
     'response'),
    ('Roof damage survey', 'ORG_SAMARITAN_S_PURSE', [], ['SHELTER'], 'uncoordinated', ['direct_observation'], 'single', -8, 7,
     'admin2', [('Westmoreland', 0), ('Westmoreland', 2)], 'ongoing', 'new', None, None),
]


def main():
    a = admin()
    q = lambda e, attr, v: a.call('GET', f'/{e}', {'maxSize': 200, 'select': 'id,name', 'where[0][type]': 'equals',  # noqa: E731
                                                   'where[0][attribute]': attr, 'where[0][value]': v})['list']
    resp = q('CResponse', 'name', RESPONSE)
    if not resp:
        raise SystemExit(f'no response "{RESPONSE}" (the demo data: demo-data.py)')
    resp = resp[0]
    titles = {t[0] for t in ASSESSMENTS}
    for old in q('CAssessment', 'responseId', resp['id']):
        if old['name'] in titles:
            for r in q('CAssessmentArea', 'assessmentId', old['id']):
                a.call('DELETE', f'/CAssessmentArea/{r["id"]}')
            for t in q('Task', 'parentId', old['id']):
                a.call('DELETE', f'/Task/{t["id"]}')
            a.call('DELETE', f'/CAssessment/{old["id"]}')
    org = {}
    for (title, who, parts, sectors, coord, method, freq, start, end, level, areas, status, review, report, sharing) in ASSESSMENTS:
        for c in [who, *parts]:
            org.setdefault(c, q('COrganisation', 'code', c)[0]['id'])
        codes = [PARISH[x] if isinstance(x, str) else community(*x) for x in areas]
        body = {'name': title, 'responseId': resp['id'], 'organisationId': org[who], 'leadOrganisationId': org[who],
                'participantCodes': ' '.join(parts), 'sectors': sectors, 'coordination': coord, 'methodology': method,
                'frequency': freq, 'startDate': day(start), 'endDate': day(end), 'geoLevel': level,
                'areaCodes': ' '.join(codes), 'status': status}
        if report and report.startswith('http'):
            body.update(reportLink=report, reportSharing=sharing)
        elif report:
            body.update(reportFile=report, reportSharing=sharing)
        asm = a.call('POST', '/CAssessment', body=body)
        for code in codes:
            area = q('CAdminArea', 'pcode', code)[0]
            a.call('POST', '/CAssessmentArea', body={'name': code, 'assessmentId': asm['id'], 'adminAreaId': area['id'], 'pcode': code})  # named by its formula
        if review != 'new':
            a.call('PUT', f'/CAssessment/{asm["id"]}', body={'review': review})
        got = a.call('GET', f'/CAssessment/{asm["id"]}')
        print(f'{got["code"]} {title}: {len(codes)} areas' + (f', flags {got["dataChecks"]}' if got.get('dataChecks') else ''))


if __name__ == '__main__':
    main()
