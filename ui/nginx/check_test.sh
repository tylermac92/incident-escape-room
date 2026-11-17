#!/bin/sh
# Self-test for check.sh: the real config passes and each unsafe variant fails.
set -eu
dir=$(dirname "$0")
conf=$dir/nginx.conf
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

"$dir/check.sh" "$conf" >/dev/null

expect_fail() {
    sed "$1" "$conf" > "$tmp"
    if "$dir/check.sh" "$tmp" 2>/dev/null; then echo "check.sh missed: $2" >&2; exit 1; fi
}
expect_fail 's|server controller:8000;|server controller:8000;\n        server evil.example:80;|' "second upstream server"
expect_fail 's|server controller:8000;|server evil.example:80;|' "wrong upstream"
expect_fail 's|upstream controller {|resolver 1.1.1.1;\n    upstream controller {|' "resolver"
expect_fail '0,/proxy_pass http:\/\/controller;/s||proxy_pass http://$arg_target;|' "variable proxy target"
expect_fail 's|proxy_http_version 1.1;|grpc_pass grpc://evil.example:80;|' "other *_pass"
expect_fail 's|include /etc/nginx/mime.types;|include /etc/nginx/conf.d/*.conf;|' "extra include"
expect_fail 's|^    }$|    }\n    upstream other { server controller:8000; }|' "second upstream block"
echo "nginx policy self-test: ok"
