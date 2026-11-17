# Incident Escape Room

## Safety first

Everything in this game is a simulation of a made-up store, running on your own computer. Actions in the game change only that simulation. The game has no setting that targets any other system, by design. Never practice these actions on real or shared systems.

## Status

Scaffolding only (ticket ENV-01). The design is in [`docs/technical-design-document.md`](docs/technical-design-document.md) and the work plan in [`docs/tickets.md`](docs/tickets.md).

## Layout

| Path | What it is |
|---|---|
| `sim/` | Simulation engine (Python 3.12, uv). Must never import `controller`. |
| `controller/` | Game controller (Python 3.12, FastAPI, uv). |
| `ui/` | Player UI (React + TypeScript, Vite). All copy lives in `ui/src/strings/en.json`. |

## Building

`make build` builds the three container images (`incident-escape-room-sim`, `-controller`, `-ui`) with Docker. Only this step needs network access, to fetch the pinned base images and locked dependencies; the built images install nothing when they start.

```bash
make build
```

## Building packages without Docker

For working on one package, with [uv](https://docs.astral.sh/uv/) and Node.js 22 with npm:

```bash
cd sim && uv sync --locked && uv build
```

```bash
cd controller && uv sync --locked && uv build
```

```bash
cd ui && npm ci && npm run build
```

Run the tests with `make test`.
