# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
.PHONY: build test up down status logs dev

# Image names match Compose's default <project>-<service>, so `down --rmi local` removes them (ENV-03).
build:
	for s in sim controller ui; do docker build -t incident-escape-room-$$s $$s || exit 1; done

test:
	cd sim && uv run --locked pytest -q

up down status logs dev:
	@echo "make $@ is not implemented yet (see docs/tickets.md, ENV-09 to ENV-12)." >&2
	@exit 1
