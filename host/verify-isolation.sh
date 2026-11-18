#!/bin/sh
# ENV-08: after `up`, check from the host that running networks and attachments match the policy.
set -u
. host/lib.sh
nets=$(docker network ls -q --filter "$PROJECT_FILTER")
ctrs=$(docker ps -q --filter "$PROJECT_FILTER")
mkdir -p .escape
# shellcheck disable=SC2086  # word-split ID lists
{
    printf '{"networks":'
    if [ -n "$nets" ]; then docker network inspect $nets; else echo '[]'; fi
    printf ',"containers":'
    if [ -n "$ctrs" ]; then docker inspect $ctrs; else echo '[]'; fi
    echo '}'
} > .escape/runtime-state.json
run_checker host_verify.py < .escape/runtime-state.json
