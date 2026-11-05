#!/usr/bin/env python3
"""kobo/forms/*.json (the forms as XLSForm rows, what tests/staging.py deploys) to .xlsx,
for people who'd rather open them in a spreadsheet: python3 -I kobo/forms/export.py"""
import json
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
for path in sorted(HERE.glob('*.json')):
    form = json.loads(path.read_text())
    wb = Workbook()
    for i, sheet in enumerate(('survey', 'choices', 'settings')):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = sheet
        rows = form[sheet] if sheet != 'settings' else [form['settings']]
        cols = list(dict.fromkeys(k for r in rows for k in r))
        ws.append(cols)
        for r in rows:
            ws.append([r.get(c, '') for c in cols])
    wb.save(path.with_suffix('.xlsx'))
    print(path.with_suffix('.xlsx').name)
