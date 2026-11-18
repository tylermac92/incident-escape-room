#!/bin/sh
# ENV-13: refuse any Docker engine that is not on this computer. It only asks the docker
# client for its configuration, so it runs before anything contacts the engine.
# Prints "<context> <endpoint>" on success.
set -u
if [ -n "${DOCKER_HOST:-}" ]; then
    context=default endpoint=$DOCKER_HOST  # DOCKER_HOST overrides any context
else
    context=$(docker context show) || exit 1
    endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}') || exit 1
fi
case $endpoint in
    unix://*|npipe://*) echo "$context $endpoint" ;;
    *)
        echo "The game must run on this computer's own Docker engine." >&2
        echo "  The active Docker endpoint is $endpoint (context $context)." >&2
        echo "  fix: unset DOCKER_HOST, or switch to a local context with 'docker context use'." >&2
        exit 1 ;;
esac
