#!/usr/bin/env bash
# Copy the droplet's EspoCRM secrets (made by deploy/up.sh) to secrets/espo.secrets (not in
# git, mode 600), for the seed, the tests and the screenshots.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
mkdir -p secrets && chmod 700 secrets
( umask 077; ssh -o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m \
    "$ESPO_SSH" cat /root/kobo-espo.secrets > secrets/espo.secrets )
echo "secrets/espo.secrets"
