#!/usr/bin/env python3
"""
Records for the example agents (agents/setup/examples.json) to pick up: a site visit that
needs a repair (and is a danger to people), a routine one, a site needing a repair that
nobody has visited for 10 days (Repair follow-up: at its next time, Monday 06:00 UTC, or set
it to every hour to see it sooner), and an application waiting in Research. For trying the agents with a real model; it doesn't check anything itself.

    python3 -I tests/agent-examples.py          # the two sites and the application
    python3 -I tests/agent-examples.py app      # only the application

Then one pass of a runner (see the manual, "Running it" → "Agents"). The records are named
"BDR ..."; delete them by hand when done.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import admin  # noqa: E402

a = admin()
teams = {t['name']: t['id'] for t in a.call('GET', '/Team', {'maxSize': 50})['list']}
users = {u['userName']: u['id'] for u in a.call('GET', '/User', {'maxSize': 200, 'select': 'userName'})['list']}
stamp = time.strftime('%H%M%S')

visits = [('BDR Well north', 'needs_repair',
           'The concrete cover on the well has cracked through and part of it fell in. Children were '
           'leaning over the open hole to draw water while we were there. We put branches around it for now.'),
          ('BDR Tap stand market', 'operational',
           'All four taps work, flow is good, the drain is clear. Committee cleans it every morning.')]
if sys.argv[1:] != ['app']:
    resp = a.call('POST', '/CResponse', body={'name': f'BDR Response {stamp}', 'status': 'Active',
                                              'teamsIds': [teams['Response: Test EQ 1']], 'leadId': users['staff-1']})
    for name, status, text in visits:
        site = a.call('POST', '/CSite', body={'name': name, 'siteCode': f'BDR-{stamp}-{len(name)}',
                                              'siteType': 'water_point', 'status': 'operational',
                                              'responseId': resp['id'], 'teamsIds': [teams['Response: Test EQ 1']]})
        time.sleep(1.1)  # EspoCRM's times are to the second
        a.call('PUT', f'/CSite/{site["id"]}', body={'status': status, 'lastVisit': time.strftime('%Y-%m-%d')})
        a.call('POST', '/Note', body={'type': 'Post', 'parentType': 'CSite', 'parentId': site['id'],
                                      'post': f'**Site visit**\nBy: BDR tester\nCondition: {status}\nNotes: {text}'})
        print('site', name, site['id'])
    # for Repair follow-up (on a schedule): needs a repair, nobody has been for 10 days
    site = a.call('POST', '/CSite', body={'name': 'BDR Pump east', 'siteCode': f'BDR-{stamp}-pump',
                                          'siteType': 'water_point', 'status': 'needs_repair',
                                          'lastVisit': time.strftime('%Y-%m-%d', time.gmtime(time.time() - 10 * 86400)),
                                          'responseId': resp['id'], 'teamsIds': [teams['Response: Test EQ 1']]})
    print('site BDR Pump east', site['id'])

org = 'Riverbend Community Water Trust'
found = a.call('GET', '/Account', {'where[0][type]': 'equals', 'where[0][attribute]': 'name',
                                   'where[0][value]': org, 'select': 'id'})['list']
acc = found[0] if found else a.call('POST', '/Account', body={'name': org, 'website': 'https://example.org'})
app = a.call('POST', '/CApplication', body={
    'name': f'BDR {org}', 'accountId': acc['id'], 'country': 'Kenya',
    'registrationNumber': 'CBO/2024/0193', 'amountRequested': 48000,
    'purpose': 'Rehabilitate 6 boreholes in Turkana South and train local water committees.',
    'leadership': 'Mary Ekai (chair), Peter Lokwang (treasurer)', 'stage': 'Submitted',
    'teamsIds': [teams['Grants review']], 'noticeVersion': 'test-1'})
time.sleep(1.1)
# straight to Research, as if DD screening had cleared it (in dry run it doesn't move it)
a.call('PUT', f'/CApplication/{app["id"]}', body={'stage': 'Research', 'ddSanctions': 'clear', 'ddRegistry': 'not_checked'})
print('application', app['id'])
