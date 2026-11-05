#!/usr/bin/env bash
# Run SQL against the test droplet's EspoCRM database: tests/db.sh "select ..."
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
ssh -o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m "$ESPO_SSH" \
    "cd /root/kobo-espo && docker compose -p kobo-espo exec -T db sh -c 'mariadb -uroot -p\"\$MARIADB_ROOT_PASSWORD\" espocrm'" <<<"$1"
