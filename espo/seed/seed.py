#!/usr/bin/env python3
"""
Set up this EspoCRM for the workflows its instance has: the packs in deploy/instance.toml
(plans/workflow-packs-plan.md), applied by espo/workflows.py. Idempotent: run it again
after changing a pack.

    python3 -I espo/seed/seed.py [--url https://staging.respond.kobolabs.dev] [--instance FILE] [--users]

With the admin API only (no files on the server), each pack's: entities, fields, links,
short codes, layouts, formulas, roles, teams, reference data, example agents (see
workflows/<pack>/workflow.toml); and the instance's own: its application name, and
outgoing email with Resend when secrets/resend.key is there (a send-only API key): the
from address, SMTP, the system's group email account, assignment and mention emails
(see EMAIL). --users makes the packs' test users with generated passwords, kept in
secrets/seed.secrets (gitignored).

The bridge's API users and roles aren't made here: kobo-espo-bridge's setup.py makes them per
template (kobo/templates/*.toml), each with only what its template needs.
"""
import argparse
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'espo'))
sys.path.insert(0, str(ROOT / 'tests'))
import workflows  # noqa: E402
from lib import URL, Espo, admin, secrets as read_secrets  # noqa: E402
from workflows import make_agent  # noqa: E402,F401  (tests/cases/agents.py makes its agents with it)

INSTANCE = ROOT / 'deploy' / 'instance.toml'
EMAIL = {'address': 'noreply@respond.kobolabs.dev', 'name': 'Kobo Respond',
         'host': 'smtp.resend.com', 'port': 2587, 'security': 'TLS', 'username': 'resend'}
EMAIL_KEY = ROOT / 'secrets' / 'resend.key'


def instance(path=INSTANCE):
    return tomllib.loads(Path(path).read_text())


def spec(path=INSTANCE):
    """The merged packs of an instance (what the tests read too: its agents, its users)."""
    inst = instance(path)
    return workflows.load(inst['packs'], params=inst.get('params'))


def ensure_email(espo, entities):
    if not EMAIL_KEY.exists():
        print(f'email: no {EMAIL_KEY.relative_to(ROOT)}, no outgoing email')
        return
    key = EMAIL_KEY.read_text().strip()
    # tests/run_all.sh turns the notification emails off for its run, the seed reruns included
    notify = os.environ.get('SEED_EMAIL_NOTIFICATIONS') != 'off'
    espo.call('PUT', '/Settings', body={
        'outboundEmailFromAddress': EMAIL['address'], 'outboundEmailFromName': EMAIL['name'],
        # Shared, so EspoCRM's scheduled emails (a CSO's welcome, by formula) can go out with it;
        # nobody can choose noreply@ as their From: no role gives people access to Email
        'outboundEmailIsShared': True, 'smtpServer': EMAIL['host'], 'smtpPort': EMAIL['port'],
        'smtpSecurity': EMAIL['security'], 'smtpAuth': True, 'smtpUsername': EMAIL['username'], 'smtpPassword': key,
        'assignmentEmailNotifications': notify,
        'assignmentEmailNotificationsEntityList': entities,
        'mentionEmailNotifications': notify})
    # EspoCRM sends its own emails (access info, notifications) through the group email
    # account whose address is the from address, not with the settings' SMTP
    account = {'name': f'{EMAIL["name"]} (system)', 'emailAddress': EMAIL['address'], 'fromName': EMAIL['name'],
               'status': 'Active', 'useImap': False, 'useSmtp': True, 'smtpIsShared': False,
               'smtpHost': EMAIL['host'], 'smtpPort': EMAIL['port'], 'smtpSecurity': EMAIL['security'],
               'smtpAuth': True, 'smtpAuthMechanism': 'login', 'smtpUsername': EMAIL['username'], 'smtpPassword': key}
    have = espo.find('InboundEmail', 'emailAddress', EMAIL['address'])
    if have:
        espo.call('PUT', f'/InboundEmail/{have["id"]}', body=account)
    else:
        espo.call('POST', '/InboundEmail', body=account)
    print(f'email: from {EMAIL["address"]} by {EMAIL["host"]}:{EMAIL["port"]}; assignment and mention emails'
          + ('' if notify else ' off (SEED_EMAIL_NOTIFICATIONS=off)'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    ap.add_argument('--instance', default=str(INSTANCE))
    ap.add_argument('--users', action='store_true')
    args = ap.parse_args()
    espo = admin() if args.url == URL else Espo(args.url, basic=f'admin:{read_secrets()["ESPO_ADMIN_PASSWORD"]}')
    inst = instance(args.instance)
    s = workflows.load(inst['packs'], params=inst.get('params'))
    print(f'packs: {", ".join(s["packs"])}')
    workflows.apply(espo, s, users=args.users, application_name=inst.get('application_name'),
                    email=lambda e: ensure_email(e, s['settings']['assignment_notifications']))


if __name__ == '__main__':
    main()
