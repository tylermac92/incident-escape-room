# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
# The logic lives in host/*.sh (POSIX sh), so the host needs only Docker and Make.
.PHONY: build test check-compose verify-isolation up down status logs dev

PROFILE ?= player
# ENV-13: every target that talks to Docker first refuses an engine that is not this computer's.
GUARD = @sh host/engine_guard.sh >/dev/null

# Compose names images <project>-<service>, so `down --rmi local` removes them (ENV-10).
# The python base is pulled too, so the host checkers work offline afterwards.
build:
	$(GUARD)
	docker compose build
	. host/lib.sh && docker pull -q "$$PYTHON_IMAGE"

# Unit suites and self-tests, then a stack in the test profile (ESCAPE_TEST_MODE=1), torn down after.
test:
	for p in isolation sim controller; do (cd $$p && uv run --locked pytest -q) || exit 1; done
	sh ui/nginx/check_test.sh
	sh host/engine_guard_test.sh
	@ESCAPE_PORT=$(ESCAPE_PORT) sh host/test-stack.sh

# Static isolation policy (ENV-06, TDD §5.5) over the rendered config. PROFILE=player|dev|test.
check-compose:
	$(GUARD)
	@sh host/check-compose.sh $(PROFILE)

# Host-side check after `up` (ENV-08, TDD §5.5).
verify-isolation:
	$(GUARD)
	@sh host/verify-isolation.sh

# Preflight, start, verify; fail closed (ENV-09). KEEP_ON_FAIL=1 keeps a started stack, locked.
up:
	@ESCAPE_PORT=$(ESCAPE_PORT) KEEP_ON_FAIL=$(KEEP_ON_FAIL) sh host/up.sh

# Project-scoped teardown (ENV-10). FORCE=1 also removes leftovers selected only by the label.
down:
	$(GUARD)
	@FORCE=$(FORCE) sh host/down.sh

# Both scoped by project name (ENV-11): only this project's containers and logs.
status:
	$(GUARD)
	@docker compose -p incident-escape-room ps -a

logs:
	$(GUARD)
	@docker compose -p incident-escape-room logs -f --tail 100

# Hot-reload dev mode (ENV-12): compose.dev.yaml, the same checks, the same single port.
dev:
	@ESCAPE_PORT=$(ESCAPE_PORT) KEEP_ON_FAIL=$(KEEP_ON_FAIL) sh host/up.sh dev
