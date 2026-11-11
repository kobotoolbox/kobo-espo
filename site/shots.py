#!/usr/bin/env python3
"""
Screenshots for the manual, from the test droplet's EspoCRM, as each role (the seed users'
passwords from secrets/, never written anywhere else). Needs the demo data (site/demo-data.py,
and site/demo-cso.py for the CSO mapping's, its portal login among them).

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


def save(page, name, full=False):
    png = page.screenshot(full_page=full)
    img = Image.open(io.BytesIO(png)).convert('RGB')
    img.save(OUT / f'{name}.jpg', 'JPEG', quality=82, optimize=True)
    print(f'{name}.jpg {img.size[0]}x{img.size[1]}')


PORTAL = 'cso'  # the CSO portal's customId: its pages are /portal/cso/
PORTAL_USERS = {'cso-portal-amani'}


def base(user):
    return f'{URL}/portal/{PORTAL}/' if user in PORTAL_USERS else URL + '/'


def sign_in(browser, user, size=(1440, 900)):
    ctx = browser.new_context(viewport={'width': size[0], 'height': size[1]}, device_scale_factor=2, locale='en-GB')
    page = ctx.new_page()
    page.goto(base(user))
    page.fill('#field-userName', user)
    page.fill('#field-password', secrets()['ESPO_ADMIN_PASSWORD'] if user == 'admin' else secrets('seed')[pw_key(user)])
    page.click('#btn-login')
    page.wait_for_function("document.querySelector('#main') && document.querySelector('#main').children.length > 0", timeout=30000)
    time.sleep(2)
    return ctx, page


def go(page, hash_, wait='.list-container, .record, .kanban, .detail', settle=2.5, user=None):
    page.goto(f'{base(user)}#{hash_}')
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
        'connection': a.call('GET', '/CKoboConnection', {
            'where[0][type]': 'equals', 'where[0][attribute]': 'name', 'where[0][value]': 'site-registration',
            'where[1][type]': 'equals', 'where[1][attribute]': 'runBy', 'where[1][value]': 'main',
            'select': 'id', 'maxSize': 1})['list'][0]['id'],
        'melissa': find(a, 'CResponse', 'name', 'Hurricane Melissa response, Jamaica'),
        'trucking': find(a, 'CActivity', 'title', 'Water trucking to Black River and Santa Cruz'),
        'jrc': find(a, 'CResponder', 'organisationId', find(a, 'COrganisation', 'code', 'ORG_JRC')),
        'amani': find(a, 'CCso', 'name', 'Amani Community Health Network'),
        'kamukunji': find(a, 'CAdminArea', 'pcode', 'KE047288'),
    }
    ids['wash_survey'] = find(a, 'CAssessment', 'name', 'Household WASH survey')  # site/demo-assessments.py
    ids['wash_survey_area'] = find(a, 'CAssessmentArea', 'assessmentId', ids['wash_survey'])
    ids['amani_place'] = a.call('GET', '/CPresence', {
        'where[0][type]': 'equals', 'where[0][attribute]': 'csoId', 'where[0][value]': ids['amani'],
        'where[1][type]': 'equals', 'where[1][attribute]': 'adminAreaId', 'where[1][value]': ids['kamukunji'],
        'select': 'id', 'maxSize': 1})['list'][0]['id']
    for key, activity in (('trucking_place', 'trucking'),):  # its first community
        ids[key] = a.call('GET', '/CActivityLocation', {
            'where[0][type]': 'equals', 'where[0][attribute]': 'activityId', 'where[0][value]': ids[activity],
            'orderBy': 'cKoboRow', 'order': 'asc', 'select': 'id', 'maxSize': 1})['list'][0]['id']
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
        'connection': ('admin', f'CKoboConnection/view/{ids["connection"]}', None),
        'fivew-response': ('staff-1', f'CResponse/view/{ids["melissa"]}', None),
        'fivew-organisations': ('staff-1', 'COrganisation', None),
        'fivew-registration': ('staff-1', f'CResponder/view/{ids["jrc"]}', None),
        'fivew-activities': ('staff-1', 'CActivity', None),
        'fivew-activity': ('staff-1', f'CActivity/view/{ids["trucking"]}', None),
        'fivew-location': ('staff-1', f'CActivityLocation/view/{ids["trucking_place"]}', None),
        'cso-list': ('cso-kenya', 'CCso', None),
        'cso-profile': ('cso-kenya', f'CCso/view/{ids["amani"]}', None),
        'cso-place': ('cso-kenya', f'CPresence/view/{ids["amani_place"]}', None),
        'cso-updates': ('cso-kenya', 'CCsoUpdate', None),
        'portal-profile': ('cso-portal-amani', f'CCso/view/{ids["amani"]}', None),
        'portal-places': ('cso-portal-amani', 'CPresence', None),
        'portal-contacts': ('cso-portal-amani', 'Contact', None),
        'assessments': ('admin', 'CAssessment', None),  # (the demo response's team has no test user)
        'assessment': ('admin', f'CAssessment/view/{ids["wash_survey"]}', None),
        'assessment-area': ('admin', f'CAssessmentArea/view/{ids["wash_survey_area"]}', None),
        'packs-extension': ('admin', 'Admin/extensions', 'admin'),
        'email-settings': ('admin', 'Admin/outboundEmails', 'admin'),
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
            go(page, hash_, wait='#main .panel, #main .record, .list-container' if action == 'admin' else
               '.list-container, .record, .kanban, .detail', user=user)
            if action == 'kanban':
                page.click('button[data-name="kanban"][data-action="switchViewMode"]')
                page.wait_for_selector('button[data-name="kanban"].active', timeout=30000)
                time.sleep(3)
            if action == 'notifications':
                page.click('.notifications-badge, a.notifications-button, [data-name="notifications"] a')
                page.wait_for_selector('.notification-panel-container, .notification-list, #notifications-panel',
                                       timeout=30000)
                time.sleep(2.5)
            save(page, name, full='/view/' in hash_)  # a record's page: down to its stream
        browser.close()


if __name__ == '__main__':
    main(set(sys.argv[1:]))
