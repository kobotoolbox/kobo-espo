#!/usr/bin/env python3
"""
EspoCRM's assignment and mention emails, off while the tests run (tests/run_all.sh), so a
run doesn't use up the sender's (Resend's) daily quota. Invitations still go out.

    python3 -I tests/email_notifications.py off            prints the settings it changed, as JSON
    python3 -I tests/email_notifications.py restore JSON   puts them back
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import admin  # noqa: E402

KEYS = ('assignmentEmailNotifications', 'mentionEmailNotifications')

if __name__ == '__main__':
    a = admin()
    if sys.argv[1:2] == ['off']:
        settings = a.call('GET', '/Settings')
        print(json.dumps({k: bool(settings.get(k)) for k in KEYS}))
        a.call('PUT', '/Settings', body={k: False for k in KEYS})
    elif sys.argv[1:2] == ['restore'] and len(sys.argv) == 3:
        a.call('PUT', '/Settings', body={k: bool(v) for k, v in json.loads(sys.argv[2]).items() if k in KEYS})
    else:
        sys.exit(__doc__)
