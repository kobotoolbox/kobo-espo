#!/usr/bin/env bash
# Start (or restart) the bridge on the test droplet, polling Kobo staging.
#
#   deploy/bridges.sh          compose --profile bridge up: one service for every connection,
#                              and the EspoCRM MCP (https://ESPO_HOST/bridge/mcp)
#   deploy/bridges.sh down     stop them (EspoCRM keeps running)
#   deploy/bridges.sh logs     their logs
#
# The service (kobo-espo-bridge's `bridge.py serve`) runs the Kobo connections in EspoCRM
# and does their setup itself, as admin. kobo-espo's four forms are connections like any
# other: made from kobo/templates the first time (`serve adopt`), then edited in EspoCRM.
# The files stay as the tests' fixtures; a change to one doesn't reach the droplet.
# Needs KOBO_URL and KOBO_TOKEN in .env: a throwaway test account (on a production server
# only with KOBO_TEST_ACCOUNT_ON_PRODUCTION=yes). The token goes to
# /root/kobo-espo-kobo.token on the droplet (mode 600). The API keys setup makes are in
# /root/kobo-espo-bridge.secrets (mode 600), the first time a copy of secrets/bridge.secrets.
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
    scp $SSH_OPTS -q "$token" "$ESPO_SSH:/root/kobo-espo-kobo.token"
    if [[ -f secrets/bridge.secrets ]] && ! ssh $SSH_OPTS "$ESPO_SSH" test -s /root/kobo-espo-bridge.secrets; then
        scp $SSH_OPTS -q secrets/bridge.secrets "$ESPO_SSH:/root/kobo-espo-bridge.secrets"
    fi
fi
ssh $SSH_OPTS "$ESPO_SSH" KOBO_URL="$KOBO_URL" ESPO_HOST="$ESPO_HOST" CMD="$CMD" bash -s <<'REMOTE'
set -euo pipefail
cd /root/kobo-espo
touch /root/kobo-espo-bridge.secrets
chmod 600 /root/kobo-espo-kobo.token /root/kobo-espo-bridge.secrets 2>/dev/null || true
set -a; source /root/kobo-espo.secrets; ESPO_SITE_URL=https://$ESPO_HOST; set +a
compose() { docker compose -p kobo-espo --profile bridge "$@"; }
case $CMD in
    up)
        # Before the one service there was a container per template, its state named after
        # it (up.sh has removed those containers as orphans): the state moves to the names
        # serve uses, before it starts, so nothing is rescanned
        compose stop bridge >/dev/null 2>&1 || true
        docker run --rm -v kobo-espo_bridge-state:/state python:3.13-slim sh -c 'cd /state &&
            for p in intake:support-request volunteers:volunteer sites:site-registration site-visits:site-visit; do
                o=${p%%:*}; n=${p#*:}; if [ -d "$o" ] && [ ! -e "$n" ]; then mv "$o" "$n"; echo "state: $o -> $n"; fi
            done'
        # The templates as connection records: made from the files if there are none yet,
        # and, where the service still ran them as files, their state moved to the records'
        # (once; after that, the records are the connections)
        compose run --rm --no-deps -v /root/kobo-espo/kobo/templates:/adopt:ro bridge \
            sh -c 'python3 -I /bridge/bridge.py serve adopt /adopt/*.toml' \
            || echo "adopt failed (above): those connections don't run until it's fixed" >&2
        # --no-deps: never recreate EspoCRM itself from here
        # restart too: the code is mounted, and a running bridge has the old one loaded
        compose up -d --no-deps --build bridge bridge-mcp
        compose restart bridge bridge-mcp
        # Caddy has deploy/Caddyfile mounted as a file: it sees a new one only once restarted
        if ! docker compose -p kobo-espo --profile tls exec -T caddy cat /etc/caddy/Caddyfile | cmp -s - deploy/Caddyfile; then
            docker compose -p kobo-espo --profile tls restart caddy
        fi ;;
    down) compose stop bridge bridge-mcp ;;
    logs) compose logs --tail 60 bridge bridge-mcp ;;
esac
REMOTE
