# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
.PHONY: build test up down status logs dev

# Compose names images <project>-<service>, so `down --rmi local` removes them (ENV-10).
build:
	docker compose build

test:
	cd sim && uv run --locked pytest -q

up down status logs dev:
	@echo "make $@ is not implemented yet (see docs/tickets.md, ENV-09 to ENV-12)." >&2
	@exit 1
