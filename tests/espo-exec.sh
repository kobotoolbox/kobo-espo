#!/usr/bin/env bash
# Run a shell command in the test droplet's EspoCRM container: tests/espo-exec.sh 'ls data'
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
ssh -o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m "$ESPO_SSH" \
    "cd /root/kobo-espo && docker compose -p kobo-espo exec -T espocrm sh -c $(printf %q "$1")"
