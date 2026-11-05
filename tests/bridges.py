"""Running kobo-bridge's setup.py and bridge.py (as processes, as in their containers)
against the test droplet's EspoCRM, for the tests and the demo data."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import ROOT, URL, secrets

BRIDGE_DIR = Path(os.environ.get('KOBO_BRIDGE_DIR', ROOT.parent / 'kobo-bridge'))
sys.path.insert(0, str(BRIDGE_DIR))
import bridge  # noqa: E402

SECRETS = ROOT / 'secrets' / 'bridge.secrets'


def ensure_secrets():
    if not SECRETS.exists():
        SECRETS.write_text(f'ESPO_ADMIN_PASSWORD={secrets()["ESPO_ADMIN_PASSWORD"]}\n')
        SECRETS.chmod(0o600)


class Bridge:
    """One template's bridge: setup, then passes of bridge.py once, each a new process."""

    def __init__(self, name, kobo_url, token):
        self.name, self.kobo_url = name, kobo_url
        self.template = ROOT / 'kobo' / 'templates' / f'{name}.toml'
        self.t = bridge.load_template(self.template)
        self.state = Path(tempfile.mkdtemp(prefix=f'bridge-{name}-'))
        self.token_file = self.state / 'token'
        self.token_file.write_text(token)
        self.token_file.chmod(0o600)

    def setup(self):
        out = subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'setup.py'), '--template', str(self.template),
                              '--url', URL, '--secrets', str(SECRETS), '--kobo-url', self.kobo_url,
                              '--token-file', str(self.token_file), '--state-dir', str(self.state)],
                             capture_output=True, text=True)
        if out.returncode:
            raise SystemExit(f'setup {self.name} failed:\n{out.stdout}\n{out.stderr}')
        return out.stdout

    def env(self, espo_url=URL):
        s = secrets('bridge')
        b, fu = self.t.get('bridge') or {}, self.t.get('followup') or {}
        e = {'PATH': os.environ['PATH'], 'ESPO_URL': espo_url, 'ESPO_API_KEY': s[b['secret']],
             'KOBO_URL': self.kobo_url, 'KOBO_TOKEN_FILE': str(self.token_file),
             'BRIDGE_TEMPLATE': str(self.template), 'BRIDGE_STATE_DIR': str(self.state),
             'BRIDGE_LIST_MIN_SECONDS': '0'}
        if fu:
            e['ESPO_FOLLOWUP_API_KEY'] = s[fu.get('secret', 'ESPO_FOLLOWUP_API_KEY')]
        if self.t['entity'] == 'Case' and self.t.get('form'):
            e['ESPO_EDITS_API_KEY'] = s['ESPO_EDITS_API_KEY']
        return e

    def once(self, espo_url=URL):
        out = subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'bridge.py'), 'once'],
                             env=self.env(espo_url), capture_output=True, text=True)
        status = json.loads((self.state / 'status.json').read_text())
        return out.returncode, out.stdout + out.stderr, status

    def failed(self):
        return subprocess.run([sys.executable, '-I', str(BRIDGE_DIR / 'bridge.py'), 'failed', str(self.state)],
                              capture_output=True, text=True).stdout

    def forget(self):
        """A lost ledger: the next pass rescans every submission."""
        for f in self.state.glob('bridge.sqlite*'):
            f.unlink()


def by(espo, entity, attr, value, select=None):
    params = {'where[0][type]': 'equals', 'where[0][attribute]': attr, 'where[0][value]': value, 'maxSize': 20}
    if select:
        params['select'] = select
    return espo.call('GET', f'/{entity}', params)['list']


def notifications(espo, record_id):
    """The user's notifications about a record (EspoCRM 10 groups them per record)."""
    rows = espo.call('GET', '/Notification', {'maxSize': 50})['list']
    # A mention is about the note: the record is the note's parent
    return [n for n in rows if record_id in (n.get('relatedParentId'), n.get('relatedId'),
                                             (n.get('noteData') or {}).get('parentId'))]
