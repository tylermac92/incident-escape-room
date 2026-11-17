# Incident Escape Room. Every target is scoped to this project only (TDD §4.7).
.PHONY: build test up down status logs dev

# shortcut: builds packages locally; ENV-02 switches this to building container images.
build:
	cd sim && uv sync --locked && uv build
	cd controller && uv sync --locked && uv build
	cd ui && npm ci && npm run build

test:
	cd sim && uv run --locked pytest -q

up down status logs dev:
	@echo "make $@ is not implemented yet (see docs/tickets.md, ENV-09 to ENV-12)." >&2
	@exit 1
