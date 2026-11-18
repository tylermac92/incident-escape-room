# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
.PHONY: build test check-compose up down status logs dev

# The same pinned base as sim/ and controller/Dockerfile; it also runs the compose policy check.
PYTHON_IMAGE := python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
PROFILE ?= player

# Compose names images <project>-<service>, so `down --rmi local` removes them (ENV-10).
# The python base is pulled too, so check-compose works offline afterwards.
build:
	docker compose build
	docker pull -q $(PYTHON_IMAGE)

test:
	for p in isolation sim controller; do (cd $$p && uv run --locked pytest -q) || exit 1; done
	sh ui/nginx/check_test.sh

# Static isolation policy (ENV-06, TDD §5.5) over the rendered config. PROFILE=player|dev.
# The checker runs in a throwaway container with no network, so the host needs only Docker.
check-compose:
	@test "$(PROFILE)" = player || test "$(PROFILE)" = dev || { echo "PROFILE must be player or dev" >&2; exit 2; }
	@mkdir -p .escape
	@docker compose $(if $(filter dev,$(PROFILE)),--profile dev) config --format json > .escape/compose.$(PROFILE).json
	@docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
		--user 65534:65534 --label com.incident-escape-room.managed=true $(PYTHON_IMAGE) \
		python -c "$$(cat isolation/src/isolation/compose_policy.py)" --profile $(PROFILE) --root "$(CURDIR)" \
		< .escape/compose.$(PROFILE).json > .escape/preflight-report; \
		status=$$?; cat .escape/preflight-report; exit $$status

up down status logs dev:
	@echo "make $@ is not implemented yet (see docs/tickets.md, ENV-09 to ENV-12)." >&2
	@exit 1
