#!/usr/bin/env python3
"""Our 5W activity report, from the Hurricane Melissa 5W form (Workflow E):

    python3 -I kobo/forms/melissa.py ref/<the Melissa form>.xlsx

writes kobo/forms/activity-report.json. Its questions, notes, constraints and codes are
the Melissa form's, so its submissions fit EspoCRM as the Melissa form's do. What changes:
the response is picked from EspoCRM's list (responses.csv); the organisations
(organisations.csv) and the parishes and communities (areas.csv) are EspoCRM's lists,
not the form's own choices; a community row can name a registered site (site_code).
Then workflows/responses/lists/fivew-melissa.json holds the form's other lists for EspoCRM.
"""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
KEEP = {'type', 'name', 'label', 'hint', 'required', 'calculation', 'appearance', 'default', 'relevant',
        'choice_filter', 'constraint', 'constraint_message'}
FROM_ESPOCRM = {'organization_list', 'admin1', 'admin2'}  # lists EspoCRM keeps on the form instead


def sheet(wb, name):
    rows = list(wb[name].iter_rows(values_only=True))
    head = [str(h).split('::')[0] if h else None for h in rows[0]]  # label::English (en) -> label
    return [{h: v for h, v in zip(head, r) if h and v not in (None, '')} for r in rows[1:] if any(r)]


def main(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    survey = []
    for row in sheet(wb, 'survey'):
        row = {k: (str(v) if not isinstance(v, str) else v) for k, v in row.items() if k in KEEP}
        name = row.get('name')
        if name in ('LeadOrganization_name', 'ImplementingOrganization_name'):
            kind = name.split('_')[0]
            row['type'] = 'select_one_from_file organisations.csv'
            row['choice_filter'] = f"org_type=${{{kind}_type}} or name='other'"
        elif name == 'parish':
            row.update(type='select_one_from_file areas.csv', choice_filter="level='admin1'")
        elif name == 'community':
            row.update(type='select_one_from_file areas.csv', choice_filter='parent=${parish}')
        survey.append(row)
        if row.get('type') == 'deviceid':
            survey.append({'type': 'select_one_from_file responses.csv', 'name': 'response',
                           'label': 'Which response is this for?', 'required': 'true'})
        if name == 'location_address_comments':
            survey.append({'type': 'text', 'name': 'site_code', 'label': 'Site code (if at a registered site)',
                           'appearance': 'w2'})
    choices = [{k: str(v) for k, v in c.items() if k in ('list_name', 'name', 'label', 'sector', 'resource_type')}
               for c in sheet(wb, 'choices') if c.get('list_name') not in FROM_ESPOCRM]
    form = {'settings': {'form_title': '5W activity report (espo-kobo test)', 'form_id': 'fivew_activity_report',
                         'version': '1', 'style': 'theme-grid pages'},
            'survey': survey, 'choices': choices}
    out = HERE / 'activity-report.json'
    out.write_text(json.dumps(form, indent=1, ensure_ascii=False) + '\n')
    print(f'{out.name}: {len(survey)} rows, {len(choices)} choices')


if __name__ == '__main__':
    main(sys.argv[1])
