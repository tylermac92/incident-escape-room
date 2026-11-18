#!/bin/sh
# ENV-10: remove everything this project created and nothing else (TDD §4.7, SR-1).
# Never prunes, and never selects resources by name pattern. FORCE=1 additionally removes
# leftovers selected only by the project label. Safe to run twice, or when nothing is running.
set -u
. host/lib.sh

docker compose -p "$PROJECT" down --volumes --remove-orphans --rmi local

# shellcheck disable=SC2046  # word-split ID lists
if [ "${FORCE:-0}" = 1 ]; then
    ids=$(docker ps -aq --filter "label=$LABEL");     [ -z "$ids" ] || docker rm -f $ids
    ids=$(docker network ls -q --filter "label=$LABEL"); [ -z "$ids" ] || docker network rm $ids
    ids=$(docker volume ls -q --filter "label=$LABEL");  [ -z "$ids" ] || docker volume rm $ids
fi

rm -rf ./.escape

left=$(
    docker ps -a --filter "label=$LABEL" --format 'container {{.Names}} ({{.Status}})'
    docker network ls --filter "label=$LABEL" --format 'network {{.Name}}'
    docker volume ls --filter "label=$LABEL" --format 'volume {{.Name}}'
)
if [ -n "$left" ]; then
    echo "make down: these labeled resources are still present:" >&2
    echo "$left" | sed 's/^/  /' >&2
    echo "  fix: make down FORCE=1 (removes only resources labeled $LABEL)" >&2
    exit 1
fi
echo "make down: all project resources removed."
