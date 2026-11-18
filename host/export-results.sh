#!/bin/sh
# ENV-14 (D-04): copy the results file out of the controller on purpose. Nothing is uploaded,
# and no bind mount is added: the copy uses `docker compose cp`. The exported file belongs to
# the user, and make down never deletes it.
set -u
. host/lib.sh
fail() { echo "make export-results: $1" >&2; exit 1; }

running=$(docker ps -q --filter "$PROJECT_FILTER" --filter label=com.docker.compose.service=controller --filter status=running)
[ -n "$running" ] || fail "the game is not running, so there is nothing to export; start it with make up"

mkdir -p .escape
staged=.escape/results-export.jsonl
docker compose -p "$PROJECT" cp controller:/data/results.jsonl "$staged" >/dev/null 2>&1 \
    || fail "there are no results yet; complete a round first"

# Summary and privacy check; on any problem nothing is exported.
run_checker results_export.py < "$staged" || fail "nothing was exported"

out="escape-results-$(date -u +%Y%m%dT%H%M%SZ).jsonl"
mv "$staged" "$out"
echo "Exported to ./$out (stays on this computer; make down does not delete it)."
