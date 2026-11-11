#!/usr/bin/env python3
"""
The 5W dashboard's feed users (site/dash-fivew.py builds the dashboard): two read-only API
users in EspoCRM, made with the EspoCRM MCP's create_dashboard_feed as a conversation
would, for the demo response's team (Response: Hurricane Melissa), so every cluster: its
activities' communities (each with its activity's who and what) and its registered
organisations, only the fields the dashboard shows (no one's contact details). Their keys
go to secrets/dash-fivew.json (mode 600), never printed.

    python3 -I site/dash-fivew-feeds.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from lib import URL, admin, secrets  # noqa: E402

from bridges import BRIDGE_DIR  # noqa: E402

sys.path.insert(0, str(BRIDGE_DIR))
from espo_mcp import tools  # noqa: E402
from espo_mcp.confirm import Refused  # noqa: E402

TEAM = 'Response: Hurricane Melissa'
FEEDS = {
    'CActivityLocation': ['activity', 'account', 'leadOrganisation', 'sector', 'activityKind', 'activityKindOther', 'status',
                          'parish', 'community', 'pcode1', 'locationType', 'populationTargeted', 'populationReached',
                          'overlapsWith', 'project'],
    'CResponder': ['code', 'acronym', 'orgType', 'clusters', 'status', 'lastReport', 'response'],
}


def main():
    work = Path(tempfile.mkdtemp(prefix='dash-fivew-'))
    (work / 'token').write_text('unused')
    (work / 'bridge.secrets').write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
    inst = tools.Instance({'ESPO_URL': URL, 'BRIDGE_SECRETS': str(work / 'bridge.secrets'),
                           'KOBO_URL': 'http://127.0.0.1:9', 'KOBO_TOKEN_FILE': str(work / 'token')})
    a, out = admin(), {}
    for entity, fields in FEEDS.items():
        try:
            first = tools.create_dashboard_feed(inst, TEAM, entity, fields)
            user = tools.create_dashboard_feed(inst, TEAM, entity, fields, confirm=first['confirm'])['api_user']
        except Refused as e:
            if 'already' not in str(e):
                raise
            user = str(e).split('feed user ')[1].split(' ')[0]
        u = a.call('GET', '/User', {'maxSize': 1, 'select': 'id', 'where[0][type]': 'equals',
                                    'where[0][attribute]': 'userName', 'where[0][value]': user})['list'][0]
        out[entity] = {'user': user, 'key': a.call('GET', f'/User/{u["id"]}').get('apiKey'), 'fields': fields}
        print(f'{entity}: {user}')
    path = ROOT / 'secrets' / 'dash-fivew.json'
    path.write_text(json.dumps(out))
    path.chmod(0o600)
    print(f'keys in {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
