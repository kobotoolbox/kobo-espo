#!/usr/bin/env bash
# Start (or restart) the bridges on the test droplet, polling Kobo staging.
#
#   deploy/bridges.sh          setup for every template, then compose --profile bridge up
#   deploy/bridges.sh down     stop the bridges (EspoCRM keeps running)
#   deploy/bridges.sh logs     their logs
#
# Needs KOBO_URL and KOBO_TOKEN in .env: a throwaway test account (on a production server
# only with KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes). The token goes to
# /root/kobo-espo-kobo.token on the droplet (mode 600); the API keys setup made to
# /root/kobo-espo-bridge.secrets (mode 600).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
case "$KOBO_URL" in
    "") echo "no KOBO_URL in .env" >&2; exit 1 ;;
    *kf.kobotoolbox.org*|*eu.kobotoolbox.org*)
        [[ ${KOBO_TEST_ACCOUNT_ON_PRODUCTION:-} == yes ]] || {
            echo "KOBO_URL is a production server: set KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes, for a throwaway test account only" >&2; exit 1; } ;;
esac
SSH_OPTS="-o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m"
CMD=${1:-up}
if [[ $CMD == up ]]; then
    deploy/up.sh >/dev/null
    token=$(mktemp); trap 'rm -f "$token"' EXIT
    ( umask 077; printf %s "$KOBO_TOKEN" > "$token" )
    for t in kobo/templates/*.toml; do
        python3 -I ../kobo-espo-bridge/setup.py --template "$t" --url "https://$ESPO_HOST" \
            --secrets secrets/bridge.secrets --kobo-url "$KOBO_URL" --token-file "$token" | tail -1
    done
    scp $SSH_OPTS -q "$token" "$ESPO_SSH:/root/kobo-espo-kobo.token"
    scp $SSH_OPTS -q secrets/bridge.secrets "$ESPO_SSH:/root/kobo-espo-bridge.secrets"
fi
ssh $SSH_OPTS "$ESPO_SSH" KOBO_URL="$KOBO_URL" ESPO_HOST="$ESPO_HOST" CMD="$CMD" bash -s <<'REMOTE'
set -euo pipefail
cd /root/kobo-espo
chmod 600 /root/kobo-espo-kobo.token /root/kobo-espo-bridge.secrets 2>/dev/null || true
set -a; source /root/kobo-espo.secrets; source /root/kobo-espo-bridge.secrets; ESPO_SITE_URL=https://$ESPO_HOST; set +a
compose() { docker compose -p kobo-espo --profile bridge "$@"; }
case $CMD in
    # --no-deps: never recreate EspoCRM itself from here
    # restart too: the code is mounted, and a running bridge has the old one loaded
    up) compose up -d --no-deps bridge-intake bridge-volunteers bridge-sites bridge-site-visits
        compose restart bridge-intake bridge-volunteers bridge-sites bridge-site-visits ;;
    down) compose stop bridge-intake bridge-volunteers bridge-sites bridge-site-visits ;;
    logs) compose logs --tail 40 bridge-intake bridge-volunteers bridge-sites bridge-site-visits ;;
esac
REMOTE
