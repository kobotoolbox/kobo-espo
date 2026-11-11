#!/usr/bin/env python3
"""The assessment registry's form (plans/assessment-registry-plan.md), on the model of OCHA's
Venezuela earthquakes registry, with the response's lists (EspoCRM's, as CSV media) where
that one asks free text:

    python3 -I kobo/forms/assessment.py

writes kobo/forms/assessment-registration.json and its bridge template,
kobo/templates/assessment-registration.toml. The choices come from the packs' lists
(workflows/assessments/lists/assessment-lists.json, the response's sectors from
workflows/responses/lists/fivew-melissa.json), as EspoCRM's enums do, so the two agree.

The areas are a repeat, one row per area (a CAssessmentArea each, for the coverage map),
picked from the country's admin areas (areas.csv: COUNTRY's). An assessment's code
(assessment, prefilled in the link it's emailed: ?d[/data/assessment]=ASM-...) makes a
submission update it.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LISTS = json.loads((ROOT / 'workflows' / 'assessments' / 'lists' / 'assessment-lists.json').read_text())
SECTORS = [{'code': 'INTER_CLUSTER', 'label': 'Inter-cluster'},
           *json.loads((ROOT / 'workflows' / 'responses' / 'lists' / 'fivew-melissa.json').read_text())['sectors']]
# The country whose admin areas the form lists, and its levels' names
COUNTRY = {'iso3': 'JAM', 'admin1': 'Parish', 'admin2': 'Community'}
STEM, TITLE = 'assessment-registration', 'Assessment registration'


def options(name):
    return SECTORS if name == 'sectors' else LISTS[name]


def q(type_, name, label, **kw):
    return {k: v for k, v in {'type': type_, 'name': name, 'label': label, **kw}.items() if v is not None}


def pick(name, label, list_name, many=False, required=True, **kw):
    """A select question and, when its list has 'other', the text that says what."""
    rows = [q(f'select_{"multiple" if many else "one"} {list_name}', name, label,
              required='true' if required else None, **kw)]
    others = [c['code'] for c in options(list_name) if c['code'] in ('other', 'other_sector')]
    if others:
        test = f"selected(${{{name}}}, '{others[0]}')" if many else f"${{{name}}} = '{others[0]}'"
        rows.append(q('text', f'{name}_other', 'Please specify', required='true', relevant=test))
    return rows


def group(name, label, rows, repeat=False, **kw):
    kind = 'repeat' if repeat else 'group'
    return [q(f'begin_{kind}', name, label, **kw), *rows, {'type': f'end_{kind}'}]


def org(name, label, required=True, **kw):
    return [q('select_one_from_file organisations.csv', name, label, required='true' if required else None,
              appearance='minimal autocomplete', **kw),
            q('text', f'{name}_other', 'Its name', required='true', relevant=f"${{{name}}} = 'other'")]


def survey():
    a = COUNTRY
    return [
        q('start', 'start', None), q('end', 'end', None), q('hidden', 'assessment', None),
        q('note', 'intro', 'Register an assessment your organisation is planning, doing or has done in this '
          'response, so that the response can see who is assessing what, where and when, avoid duplication '
          'and share the results. Send it again (from the link you are emailed) when it moves on.'),
        q('select_one_from_file responses.csv', 'response', 'Response', required='true', appearance='minimal'),
        *group('REPORTER', 'Who is registering it', [
            *org('organisation', 'Your organisation'),
            q('text', 'reporter_name', 'Your name', required='true'),
            q('text', 'reporter_email', 'Your email', required='true',
              constraint=r"regex(., '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')",
              constraint_message='An email address, e.g. name@example.org'),
        ]),
        *group('ABOUT', 'The assessment', [  # not ASSESSMENT: Kobo's names are case-blind, and "assessment" is the code's
            q('text', 'title', 'Its title', required='true'),
            *pick('sectors', 'Sectors it covers', 'sectors', many=True),
            *pick('coordination', 'How is it coordinated?', 'coordination'),
            *pick('methodology', 'Methodology', 'methodology', many=True),
            *pick('frequency', 'How often is it done?', 'frequency'),
        ]),
        *group('ORGS', 'Organisations', [
            *org('lead_organisation', 'Lead organisation', hint='Yours, if it leads it'),
            q('select_multiple_from_file organisations.csv', 'participants', 'Participating organisations',
              appearance='minimal autocomplete'),
            q('text', 'participants_other', 'Participating organisations not in the list'),
        ]),
        *group('DATES', 'When', [
            q('date', 'start_date', 'Start date', required='true'),
            q('date', 'end_date', 'End date (estimated, if not done yet)', constraint='. >= ${start_date}',
              constraint_message="It can't end before it starts."),
        ]),
        *group('WHERE', 'Where', [
            *pick('geo_level', 'At what level does it cover places?', 'geo_level'),
            *group('AREAS', 'An area it covers', [
                q('select_one_from_file areas.csv', 'admin1', a['admin1'], required='true',
                  choice_filter="level='admin1'", appearance='minimal'),
                q('select_one_from_file areas.csv', 'admin2', a['admin2'], choice_filter='parent=${admin1}',
                  appearance='minimal autocomplete', relevant="${geo_level} = 'admin2' or ${geo_level} = 'sites'"),
                q('calculate', 'area', None, calculation="if(${admin2} != '', ${admin2}, ${admin1})"),
            ], repeat=True, relevant="${geo_level} != 'whole_area'"),
            q('calculate', 'area_codes', None, calculation="join(' ', ${area})"),
            q('text', 'localities', 'Localities, sites or camps', hint='Names, if it covers particular places'),
        ]),
        *group('STATUS', 'Where it is now, and its results', [
            *pick('status', 'Status', 'status'),
            q('file', 'report', 'The report, if there is one', relevant="${status} != 'planned'"),
            *pick('report_sharing', 'Who may see the report?', 'sharing', relevant="${report} != '' or ${report_link} != ''",
                  required=False),
            q('text', 'report_link', 'Or a link to it (ReliefWeb, HDX...)', relevant="${status} != 'planned'"),
            q('file', 'dataset', 'The dataset, if it can be shared', relevant="${status} != 'planned'"),
            *pick('data_sharing', 'Who may see the data?', 'sharing', relevant="${dataset} != ''", required=False),
            q('text', 'notes', 'Anything else', appearance='multiline'),
        ]),
    ]


def choices(rows):
    used = []
    for row in rows:
        t = row['type'].split()
        if t[0] in ('select_one', 'select_multiple') and t[1] not in used:
            used.append(t[1])
    return [{'list_name': name, 'name': c['code'], 'label': c['label']} for name in used for c in options(name)]


# Kobo question -> EspoCRM field, and its type for the bridge
FIELDS = [('organisation', 'organisation', 'link COrganisation code'), ('organisation_other', 'organisationOther', None),
          ('sectors', 'sectors', 'multiEnum'), ('sectors_other', 'sectorsOther', None),
          ('coordination', 'coordination', None), ('methodology', 'methodology', 'multiEnum'),
          ('methodology_other', 'methodologyOther', None), ('frequency', 'frequency', None),
          ('frequency_other', 'frequencyOther', None),
          ('lead_organisation', 'leadOrganisation', 'link COrganisation code'),
          ('lead_organisation_other', 'leadOrganisationOther', None), ('participants', 'participantCodes', None),
          ('participants_other', 'participantsOther', None), ('start_date', 'startDate', None),
          ('end_date', 'endDate', None), ('geo_level', 'geoLevel', None), ('area_codes', 'areaCodes', None),
          ('localities', 'localities', None), ('status', 'status', None), ('report', 'reportFile', None),
          ('report_sharing', 'reportSharing', None), ('report_link', 'reportLink', None),
          ('dataset', 'datasetFile', None), ('data_sharing', 'dataSharing', None), ('notes', 'notes', None)]


def field(kobo, espo, kind, table='field'):
    out = f'[[{table}]]\nkobo = "{kobo}"\nespo = "{espo}"\n'
    if kind and kind.startswith('link'):
        _, entity, lookup = kind.split()
        out += f'type = "link"\nentity = "{entity}"\nlookup = "{lookup}"\n'
    elif kind:
        out += f'type = "{kind}"\n'
    return out


def template():
    title = f'{TITLE} (espo-kobo test)'
    lists = [('responses.csv', 'CResponse', 'where = { status = ["Planning", "Active"] }\norder_by = "name"\n',
              'columns = { name = "code", label = "name" }'),
             ('organisations.csv', 'COrganisation', 'order_by = "name"\n', 'columns = { name = "code", label = "name" }'),
             ('areas.csv', 'CAdminArea', f'where = {{ country = "{COUNTRY["iso3"]}" }}\norder_by = "pcode"\n',
              'columns = { name = "pcode", label = "name", level = "level", parent = "parentPcode" }')]
    parts = [
        '# The assessment registry (plans/assessment-registry-plan.md). Generated by\n'
        f'# kobo/forms/assessment.py with its form, kobo/forms/{STEM}.json: change them there.',
        f'[bridge]\nuser = "kobo-{STEM}"\nrole = "Kobo {STEM}"\nsecret = "ESPO_{STEM.upper().replace("-", "_")}_API_KEY"\n',
        f'[form]\nname = "{title}"\n',
        '# An assessment (CAssessment); sent again with its code (in its link), the same one. Its\n'
        '# teams (the whole response\'s), its organisation\'s Account, overlaps: formula\n'
        '[record]\nentity = "CAssessment"\npanel = "Assessment"\nname = "{title}"\nmatch = { code = "assessment" }\n'
        'media = "files"\nkeep_on_update = []  # its status: what the form says\nrequired = ["response", "organisation", "title", "sectors", "start_date", "geo_level", "status"]\n',
        '[requester]  # who registered it: a Contact, by email\nemail = "reporter_email"\nname = "reporter_name"\n'
        'create_account = false\n',
        field('response', 'response', 'link CResponse code'),
        *(field(k, e, kind) for k, e, kind in FIELDS),
        '# Each area it covers: one row (CAssessmentArea), its area by the deepest P-code given\n'
        '[[repeat]]\ngroup = "AREAS"\nentity = "CAssessmentArea"\nlink = "assessment"\nname = "{area}"  # then its assessment\'s code and the area\'s name (formula)\n',
        field('area', 'adminArea', 'link CAdminArea pcode', 'repeat.field'),
        field('area', 'pcode', None, 'repeat.field'),
        *(f'[[list]]\nfile = "{f}"\nentity = "{e}"\n{extra}{cols}\nforms = ["{title}"]\n' for f, e, extra, cols in lists),
    ]
    out = ROOT / 'kobo' / 'templates' / f'{STEM}.toml'
    out.write_text('\n'.join(parts))
    print(out.relative_to(ROOT))


def main():
    rows = survey()
    form = {'settings': {'form_title': f'{TITLE} (espo-kobo test)', 'form_id': STEM.replace('-', '_'), 'version': '1',
                         'style': 'pages'}, 'survey': rows, 'choices': choices(rows)}
    out = HERE / f'{STEM}.json'
    out.write_text(json.dumps(form, indent=1, ensure_ascii=False) + '\n')
    print(f'{out.name}: {len(rows)} rows, {len(form["choices"])} choices')
    template()


if __name__ == '__main__':
    main()
