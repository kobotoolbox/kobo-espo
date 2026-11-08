"""Shared test helpers: EspoCRM clients for the test droplet, reusing kobo-espo-bridge's.

Secrets come from secrets/espo.secrets (gitignored; deploy/up.sh writes them on the
droplet, tests/fetch-secrets.sh copies them here) and secrets/seed.secrets (espo/seed).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('KOBO_ESPO_BRIDGE_DIR', str(ROOT.parent / 'kobo-espo-bridge')))
from bridge import BridgeError, Espo  # noqa: E402,F401


def secrets(name='espo'):
    path = ROOT / 'secrets' / f'{name}.secrets'
    if not path.exists():
        return {}
    return dict(ln.split('=', 1) for ln in path.read_text().splitlines() if '=' in ln)


def env(key, default=None):
    if key in os.environ:
        return os.environ[key]
    for line in (ROOT / '.env').read_text().splitlines() if (ROOT / '.env').exists() else []:
        if line.startswith(key + '='):
            return line.split('=', 1)[1]
    return default


URL = env('ESPO_URL') or f'https://{env("ESPO_HOST", "staging.respond.kobolabs.dev")}'


def admin():
    return Espo(URL, basic=f'admin:{secrets()["ESPO_ADMIN_PASSWORD"]}')


def as_user(username):
    return Espo(URL, basic=f'{username}:{secrets("seed")[pw_key(username)]}')


def as_key(key_name):
    return Espo(URL, api_key=secrets('seed')[key_name])


def pw_key(username):
    return f'PASSWORD_{username.upper().replace("-", "_")}'
