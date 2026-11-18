#!/bin/sh
# ENV-06: static isolation policy (TDD §5.5) over the rendered config.
# Usage: host/check-compose.sh player|dev. Writes .escape/compose.<profile>.json and .escape/preflight-report.
set -u
. host/lib.sh
profile=${1:-player}
case $profile in player|dev) ;; *) echo "profile must be player or dev" >&2; exit 2 ;; esac
[ "$profile" = dev ] && profile_arg="--profile dev" || profile_arg=""

mkdir -p .escape
# shellcheck disable=SC2086  # profile_arg is empty or two words
docker compose $profile_arg config --format json > ".escape/compose.$profile.json" || exit 1
run_checker compose_policy.py --profile "$profile" --root "$PWD" \
    < ".escape/compose.$profile.json" > .escape/preflight-report
status=$?
cat .escape/preflight-report
exit $status
