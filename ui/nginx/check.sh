#!/bin/sh
# Edge proxy policy (ENV-05, T-ISO-4): nginx may reach only controller:8000.
# Usage: check.sh [nginx.conf]. Prints the broken rule and exits 1 on a violation.
set -eu
conf=${1:-$(dirname "$0")/nginx.conf}
body=$(sed 's/#.*//' "$conf")
fail() { echo "nginx policy: $1 ($conf)" >&2; exit 1; }
count() { printf '%s\n' "$body" | grep -cE "$1" || true; }

[ "$(count '^[[:space:]]*upstream[[:space:]]')" = 1 ] || fail "need exactly one upstream block"
[ "$(count '^[[:space:]]*server[[:space:]]+[^{;]+;')" = 1 ] || fail "need exactly one upstream server"
[ "$(count '^[[:space:]]*server[[:space:]]+controller:8000;')" = 1 ] || fail "the upstream server must be controller:8000"
[ "$(count '(^|[[:space:]])resolver[[:space:]]')" = 0 ] || fail "no resolver directive allowed"
[ "$(count '_pass[[:space:]]')" = "$(count '^[[:space:]]*proxy_pass http://controller;')" ] \
    || fail "every proxy target must be exactly http://controller"
[ "$(count '^[[:space:]]*include[[:space:]]')" = "$(count '^[[:space:]]*include /etc/nginx/mime.types;')" ] \
    || fail "only mime.types may be included"
echo "nginx policy: ok"
