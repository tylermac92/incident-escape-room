#!/bin/sh
# Self-test for engine_guard.sh: local sockets pass, every remote endpoint is refused.
# A stub `docker` on PATH answers context questions; no engine is needed.
set -eu
guard=$(cd "$(dirname "$0")" && pwd)/engine_guard.sh
stub=$(mktemp -d)
trap 'rm -r "$stub"' EXIT
cat > "$stub/docker" <<'EOF'
#!/bin/sh
case "$1 $2" in
    "context show") echo "$STUB_CONTEXT" ;;
    "context inspect") echo "$STUB_ENDPOINT" ;;
    *) echo "unexpected docker call: $*" >&2; exit 99 ;;
esac
EOF
chmod +x "$stub/docker"

expect() {  # expect pass|refuse DOCKER_HOST CONTEXT ENDPOINT
    if out=$(PATH="$stub:$PATH" DOCKER_HOST=$2 STUB_CONTEXT=$3 STUB_ENDPOINT=$4 sh "$guard" 2>&1); then got=pass; else got=refuse; fi
    [ "$got" = "$1" ] || { echo "engine_guard: expected $1 for DOCKER_HOST='$2' context=$3 endpoint=$4, got: $out" >&2; exit 1; }
}
expect pass   ""                        default        unix:///var/run/docker.sock
expect pass   ""                        colima         "unix:///Users/me/.colima/default/docker.sock"
expect pass   ""                        desktop-linux  unix:///Users/me/.docker/run/docker.sock
expect pass   ""                        desktop-windows npipe:////./pipe/dockerDesktopLinuxEngine
expect pass   unix:///run/user/1000/docker.sock default unix:///var/run/docker.sock
expect refuse ""                        remote         tcp://10.0.0.5:2376
expect refuse ""                        build-box      ssh://me@build-box
expect refuse tcp://192.168.1.20:2375   default        unix:///var/run/docker.sock
expect refuse ssh://me@server           default        unix:///var/run/docker.sock
expect refuse ""                        broken         ""
echo "engine guard self-test: ok"
