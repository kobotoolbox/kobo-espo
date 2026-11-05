#!/usr/bin/env bash
# Every test, against the test droplet. ./tests/run_all.sh [--kobo real]
#   - kobo-espo-bridge's unit tests (no network)
#   - espo/seed (idempotent: makes sure EspoCRM is as the tests expect)
#   - isolation (T8-T11, T13, T15, T16), workflow B (T14), connection (T1-T7, T12, C1-C3)
# Results: tests/results/*.json
set -uo pipefail
cd "$(dirname "$0")/.."
BRIDGE=${KOBO_ESPO_BRIDGE_DIR:-../kobo-espo-bridge}
fail=0
( cd "$BRIDGE" && PYTHONPATH=.:tests python3 -m unittest discover -s tests 2>&1 | tail -1 ) || fail=1
python3 -I espo/seed/seed.py --users > /dev/null || fail=1
for t in isolation workflow_b; do python3 -I tests/cases/$t.py | tail -1 || fail=1; done
python3 -I tests/cases/connection.py "$@" | tail -1 || fail=1
exit $fail
