#!/usr/bin/env python3
"""
Screenshots for the manual, from the test droplet's EspoCRM, as each role (the seed users'
passwords from secrets/, never written anywhere else). Needs the demo data (site/demo-data.py).

    python3 -I site/shots.py [name ...]      all, or only these

Writes site/static/shots/<name>.jpg.
"""
import io
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import URL, admin, pw_key, secrets  # noqa: E402

OUT = ROOT / 'site' / 'static' / 'shots'


def find(a, entity, attr, value):
    return a.call('GET', f'/{entity}', {'where[0][type]': 'equals', 'where[0][attribute]': attr,
                                       'where[0][value]': value, 'select': 'id', 'maxSize': 1})['list'][0]['id']


def save(page, name, clip=None):
    png = page.screenshot(clip=clip, full_page=False)
    img = Image.open(io.BytesIO(png)).convert('RGB')
    img.save(OUT / f'{name}.jpg', 'JPEG', quality=82, optimize=True)
    print(f'{name}.jpg {img.size[0]}x{img.size[1]}')


def sign_in(browser, user, size=(1440, 900)):
    ctx = browser.new_context(viewport={'width': size[0], 'height': size[1]}, device_scale_factor=2, locale='en-GB')
    page = ctx.new_page()
    page.goto(URL + '/')
    page.fill('#field-userName', user)
    page.fill('#field-password', secrets()['ESPO_ADMIN_PASSWORD'] if user == 'admin' else secrets('seed')[pw_key(user)])
    page.click('#btn-login')
    page.wait_for_selector('#navbar', timeout=30000)
    time.sleep(2)
    return ctx, page


def go(page, hash_, wait='.list-container, .record, .kanban, .detail', settle=2.5):
    page.goto(f'{URL}/#{hash_}')
    page.wait_for_selector(wait, timeout=30000)
    time.sleep(settle)


def main(only):
    OUT.mkdir(parents=True, exist_ok=True)
    a = admin()
    ids = {
        'case_export': find(a, 'Case', 'name', 'Data and exports: Export to XLS times out'),
        'case_login': find(a, 'Case', 'name', "Account and access: New enumerators can't log in"),
        'eq1': find(a, 'CResponse', 'name', 'Earthquake response, Testland North'),
        'site': find(a, 'CSite', 'siteCode', 'EQ1-WP-001'),
        'role_volunteer': find(a, 'Role', 'name', 'Volunteer'),
        'volunteer': find(a, 'Contact', 'emailAddress', 'nadia.haddad@example.org'),
    }
    shots = {
        'cases-triager': ('triager', 'Case', None),
        'case-from-kobo': ('triager', f'Case/view/{ids["case_export"]}', None),
        'case-assigned': ('triager', f'Case/view/{ids["case_login"]}', None),
        'notifications': ('triager', 'Case', 'notifications'),
        'cases-partner-a': ('partner-a', 'Case', None),
        'cases-partner-b': ('partner-b', 'Case', None),
        'response': ('staff-1', f'CResponse/view/{ids["eq1"]}', None),
        'board-staff': ('staff-1', 'Task', 'kanban'),
        'board-volunteer': ('volunteer-2', 'Task', 'kanban'),
        'board-volunteer-other': ('volunteer-1', 'Task', 'kanban'),
        'volunteer-contact': ('staff-1', f'Contact/view/{ids["volunteer"]}', None),
        'sites': ('staff-1', 'CSite', None),
        'site': ('staff-1', f'CSite/view/{ids["site"]}', None),
        'standards': ('staff-1', 'CStandard', None),
        'role-volunteer': ('admin', f'Role/view/{ids["role_volunteer"]}', None),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        sessions = {}
        for name, (user, hash_, action) in shots.items():
            if only and name not in only:
                continue
            if user not in sessions:
                sessions[user] = sign_in(browser, user)
            page = sessions[user][1]
            go(page, hash_)
            if action == 'kanban':
                page.click('.list-view-mode-buttons button[data-name="kanban"], button[data-value="kanban"], '
                           'a[data-name="kanban"]')
                page.wait_for_selector('.kanban', timeout=30000)
                time.sleep(3)
            if action == 'notifications':
                page.click('.notifications-badge, a.notifications-button, [data-name="notifications"] a')
                page.wait_for_selector('.notification-panel-container, .notification-list, #notifications-panel',
                                       timeout=30000)
                time.sleep(2.5)
            save(page, name)
        browser.close()


if __name__ == '__main__':
    main(set(sys.argv[1:]))
