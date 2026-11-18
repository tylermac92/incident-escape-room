#!/bin/sh
# ENV-11: the stack stage of `make test`. Starts the test profile (ESCAPE_TEST_MODE=1) through
# the same preflight and isolation checks as make up, runs the stack checks, and always tears
# down afterward, keeping the images.
set -u
. host/lib.sh

# Both stacks are the one Compose project, so never take over a stack a player started.
if [ -n "$(docker ps -aq --filter "$PROJECT_FILTER")" ]; then
    echo "make test: this project's stack is already running; run make down first." >&2
    exit 1
fi
export KEEP_IMAGES=1  # read by down.sh, including up.sh's fail-closed teardown
trap 'sh host/down.sh >/dev/null' EXIT

sh host/up.sh test || exit 1

# shortcut: until QA-18 wires the §15 suites in here, only check that the test profile took effect.
for service in sim controller; do
    if [ "$(docker compose -p "$PROJECT" exec -T "$service" printenv ESCAPE_TEST_MODE)" != 1 ]; then
        echo "make test: $service is not running with ESCAPE_TEST_MODE=1" >&2
        exit 1
    fi
done
echo "test stack: ok"
