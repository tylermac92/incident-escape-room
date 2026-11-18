# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
# The logic lives in host/*.sh (POSIX sh), so the host needs only Docker and Make.
.PHONY: build test check-compose verify-isolation up down status logs dev

PROFILE ?= player

# Compose names images <project>-<service>, so `down --rmi local` removes them (ENV-10).
# The python base is pulled too, so the host checkers work offline afterwards.
build:
	docker compose build
	. host/lib.sh && docker pull -q "$$PYTHON_IMAGE"

test:
	for p in isolation sim controller; do (cd $$p && uv run --locked pytest -q) || exit 1; done
	sh ui/nginx/check_test.sh
	sh host/engine_guard_test.sh

# Static isolation policy (ENV-06, TDD §5.5) over the rendered config. PROFILE=player|dev.
check-compose:
	@sh host/check-compose.sh $(PROFILE)

# Host-side check after `up` (ENV-08, TDD §5.5).
verify-isolation:
	@sh host/verify-isolation.sh

# Preflight, start, verify; fail closed (ENV-09). KEEP_ON_FAIL=1 keeps a started stack, locked.
up:
	@ESCAPE_PORT=$(ESCAPE_PORT) KEEP_ON_FAIL=$(KEEP_ON_FAIL) sh host/up.sh

# Project-scoped teardown (ENV-10). FORCE=1 also removes leftovers selected only by the label.
down:
	@FORCE=$(FORCE) sh host/down.sh

status logs dev:
	@echo "make $@ is not implemented yet (see docs/tickets.md, ENV-11 and ENV-12)." >&2
	@exit 1
