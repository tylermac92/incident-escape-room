# Incident Escape Room

## Safety first

Everything in this game is a simulation of a made-up store, running on your own computer. Actions in the game change only that simulation. The game has no setting that targets any other system, by design. Never practice these actions on real or shared systems.

## Status

Phase 0 (safety rails) in progress: `make up` and `make down` work, but there is no gameplay yet. The design is in [`docs/technical-design-document.md`](docs/technical-design-document.md) and the work plan in [`docs/tickets.md`](docs/tickets.md).

## Layout

| Path | What it is |
|---|---|
| `sim/` | Simulation engine (Python 3.12, uv). Must never import `controller`. |
| `controller/` | Game controller (Python 3.12, FastAPI, uv). |
| `isolation/` | Isolation checks (standard library only): the runtime self-check used by `sim` and `controller`, plus the host-side checkers run by `host/` scripts. |
| `ui/` | Player UI (React + TypeScript, Vite). All copy lives in `ui/src/strings/en.json`. |
| `ui/nginx/` | The edge config: serves the UI, proxies `/api` only to `controller:8000`. `check.sh` enforces that policy. |
| `compose.yaml` | The disposable Compose project: networks, hardening, health checks, startup order. |
| `host/` | Host-side scripts behind the make targets (POSIX sh; the host needs only Docker and Make). |

## Running

Needs Docker Engine 28.0 or later with the Compose (v2.20+) and buildx plugins, on Linux or on macOS with Colima, and GNU Make.

```bash
make up
```

`make up` checks that the Docker engine is this computer's own, that the runtime and versions are supported, that port 8080 on 127.0.0.1 is free (set `ESCAPE_PORT` to change it), and that the Compose config passes the isolation policy. It then builds any missing images, starts the stack, checks the running networks from the host, and prints the URL. If any check fails, it tears everything down and exits non-zero; `KEEP_ON_FAIL=1` instead leaves a started stack running with the game locked, for debugging.

```bash
make down
```

`make status` shows this project's containers and their health, and `make logs` streams their logs.

`make export-results` copies your results file out of the running game to `./escape-results-<UTC timestamp>.jsonl` and prints the number of rounds and the field names. It refuses to export a file with any player-identifying field. Nothing is ever uploaded: the game never sends data anywhere, and this copy is yours. `make down` does not delete it.

`make down` removes this project's containers, networks, volume and built images, and nothing else. It never prunes. If anything labeled as this project's remains, it lists it and suggests `make down FORCE=1`, which removes only resources carrying the project label.

## Building

`make build` builds the three container images (`incident-escape-room-sim`, `-controller`, `-ui`) with Docker. Only this step needs network access, to fetch the pinned base images and locked dependencies; the built images install nothing when they start.

```bash
make build
```

## Dev mode

```bash
make dev
```

`make dev` runs the same checks as `make up` with `compose.dev.yaml` applied. `./sim`, `./controller` and `./ui` are mounted read-only into their containers. `sim` and `controller` restart when their Python source changes, and `ui` runs the Vite dev server with hot reload, on the same single port, `127.0.0.1:8080`. The page shows a "DEV BUILD" ribbon. The network shape is unchanged: `sim` and `controller` stay on the internal network only. `make up` never applies the dev override, and its policy check rejects one passed to it. Stop with `make down`.

Running Vite directly on the host (`npm run dev`) is not supported: the game's API is reachable only inside the containers. On Colima, the repository must be under a directory Colima shares with its VM (your home directory by default); `make dev` warns if it is not.

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

Run the tests with `make test`. After the unit suites and the self-tests of the nginx proxy policy and the engine guard, it starts a stack in the test profile (`compose.test.yaml`, which sets `ESCAPE_TEST_MODE=1`) through the same checks as `make up`, and tears it down afterward, keeping the images. It needs uv and Docker, and refuses to run while a `make up` stack is running. For a quick run of one package, use `cd sim && uv run --locked pytest -q`.

The individual checks can also be run on their own. `make check-compose` checks the rendered Compose config against the isolation policy and writes `.escape/preflight-report`. Add `PROFILE=dev` or `PROFILE=test` for those profiles; `ESCAPE_DEV` and `ESCAPE_TEST_MODE` are each allowed only in their own profile. It needs only Docker: the check runs in a container with no network.

`make verify-isolation` checks the running stack from the host: `escape_internal` is internal, `sim` and `controller` are attached only to it, and `ui` is attached to it and `escape_edge`.
