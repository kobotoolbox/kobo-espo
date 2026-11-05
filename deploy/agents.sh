#!/usr/bin/env bash
# Start (or restart) the agent runner on the test droplet (plans/espo-agents-plan.md).
#
#   deploy/agents.sh          sync (an API user and role per Agent), then the runner up
#   deploy/agents.sh sync     only the users, roles and keys (after adding an Agent)
#   deploy/agents.sh down     stop the runner (EspoCRM keeps running)
#   deploy/agents.sh logs     its log
#
# The agents' keys go to /root/kobo-espo-agents.secrets on the droplet (mode 600), and
# ANTHROPIC_API_KEY from .env to /root/kobo-espo-agents.env (mode 600). Without a key the
# runner still runs rules-only agents; agents with a model fail their runs (see the runs).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
SSH_OPTS="-o ControlMaster=auto -o ControlPath=/tmp/kobo-espo-ssh-%C -o ControlPersist=10m"
CMD=${1:-up}
if [[ $CMD == up || $CMD == sync ]]; then
    [[ $CMD == up ]] && deploy/up.sh >/dev/null
    python3 -I agents/sync.py --url "https://$ESPO_HOST" --secrets secrets/agents.secrets | tail -1
    env=$(mktemp); trap 'rm -f "$env"' EXIT
    ( umask 077; printf 'ANTHROPIC_API_KEY=%s\nAGENTS_LLM=%s\n' "${ANTHROPIC_API_KEY:-}" "${AGENTS_LLM:-real}" > "$env" )
    scp $SSH_OPTS -q secrets/agents.secrets "$ESPO_SSH:/root/kobo-espo-agents.secrets"
    scp $SSH_OPTS -q "$env" "$ESPO_SSH:/root/kobo-espo-agents.env"
fi
[[ $CMD == sync ]] && exit 0
ssh $SSH_OPTS "$ESPO_SSH" ESPO_HOST="$ESPO_HOST" CMD="$CMD" bash -s <<'REMOTE'
set -euo pipefail
cd /root/kobo-espo
chmod 600 /root/kobo-espo-agents.secrets /root/kobo-espo-agents.env 2>/dev/null || true
# (the bridges' settings too, only so compose can read the whole file without warnings)
set -a; source /root/kobo-espo.secrets; source /root/kobo-espo-agents.env
source /root/kobo-espo-bridge.secrets 2>/dev/null || true; KOBO_URL=${KOBO_URL:-}; ESPO_SITE_URL=https://$ESPO_HOST; set +a
compose() { docker compose -p kobo-espo --profile agents "$@"; }
case $CMD in
    # --no-deps: never recreate EspoCRM itself from here; restart: the code is mounted
    up) compose up -d --no-deps agent-runner
        compose restart agent-runner ;;
    down) compose stop agent-runner ;;
    logs) compose logs --tail 60 agent-runner ;;
esac
REMOTE
