#!/usr/bin/env bash
# Put this repo on the test droplet and start EspoCRM behind TLS.
#
#   deploy/up.sh            sync, generate secrets on first run, compose up
#   deploy/up.sh down       stop (volumes kept)
#   deploy/up.sh destroy    stop and delete the volumes (all EspoCRM data)
#
# Needs ESPO_HOST and ESPO_SSH (from .env). Secrets live on the droplet only, in
# /root/kobo-espo.secrets (mode 600); tests read them over ssh.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
REMOTE=/root/kobo-espo
SECRETS=/root/kobo-espo.secrets
# One connection for everything: the droplet's ufw rate-limits new ssh connections
SSH_OPTS="-o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m"
export RSYNC_RSH="ssh $SSH_OPTS"

rsync -az --delete --exclude .git --exclude .env --exclude 'state/' --exclude '__pycache__' \
    ./ "$ESPO_SSH:$REMOTE/"
# The shared bridge, next to this repo (KOBO_BRIDGE_DIR, default ../kobo-bridge)
rsync -az --delete --exclude .git --exclude '__pycache__' \
    "${KOBO_BRIDGE_DIR:-../kobo-bridge}/" "$ESPO_SSH:/root/kobo-bridge/"

ssh $SSH_OPTS "$ESPO_SSH" ESPO_HOST="$ESPO_HOST" CMD="${1:-up}" REMOTE="$REMOTE" SECRETS="$SECRETS" bash -s <<'EOF'
set -euo pipefail
cd "$REMOTE"
if [[ ! -s $SECRETS ]]; then
    ( umask 077
      echo "ESPO_ADMIN_PASSWORD=$(openssl rand -hex 12)"
      for k in ESPO_DB_PASSWORD ESPO_DB_ROOT_PASSWORD; do echo "$k=$(openssl rand -hex 16)"; done
    ) > "$SECRETS"
    echo "generated passwords in $SECRETS"
fi
set -a; source "$SECRETS"; ESPO_SITE_URL=https://$ESPO_HOST; set +a
export ESPO_HOST
compose() { docker compose -p kobo-espo --profile tls "$@"; }
case $CMD in
    up) compose up -d --remove-orphans ;;
    down) compose down ;;
    destroy) compose down -v ;;
esac
compose ps --format '{{.Service}}\t{{.Status}}'
EOF
