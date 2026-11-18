#!/bin/sh
# ENV-09: create a verified, isolated environment, or fail closed (TDD §4.7, §5.6).
# Order: engine guard, runtime preflight, port, static policy, build if missing,
# up --wait, host-side verification. Any failure tears down, unless KEEP_ON_FAIL=1
# and the stack had already started: then it stays up with the controller locked.
# Usage: host/up.sh [player|test]; test is used only by make test (ENV-11).
set -u
. host/lib.sh
profile=${1:-player}
case $profile in player|test) ;; *) echo "profile must be player or test" >&2; exit 2 ;; esac
port=${ESCAPE_PORT:-8080}
rendered=.escape/compose.$profile.json

fail() {  # fail <what failed> <fix hint>
    echo "make up: FAILED: $1" >&2
    echo "  fix: $2" >&2
}
fail_closed() {  # tear down, then exit non-zero
    fail "$1" "$2"
    echo "make up: tearing down (fail closed)." >&2
    sh host/down.sh >/dev/null 2>&1 || echo "make up: teardown incomplete; run make down" >&2
    exit 1
}
fail_after_start() {
    fail "$1" "$2"
    if [ "${KEEP_ON_FAIL:-0}" = 1 ]; then
        # The controller reports this marker as the failed check `host_check` (tmpfs: gone on restart).
        docker compose -p "$PROJECT" exec -T controller sh -c ': > /tmp/escape-host-lock' 2>/dev/null \
            || echo "make up: controller is not running, so there is nothing to lock." >&2
        echo "make up: KEEP_ON_FAIL=1: leaving the stack running with the game locked; make down when done." >&2
        exit 1
    fi
    echo "make up: tearing down (fail closed)." >&2
    sh host/down.sh >/dev/null 2>&1 || echo "make up: teardown incomplete; run make down" >&2
    exit 1
}

# 1. The engine must be this computer's (checked before anything contacts it).
guard=$(sh host/engine_guard.sh) || exit 1
context=${guard%% *} endpoint=${guard#* }

# 2. Supported runtime, versions, resources (ENV-13).
version=$(docker version --format '{{json .}}' 2>/dev/null) \
    || { fail "cannot reach the Docker engine at $endpoint" "start Docker (or Colima), then retry"; exit 1; }
mkdir -p .escape
{ printf '{"version":%s,"info":' "$version"; docker info --format '{{json .}}'; echo '}'; } > .escape/runtime.json
runtime=$(run_checker host_runtime.py --context "$context" --endpoint "$endpoint" \
    --compose "$(docker compose version --short 2>/dev/null)" \
    --buildx "$(docker buildx version 2>/dev/null)" < .escape/runtime.json)
status=$?
echo "$runtime"
[ "$status" = 0 ] || { fail "host runtime preflight" "see the FAIL lines above"; exit 1; }

# 3. The port is free on 127.0.0.1, unless it is our own ui from an earlier make up.
case $port in
    ''|*[!0-9]*) fail "ESCAPE_PORT=$port is not a port number" "make up ESCAPE_PORT=8081"; exit 1 ;;
esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { fail "ESCAPE_PORT=$port is out of range" "make up ESCAPE_PORT=8081"; exit 1; }
ours=$(docker ps -q --filter "$PROJECT_FILTER" --filter label=com.docker.compose.service=ui --filter status=running)
if [ -z "$ours" ] && command -v bash >/dev/null \
    && bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1"' _ "$port" 2>/dev/null; then
    fail "port $port on 127.0.0.1 is already in use" "stop what is using it, or make up ESCAPE_PORT=8081"
    exit 1
fi

# 4. Static isolation policy (ENV-06). Writes the rendered config we start from.
sh host/check-compose.sh "$profile" \
    || fail_closed "static isolation policy" "remove the override or setting named above; see .escape/preflight-report"

# 5. Build only if an image is missing (a prepared machine plays offline).
if ! docker image inspect "$PROJECT-sim" "$PROJECT-controller" "$PROJECT-ui" >/dev/null 2>&1; then
    docker compose -f "$rendered" --project-directory . build \
        || fail_closed "image build" "check the build output above; the first build needs network access"
fi

# 6. Start exactly the config that passed the policy check.
if ! docker compose -f "$rendered" --project-directory . up -d --wait --wait-timeout 180; then
    docker compose -p "$PROJECT" ps -a --format '{{.Service}} {{.State}} {{.Health}}' |
        while read -r service state health; do
            case "$state/$health" in
                running/healthy|running/) ;;
                created/*) echo "make up: $service did not start (it waits for a healthy dependency)" >&2 ;;
                *)  echo "make up: $service is $state${health:+ ($health)}; its last 50 log lines:" >&2
                    docker compose -p "$PROJECT" logs --no-color --tail 50 "$service" >&2 ;;
            esac
        done
    fail_after_start "a service did not become healthy" "see the service and logs above; make status"
fi

# 7. Host-side verification of the running state (ENV-08).
sh host/verify-isolation.sh \
    || fail_after_start "host-side isolation verification" "see the FAIL lines above"

echo "$runtime" | head -n 1
echo "Ready: http://127.0.0.1:$port"
