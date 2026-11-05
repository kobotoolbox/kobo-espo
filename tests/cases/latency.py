#!/usr/bin/env python3
"""
T1 latency through the running bridge (deploy/bridges.sh, polling every 30 s): submissions
on the real Kobo test account, timed until their case is in EspoCRM.

    python3 -I tests/cases/latency.py [N]

Writes tests/results/latency.json.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ROOT, admin, env  # noqa: E402
from staging import RealKobo  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
kobo = RealKobo(env('KOBO_URL'), env('KOBO_TOKEN'), env('KOBO_TEST_ACCOUNT_ON_PRODUCTION') == 'yes')
uid = kobo.deploy(json.loads((ROOT / 'kobo' / 'forms' / 'support-request.json').read_text()))
a = admin()
times = []
for i in range(n):
    stamp = time.strftime('%H%M%S')
    sent = time.time()
    sub = kobo.submit(uid, {'requester_name': 'Latency Test', 'requester_email': 'latency@example.org',
                            'organisation': 'kobo', 'project': 'internal', 'category': 'other', 'priority': 'Low',
                            'summary': f'Latency {stamp}', 'description': 'Timing the bridge.'})
    while time.time() - sent < 180:
        if a.call('GET', '/Case', {'where[0][type]': 'equals', 'where[0][attribute]': 'cKoboSubmissionUuid',
                                   'where[0][value]': sub['_uuid'], 'select': 'id'})['list']:
            break
        time.sleep(1)
    times.append(round(time.time() - sent, 1))
    print(f'{i + 1}/{n}: {times[-1]} s')
    time.sleep(7 * (i + 1) % 23)  # land at different points of the 30 s poll
out = {'when': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'poll_seconds': 30, 'seconds': times,
       'min': min(times), 'max': max(times), 'mean': round(sum(times) / len(times), 1)}
(ROOT / 'tests' / 'results' / 'latency.json').write_text(json.dumps(out, indent=2) + '\n')
print(out)
