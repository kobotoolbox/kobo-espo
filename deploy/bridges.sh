#!/usr/bin/env bash
# Start (or restart) the bridge on the test droplet, polling Kobo staging.
#
#   deploy/bridges.sh          compose --profile bridge up: one service for every connection
#   deploy/bridges.sh down     stop it (EspoCRM keeps running)
#   deploy/bridges.sh logs     its log
#
# The service (kobo-espo-bridge's `bridge.py serve`) runs the templates in kobo/templates
# and the Kobo connections made in EspoCRM, and does their setup itself, as admin.
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
        # Before the one service: a container per template, with its state named after it
        old=$(docker ps -aq --filter name='^kobo-espo-bridge-(intake|volunteers|sites|site-visits)-1$')
        if [[ -n $old ]]; then
            docker rm -f $old >/dev/null
            compose run --rm --no-deps -T --entrypoint sh bridge -c 'cd /state &&
                for p in intake:support-request volunteers:volunteer sites:site-registration site-visits:site-visit; do
                    o=${p%%:*}; n=${p#*:}; if [ -d "$o" ] && [ ! -e "$n" ]; then mv "$o" "$n"; echo "state: $o -> $n"; fi
                done'
        fi
        # --no-deps: never recreate EspoCRM itself from here
        # restart too: the code is mounted, and a running bridge has the old one loaded
        compose up -d --no-deps bridge
        compose restart bridge ;;
    down) compose stop bridge ;;
    logs) compose logs --tail 60 bridge ;;
esac
REMOTE
