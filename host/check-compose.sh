#!/bin/sh
# ENV-06: static isolation policy (TDD §5.5) over the rendered config.
# Usage: host/check-compose.sh player|dev|test. Writes .escape/compose.<profile>.json and .escape/preflight-report.
set -u
. host/lib.sh
profile=${1:-player}
case $profile in
    player) files="" ;;
    dev) files="-f compose.yaml -f compose.dev.yaml" ;;  # make dev only (ENV-12)
    test) files="-f compose.yaml -f compose.test.yaml" ;;  # make test only (ENV-11)
    *) echo "profile must be player, dev or test" >&2; exit 2 ;;
esac

mkdir -p .escape
# shellcheck disable=SC2086  # files is a short word list
docker compose $files config --format json > ".escape/compose.$profile.json" || exit 1
run_checker compose_policy.py --profile "$profile" --root "$PWD" \
    < ".escape/compose.$profile.json" > .escape/preflight-report
status=$?
cat .escape/preflight-report
exit $status
