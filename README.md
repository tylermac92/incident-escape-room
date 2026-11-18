# Incident Escape Room

## Safety first

Everything in this game is a simulation of a made-up store, running on your own computer. Actions in the game change only that simulation. The game has no setting that targets any other system, by design. Never practice these actions on real or shared systems.

## Status

Phase 0 (safety rails) in progress: no gameplay yet. The design is in [`docs/technical-design-document.md`](docs/technical-design-document.md) and the work plan in [`docs/tickets.md`](docs/tickets.md).

## Layout

| Path | What it is |
|---|---|
| `sim/` | Simulation engine (Python 3.12, uv). Must never import `controller`. |
| `controller/` | Game controller (Python 3.12, FastAPI, uv). |
| `isolation/` | Isolation checks (standard library only): the runtime self-check used by `sim` and `controller`, and the static Compose policy (`compose_policy.py`). |
| `ui/` | Player UI (React + TypeScript, Vite). All copy lives in `ui/src/strings/en.json`. |
| `ui/nginx/` | The edge config: serves the UI, proxies `/api` only to `controller:8000`. `check.sh` enforces that policy. |
| `compose.yaml` | The disposable Compose project: networks, hardening, health checks, startup order. |

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

Run the tests with `make test`. It also checks the nginx proxy policy.

`make check-compose` checks the rendered Compose config against the isolation policy and writes `.escape/preflight-report`. Add `PROFILE=dev` for the dev profile. It needs only Docker: the check runs in a container with no network.
