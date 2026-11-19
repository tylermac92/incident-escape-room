# Incident Escape Room: Implementation Stories and Tickets (MVP), v3

## 1. Title and source

| | |
|---|---|
| **Source TDD** | *Incident Escape Room: Technical Design Document*, file `docs/technical-design-document.md` (status: draft for estimation and implementation kickoff) |
| **Scope of source** | First playable version (MVP). Stretch goals are out of scope. |
| **Revision** | v3: solo project (D-19). One person develops, tests, reviews, and approves everything. Builds on v2's decisions D-01 to D-18, including the Colima requirement. |
| **Reference convention** | `§n.n` = TDD section. `FR-`, `NFR-`, `SR-`, `AR-`, `OR-`, `SC-` = TDD requirement IDs. `T-*` = TDD test IDs (§15). |

---

## 2. Scope and planning assumptions

**Covered.** Every MVP requirement and design element in the TDD:

- Disposable environment and safety rails (§4, §5)
- Simulation engine and traffic (§8)
- The three scenarios and the action catalog (§7, §10)
- Game controller rules, scoring, APIs, and persistence (§6, §9, §11, §12)
- Player UI and accessibility (§9, §2.4)
- Failure handling (§13)
- Security, privacy, and content (§14)
- Test automation (§15)
- Playtesting, tuning, and release activities (§2.6, §15.7, §16)

**Not covered, by design.** The stretch goals, which are player-facing seeded replay and the post-game timeline (§1, §16.3), plus the other future work listed in §16.3. The extension points that the TDD requires inside MVP work (stored seed, `RoundEvent` log, `effect_class`) *are* covered, inside the relevant tickets.

**Planning assumptions and constraints**

1. **Greenfield project.** There is no existing system and no data migration. The only persisted data are the session mirror and the results file (§4.6), both created fresh.
2. **Unit tests sit inside implementation tickets.** §15.2 lists unit-test coverage per area. Each implementation ticket includes the matching unit tests in its acceptance criteria rather than in a separate ticket.
3. **Sequencing follows §16.1.** Phase 0 (safety rails) comes first, and phases overlap. Week estimates are not carried into tickets as deadlines.
4. **Fields not filled in.** Story points, priorities, and dates are not specified in the TDD and are not assigned here. Every ticket has the same owner: you, the sole developer (D-19).
5. **Defaults are configuration.** Values marked *(default)* in the TDD are implemented as scenario-pack or controller configuration, so tuning tickets can change them without code changes (§8.7, §17).
6. **Decisions are binding.** The former open questions UQ-01 to UQ-18 are decided as D-01 to D-18 (§6). Tickets cite the decision they implement. Where a decision supersedes TDD text, the TDD's decision addendum (§18) records it.

---

## 3. Epics / workstreams

| Epic | Prefix | Intended outcome | Main TDD sections |
|---|---|---|---|
| **E1: Disposable environment and safety rails** | `ENV` | `make up` / `make down` create and remove an isolated, labeled, fail-closed environment. Static and runtime isolation checks are in place before any game logic is built. | §4, §5, SR-1–SR-10, OR-1–OR-3, NFR-1, NFR-3, NFR-4 |
| **E2: Simulation engine** | `SIM` | A deterministic fixed-step model of `api`, `jobs`, `worker`, and `ledger`, driven by believable traffic. It emits metrics and bad-event counts over an internal link. | §3.1–§3.3, §8, NFR-2, NFR-5 |
| **E3: Scenarios, world data, and action effects** | `SCN` | The baseline world, three hidden fault scenarios with their signatures, evidence data, and the seven simulated actions, all confined to the simulation. | §7, §9.4, §10.1–§10.2, SR-6 |
| **E4: Game controller** | `CTL` | Session and round lifecycle, timers, health checks, alerts, impact and feed, action validation and budget, declaration, scoring, debrief, persistence, APIs and stream, resilience. | §3.2, §6, §9.3, §9.6–§9.8, §10.3, §11, §12, §13 |
| **E5: Player UI** | `UI` | The browser experience from welcome screen to session summary, with accessible status cues and clear separation of game failures from simulated ones. | §9, §2.4, §5.4, §6.6, §13, FR-1–FR-11 |
| **E6: Security, privacy, and content** | `SEC` | Pinned and scanned supply chain, enforced no-egress code in `sim`, local-only data handling, fictional content, reviewed copy, safety-first documentation. | §5.2, §5.4, §14, SR-10 |
| **E7: Test automation and verification** | `QA` | The automated proofs in §15: diagnosability, scoring, stability, feed integrity, spoiler-free stream, up/down scoping, isolation, NFR budgets, and CI. | §15, §2.6 SC-2a, SC-3, SC-5 |
| **E8: Self-testing, tuning, and release** | `REL` | Version traceability, host checks on your Colima laptop, self-play evidence and tuning, AI-proxy reviews, an honest success-criteria sign-off, and an offline-ready release candidate. | §2.6 SC-1, SC-2b/c, SC-4, §8.7, §15.7, §16, OR-4 |

---

## 4. Implementation tickets

### E1: Disposable environment and safety rails (`ENV`)

#### ENV-01 · Repository and package scaffolding

**Type:** Engineering task

**Description / value:** Create the monorepo layout with three packages: `sim` and `controller` (Python 3.12, FastAPI for `controller`) and `ui` (TypeScript/React). Add a top-level Makefile skeleton and lockfiles, so that every later ticket has a home and builds reproducibly.

**Acceptance criteria**
- Given a fresh clone, when a developer runs each package's documented local build command, then all three packages build with no network access other than the initial dependency fetch.
- `sim` and `controller` are separate Python packages. `sim` has no import dependency on `controller`.
- Python dependencies are locked with hashes, and the UI has a committed `package-lock.json` (enforcement is in SEC-01).
- A UI string resource file exists, and UI copy is loaded from it rather than hard-coded.

**Dependencies:** None identified

**TDD traceability:** §3.1 (components), §17 (English-only, strings externalized), §14 (lockfiles)

---

#### ENV-02 · Container images for `sim`, `controller`, and `ui` (multi-arch)

**Type:** Engineering task

**Description / value:** Build hardened images for both CPU architectures. Python images come from a digest-pinned `python:3.12-slim`; the UI is a multi-stage React build copied into `nginxinc/nginx-unprivileged`. Scenario YAML and feed templates are baked into the images so player mode needs no host mounts. Images must build natively on amd64 and arm64, because Colima on Apple Silicon runs an arm64 VM (D-01).

**Acceptance criteria**
- `sim` and `controller` run as non-root UID 10001. `ui` runs as non-root.
- All three containers start with `read_only: true` and write only to tmpfs, plus `/data` for `controller`.
- Scenario definitions are present at `/app/scenarios/*.yaml` in the `sim` image, and feed templates are present in the `controller` image, without bind mounts.
- No package installation happens at container start. Starting a container with networking disabled still succeeds.
- Base images are pinned by their **multi-arch index (manifest-list) digest**, not by a single-architecture digest.
- `make build` produces working images on both `linux/amd64` and `linux/arm64` hosts with no emulation (verified in QA-18 and REL-02).

**Dependencies:** ENV-01

**TDD traceability:** §4.3, §4.6, SR-3, SR-4, §14 (no runtime installs, non-root); decision D-01

---

#### ENV-03 · Compose topology, networks, and container security settings

**Type:** Engineering task

**Description / value:** Define the Compose project so that isolation is structural: a fixed project name, labels on every resource, an internal-only network for game logic, and a minimal edge network.

**Acceptance criteria**
- The Compose file sets `name: incident-escape-room`.
- Every service, network, and volume has the label `com.incident-escape-room.managed=true`.
- `escape_internal` has `internal: true`. `escape_edge` is a bridge network.
- `sim` and `controller` attach only to `escape_internal`. `ui` attaches to both networks.
- The only published port is `127.0.0.1:${ESCAPE_PORT:-8080}:8080` on `ui`.
- Every service has `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`. No service uses `network_mode`, `privileged`, `cap_add`, `devices`, `pid`, `ipc`, or a Docker socket mount.
- Service environment is limited to the `ESCAPE_*` and `TZ` allowlist.
- The named volume `escape_results` is mounted only in `controller`, at `/data`.
- Services use `build:` without a custom `image:` tag, so `--rmi local` in `make down` removes the project's images (§4.6, §4.7).

**Dependencies:** ENV-02

**TDD traceability:** §4.3, §5.1, SR-1, SR-2, SR-3, SR-4, SR-5, SR-8

**Assumptions, risks, or open questions:** The accepted residual risk (`ui` on a bridge network) is documented in the Compose file comments, per §5.1.

---

#### ENV-04 · Health checks, startup order, restart policies, and resource limits

**Type:** Engineering task

**Description / value:** Make the stack start in the right order and report readiness truthfully, within the resource budget.

**Acceptance criteria**
- **`sim` health check:** `GET /healthz` on port 9000; interval 5 s, timeout 2 s, retries 6. It is healthy only after the `sim` isolation self-check passes (ENV-07).
- **`controller`:** `depends_on: sim` with `condition: service_healthy`. Its health check is `GET /api/health/ready`, which is 200 only when isolation is `pass` and the link to `sim` is up.
- **`ui`:** `depends_on: controller` with `condition: service_healthy`. Its health check is `GET /` on port 8080.
- **Restart policies:** `on-failure:3` for `sim` and `controller`; `unless-stopped` for `ui`.
- **Resource limits** are set as: `sim` 0.5 CPU / 256 MB; `controller` 0.5 / 256 MB; `ui` 0.25 / 64 MB.
- When `docker compose up -d --wait` runs on a warm machine, all services report healthy in 60 s or less (verified in QA-17).

**Dependencies:** ENV-03, ENV-07, SIM-10, CTL-01

**TDD traceability:** §4.4, §4.5, NFR-3, NFR-4

---

#### ENV-05 · nginx configuration for the UI and API proxy

**Type:** Engineering task

**Description / value:** Serve the built app and proxy `/api` and the WebSocket to the single hard-coded upstream, so the edge container cannot be pointed anywhere else.

**Acceptance criteria**
- Static assets are served from the image. `/api/*` and `WS /api/rounds/{id}/stream` are proxied to `controller:8000`.
- The config contains exactly one upstream, has no `resolver` directive, and contains no variable-based proxy targets.
- Responses include `Content-Security-Policy: default-src 'self'; connect-src 'self'`.
- Given the controller is down, when the browser calls `/api`, then nginx returns 502, which the UI handles (UI-15).

**Dependencies:** ENV-02

**TDD traceability:** §3.2, §5.1, §14 (CSP), SR-2, SR-8

---

#### ENV-06 · Static isolation policy checker (host side)

**Type:** Engineering task

**Description / value:** A host-side script that validates the rendered `docker compose config` output before anything starts, so unsafe configuration can never launch.

**Acceptance criteria**
- The checker fails, naming the violated rule, when any of these is true:
  - A network used by `sim` or `controller` lacks `internal: true`.
  - Any service uses `network_mode`, `privileged`, `cap_add`, `devices`, `pid`, or `ipc`.
  - Any volume or bind mount points at `/var/run/docker.sock` or a host path.
  - The published ports are anything other than exactly one entry bound to `127.0.0.1`.
  - Any environment variable falls outside the allowlist.
  - Any resource lacks the project label.
- **Dev profile** (`--profile dev`, used only by `make dev`, D-06): the only relaxations are read-only bind mounts of `./ui`, `./controller`, and `./sim`, and `ESCAPE_DEV=1`. The single-published-port rule and every other rule are unchanged.
- `make up` always runs the player profile, so a dev override passed to it fails the check.
- Given the shipped Compose file, the checker passes in both profiles.
- The checker writes a report to `./.escape/preflight-report` and exits non-zero on failure.

**Dependencies:** ENV-03

**TDD traceability:** §5.5 (static checks 1–5), §4.2, SR-1–SR-5, SR-8, SR-9; decision D-06

---

#### ENV-07 · Runtime isolation self-check library (`sim` and `controller`)

**Type:** Engineering task

**Description / value:** A shared check, run inside the containers at startup and every 60 s, that proves isolation from routing and configuration state without contacting any external host.

**Acceptance criteria**
- The check fails if any of these is true:
  - `/proc/net/route` contains a default route.
  - `CapEff` in `/proc/self/status` is non-zero, or the UID is 0.
  - `/proc/self/mountinfo` shows a bind mount outside the allowlist (the `/data` volume, tmpfs, and dev source mounts only when `ESCAPE_DEV=1`).
  - A Docker socket exists at a known path.
  - Any environment variable matches `AWS_*`, `GOOGLE_*`, `AZURE_*`, `KUBECONFIG`, `VAULT_*`, `*_TOKEN`, `*_SECRET`, `*_API_KEY`, or `*_PASSWORD`, or a credential file exists at a known path (for example `~/.kube/config`, `~/.aws`).
  - A DNS lookup for `isolation-check.invalid` succeeds.
- The check performs no connection attempt to any non-internal address.
- The result (`pass` or `fail` plus the failed check IDs) is exposed to `/healthz` (`sim`) and to the controller's readiness and isolation status.
- Unit tests cover each check with pass and fail fixtures.

**Dependencies:** ENV-01

**TDD traceability:** §5.5 (runtime self-checks 1–6), SR-2–SR-5, SR-9

---

#### ENV-08 · Host-side post-start isolation verification

**Type:** Engineering task

**Description / value:** After `up`, confirm from the Docker host that the running state matches the policy.

**Acceptance criteria**
- `docker network inspect` confirms `Internal=true` for `escape_internal`.
- `docker inspect` confirms that `sim` and `controller` are attached only to `escape_internal` and that `ui` is attached to `escape_edge` and `escape_internal`.
- Any mismatch exits non-zero with a message naming the container and network.

**Dependencies:** ENV-03

**TDD traceability:** §5.5 (host-side runtime verification), SR-2, SR-9

---

#### ENV-09 · `make up` with preflight and fail-closed behavior

**Type:** Story

**Description / value:** As the player (and sole developer), I want one command that creates a verified, isolated environment, so that I can start playing safely without configuring anything.

**Acceptance criteria**
- **Preflight:** runs the host-runtime checks (ENV-13: local engine only; supported runtime; Docker Engine ≥ 28.0; Compose ≥ v2.20; buildx present). Checks that the port (`ESCAPE_PORT`, default 8080) is free on 127.0.0.1. Then runs ENV-06 in the player profile.
- Builds images if they are missing, runs `docker compose up -d --wait`, then runs ENV-08.
- Given every check passes, then the command prints the detected runtime and `Ready: http://127.0.0.1:<port>`, and exits 0.
- Given any check fails, then it prints the failed check and a fix hint, runs `make down`, and exits non-zero (fail closed).
- Given `KEEP_ON_FAIL=1` and a failure after start, then the stack stays up, the controller is `LOCKED`, and the command still exits non-zero.
- Given an unhealthy service during `--wait`, then the output names the service and shows its last 50 log lines (§13, partial startup).
- Running `make up` twice in a row is safe; the second run exits 0 (OR-3).
- Works unchanged on every tier-1 host (Linux Docker Engine; macOS with Colima).

**Dependencies:** ENV-04, ENV-06, ENV-08, ENV-10, ENV-13, CTL-20

**TDD traceability:** §4.7, §5.6, §13 (partial startup), OR-1, OR-3, SR-9, NFR-4, SC-5; decision D-01

---

#### ENV-10 · `make down` with project-scoped teardown and `FORCE=1`

**Type:** Story

**Description / value:** As a player, I want one command that removes everything the game created and nothing else, so that my machine is left clean and my other Docker work is untouched.

**Acceptance criteria**
- Runs `docker compose -p incident-escape-room down --volumes --remove-orphans --rmi local`, then deletes `./.escape/`.
- **Post-check:** `docker ps -a`, `docker network ls`, and `docker volume ls`, filtered by `label=com.incident-escape-room.managed=true`, return nothing; otherwise the command lists what remains, suggests `make down FORCE=1`, and exits non-zero.
- `FORCE=1` removes containers, then networks, then volumes, selected **only** by that label filter.
- The command never runs any `prune` command and never selects resources by name pattern. Shared base images remain.
- Running it twice, or on a machine where the game was never started, exits 0 (OR-3).

**Dependencies:** ENV-03

**TDD traceability:** §4.6, §4.7, §13 (teardown failure), OR-1, OR-3, SR-1, SC-5

---

#### ENV-11 · Supporting make targets and test profile

**Type:** Engineering task

**Description / value:** Provide `make status`, `make logs`, `make build`, and `make test`, plus a Compose test profile that enables test mode only for automated tests.

**Acceptance criteria**
- `make status` and `make logs` are scoped by project name and show only this project's containers and logs.
- `make build` builds all images without starting them, so a machine can be prepared in advance and then played offline (§4.1).
- `make test` runs the suites from §15 (wired in QA-18). It starts a stack with `ESCAPE_TEST_MODE=1` through a dedicated Compose profile, and tears that stack down afterward.
- `ESCAPE_TEST_MODE` is absent from the player profile used by `make up` (verified by QA-16).

**Dependencies:** ENV-03

**TDD traceability:** §4.7, §5.3, §15.1, OR-2

---

#### ENV-12 · Dev mode (`compose.dev.yaml`, `make dev`)

**Type:** Engineering task

**Description / value:** Hot-reload development that keeps the player-mode network shape. Following D-06, there is no second published port, and the controller never joins the edge network.

**Acceptance criteria**
- `make dev` applies `compose.dev.yaml` and sets `ESCAPE_DEV=1`.
  - `./controller` and `./sim` are mounted read-only and served with auto-reload.
  - `ui` runs the **Vite dev server** in place of nginx, with `./ui` mounted read-only and the Vite cache on tmpfs. It is published on the same single `127.0.0.1:${ESCAPE_PORT:-8080}` and proxies `/api` and the stream to `controller:8000` over `escape_internal`.
- Hot module reload works through the single published port.
- `controller` and `sim` stay attached only to `escape_internal`. ENV-06 passes in the dev profile, and ENV-07 allows only the three read-only source mounts.
- The UI shows a "DEV BUILD" ribbon in dev mode only.
- `make up` never applies the dev override.
- Running Vite directly on the host is not supported and is documented as such (SEC-07).
- **Colima:** dev mounts work when the repository is under a directory Colima shares with the VM (by default the home directory). Otherwise `make dev` prints a hint.

**Dependencies:** ENV-03, ENV-06, ENV-07, UI-01

**TDD traceability:** §4.2, §5.5 (runtime check 3), SR-2, SR-8; decision D-06

---

#### ENV-13 · Host runtime preflight and local-engine guard

**Type:** Engineering task

**Description / value:** Make sure the game only ever runs on the player's own machine, on a supported Docker runtime, with versions that keep loopback-only publishing safe.

**Acceptance criteria**
- **Engine location.** Resolves the active Docker endpoint (`DOCKER_HOST`, otherwise the current `docker context`). Given the endpoint is not a local Unix socket (or a Windows named pipe), for example `tcp://`, `ssh://`, or a remote context, then the command refuses before building anything, with "The game must run on this computer's own Docker engine."
- **Runtime detection.** Detects the two supported runtimes: Linux Docker Engine, and Colima (a context named `colima*`, or a socket under `~/.colima/`). It prints which one it found together with the engine version and CPU architecture. Docker Desktop and Docker inside WSL2 are treated as untested (D-01).
  - Podman (server component "Podman Engine") → refused, with a message that it is unsupported.
  - Any other runtime → "untested runtime" warning. It continues only if every isolation check later passes.
- **Versions.** Requires Docker Engine ≥ 28.0 (below that version, other machines on the local network may reach ports published to localhost), Compose plugin ≥ v2.20, and buildx. On Colima, a missing plugin prints the fix: install `docker-compose` and `docker-buildx` and register them with `cliPluginsExtraDirs` in `~/.docker/config.json`.
- **Resources.** Warns (does not block) if the engine reports fewer than 2 CPUs or less than 4 GiB of memory. On Colima it suggests `colima start --cpu 2 --memory 4`.
- Unit tests cover each endpoint type and runtime-detection case using recorded `docker version` and `docker context` output.

**Dependencies:** ENV-01

**TDD traceability:** §1 and safety guardrail ("runs on the player's own machine"), §4.1, SR-8, NFR-3; decision D-01

---

#### ENV-14 · `make export-results`

**Type:** Story

**Description / value:** As the developer, I want to copy my local results file on purpose, so that I can analyze my self-play sessions without the game ever sending data anywhere.

**Acceptance criteria**
- `make export-results` copies `/data/results.jsonl` from the `controller` container to `./escape-results-<UTC timestamp>.jsonl`, using `docker compose cp`. No bind mount is added.
- It prints the number of rounds and the field names exported, and confirms that the file has no player-identifying fields.
- Given the stack is not running or there are no results, then it exits non-zero with a clear message.
- Nothing is ever uploaded. The exported file is the user's: `make down` does not delete it, and the README says so.

**Dependencies:** CTL-17, ENV-11

**TDD traceability:** §4.6, §14 (local only, no personal data), §15.7; decision D-04

---

### E2: Simulation engine (`SIM`)

#### SIM-01 · Fixed-step engine, simulation clock, and pacing modes

**Type:** Engineering task

**Description / value:** The core loop that makes the game deterministic and testable faster than real time.

**Acceptance criteria**
- Simulation time advances only in fixed steps of Δt = 100 ms.
- Within each step, phases run in this order:
  1. Due actions take effect.
  2. Traffic arrivals.
  3. `api`.
  4. `ledger`.
  5. `worker`.
  6. Fault dynamics.
  7. Bad-event recording.
- **Pacing modes:**
  - **play:** 10 steps per wall-clock second.
  - **stepped:** steps only on `cmd.step`, as fast as possible. This mode is used for pre-roll in every build (D-05) and at any time in test mode.
- Pause stops stepping and freezes pending action delays. Resume continues with no change in results compared with an unpaused run (unit test).
- Two actions arriving in the same step are applied in arrival order.

**Dependencies:** ENV-01

**TDD traceability:** §6.2, §6.3, §8.1, NFR-5; decision D-05 (replaces the 30× pre-roll pacing)

---

#### SIM-02 · Seeded random-number streams

**Type:** Engineering task

**Description / value:** Seeded, independent random streams, so tests are reproducible and changes in one area don't shift another.

**Acceptance criteria**
- `sim` uses three named substreams: `traffic`, `latency`, and `fault`. Each is seeded with `int.from_bytes(sha256(f"{seed}:{name}").digest()[:8])`. The `feed` stream belongs to the controller (D-18).
- Python's built-in `hash()` is never used for seeding, because it is salted per process.
- Given the same seed and the same timed actions, two runs produce byte-identical tick streams (NFR-5).
- Adding draws to one substream leaves the other substreams' sequences unchanged (unit test).
- No other source of randomness is used in `sim`.

**Dependencies:** SIM-01

**TDD traceability:** §8.1, §8.6, NFR-5; decision D-18

---

#### SIM-03 · Traffic generator

**Type:** Engineering task

**Description / value:** Steady, believable customer load that looks alive without hiding signals.

**Acceptance criteria**
- **Flows:** `read` at 30 rps (`api` → `ledger`), `receipt_export` at 2 rps (`api` → `ledger`), and `order` at 10/s (`api` → `jobs` → `worker` → `ledger`). All rates are configurable.
- Each flow is a Poisson process with rate `r(t) = r0 × (1 + 0.10·sin(2πt/120 s)) × (1 + ε)`, where ε is per-second uniform noise within ±5%.
- A +20% burst lasting 10 s occurs every 3–5 minutes (seeded).
- Over a 30-minute baseline run, the measured mean rate per flow is within ±3% of `r0` (unit test tolerance).

**Dependencies:** SIM-01, SIM-02

**TDD traceability:** §8.2, §8.7, FR-3

---

#### SIM-04 · Simulated `api` service

**Type:** Engineering task

**Description / value:** Model the customer-facing service: its own processing time, synchronous calls to `ledger`, and asynchronous order intake.

**Acceptance criteria**
- About 15 ms of own processing per request.
- Synchronous requests call `ledger` through `api.ledger_client` (pool of 50), with a 1000 ms timeout and the configured retry policy:
  - `backoff`: at most 2 retries, exponential from 200 ms with full jitter.
  - `aggressive`: 4 immediate retries.
- End-to-end latency is reported per request. Timeouts are recorded at the timeout value.
- Orders are answered 202 immediately after being enqueued to `jobs`.
- While `api` is down (`Restarting`), every customer request fails immediately with reason `unavailable`.
- Unit tests cover the timeout and retry semantics for both policies.

**Dependencies:** SIM-01, SIM-06

**TDD traceability:** §7.1, §8.3, §9.1 (error reasons)

---

#### SIM-05 · Simulated `ledger` service

**Type:** Engineering task

**Description / value:** Model the data service: a bounded request queue, a database connection pool, hold times, and wasted work for callers that have already given up. The retry storm depends on that last behavior.

**Acceptance criteria**
- Arrivals join `ledger.requests` (FIFO, cap 300). Arrivals beyond the cap are rejected immediately with `queue_full`.
- The request at the head takes a connection from `ledger.db` (10 connections; 13 since D-24). If it has not got one within 2000 ms of arriving (queue time counts; D-20), it fails with `pool_timeout`.
- Hold times are lognormal with σ = 0.4 and these means: read 80 ms, write 120 ms, receipt export 300 ms. Measured baseline capacity is about 100 rps and utilization about 42% (±5 percentage points); with D-24's 13 connections, about 130 rps and 32%.
- A request whose caller has already timed out is still processed and counts toward `ledger` throughput, but not toward any customer success.
- Every request carries `caller` and `attempt` so throughput can be broken down by caller × attempt.
- Unit tests cover pool lease and release, queue overflow, and pool-wait timeout.

**Dependencies:** SIM-01

**TDD traceability:** §7.1, §8.3, §9.1; decision D-20

---

#### SIM-06 · Simulated `jobs` queue and `jobs.dlq`

**Type:** Engineering task

**Description / value:** The order queue between `api` and `worker`, with redelivery rules that make the poison message persist.

**Acceptance criteria**
- FIFO ordering.
- A job whose processing failed (a handled failure) is requeued to the **tail** after 2 s, with its attempt count incremented.
- A job that was in flight when the consumer crashed is redelivered to the **head**.
- No automatic max-delivery or dead-lettering occurs. Messages reach `jobs.dlq` only through a player action.
- The queue exposes depth (waiting plus in flight), the head message's delivery attempts, and the `jobs.dlq` count.
- Unit tests cover tail requeue versus head redelivery.

**Dependencies:** SIM-01

**TDD traceability:** §7.1, §8.3, §9.1 (queue-depth breakdowns)

---

#### SIM-07 · Simulated `worker` service

**Type:** Engineering task

**Description / value:** The consumer that writes orders to `ledger`, including the supervised crash loop.

**Acceptance criteria**
- Concurrency of 10 slots (`worker.ledger_client` of 10). Each slot takes the head message and processes it for about 100 ms, then writes to `ledger` with a 2000 ms timeout and `backoff` retries. Maximum rate is about 40 jobs/s.
- Success acknowledges the message. A handled failure requeues it to the tail (SIM-06).
- A crash leaves the in-flight message at the head and puts the consumer into a 5 s restart backoff. The status is `Crash-looping` while repeated crashes continue.
- Reports `attempts` and `completed` separately, plus errors by reason (`crash`, `downstream_timeout`).

**Dependencies:** SIM-05, SIM-06

**TDD traceability:** §7.1, §8.3, §9.1, §9.2

---

#### SIM-08 · Bad customer event accounting

**Type:** Engineering task

**Description / value:** The single source of truth for customer impact, used by scoring, counters, and the feed.

**Acceptance criteria**
- **Categories and rules recorded per simulated second:**
  - `read_failed`: a synchronous error.
  - `read_slow`: success taking more than 2000 ms.
  - `receipt_unavailable`: export failed or disabled.
  - `order_rejected`: `api` down.
  - `order_delayed`: not completed within 30 s of placement; counted once, at breach.
  - `order_lost`: removed by purge, `restart_all`, or quarantine of a healthy message.
- Weights are attached as 1, except `order_lost` = 3.
- Counts are included in every `evt.tick`.
- Unit tests cover each category, including counting `order_delayed` exactly once per order.

**Dependencies:** SIM-04, SIM-05, SIM-06, SIM-07

**TDD traceability:** §8.4, §11.1 (B), FR-6

---

#### SIM-09 · Metric aggregation

**Type:** Engineering task

**Description / value:** Turn request completions and resource samples into the five metric families at a 1 s cadence.

**Acceptance criteria**
- Requests are recorded at completion. Each simulated second, the trailing 10 s window produces `latency_p50_ms`, `latency_p95_ms`, `error_rate_pct` (by reason), and `throughput_rps` with these breakdowns: `api` by flow; `ledger` by caller × attempt; `worker` attempts vs completed.
- `queue_depth` (for `jobs` and `ledger.requests`) and `pool_in_use` are sampled at the end of each second. Pool use is the mean over the second (D-21), for `api.ledger_client` (50), `worker.ledger_client` (10), and `ledger.db` (10).
- Service status (`Up`, `Restarting`, `Crash-looping`) is included per service.
- Unit tests check p95 against a known latency distribution, and error-rate denominators.

**Dependencies:** SIM-04, SIM-05, SIM-06, SIM-07

**TDD traceability:** §8.5, §9.1, §9.2, FR-4

---

#### SIM-10 · `sim` link server and `/healthz`

**Type:** Engineering task

**Description / value:** The internal WebSocket server that the controller uses to drive the simulation. It is the only network endpoint in `sim`.

**Acceptance criteria**
- Serves `ws://sim:9000/link` and `GET /healthz` on port 9000. Opens no outbound connections.
- **Commands accepted:**
  - `cmd.start_round {scenario_id, seed}` (enters the stepped pre-roll phase)
  - `cmd.step {n}`, accepted in player mode **only while in pre-roll**, and at any time in test mode
  - `cmd.resume`, `cmd.pause`, `cmd.action {action: {action_id, type, target, params}}` (nested, because the envelope's `type` names the command), `cmd.stop`
  - `cmd.test_inject {kind, duration_s}`, test mode only (D-10)
- **Events emitted:** `evt.tick` (one per simulated second), `evt.action_applied`, `evt.heartbeat` (1 Hz wall clock; carries `pack_version` and the pack's controller tuning, D-25), `evt.error`. `evt.prealert_ready` is removed (D-05).
- `evt.tick` contains the metrics, bad-event counts, statuses, and config snapshot, plus hidden fields (`fault.active`, `fault.neutralized`, scenario id) for the controller only.
- `/healthz` returns 200 only after the isolation self-check passes (ENV-07).
- Malformed or disallowed commands (for example `cmd.step` during play in player mode) are answered with `evt.error` and have no effect on the simulation.

**Dependencies:** SIM-01, SIM-09, ENV-07

**TDD traceability:** §3.2, §3.3, §4.5, §12.2 (internal messages), SR-6; decisions D-05, D-10

---

### E3: Scenarios, world data, and action effects (`SCN`)

#### SCN-01 · Scenario definition schema, loader, and scenario-pack version

**Type:** Engineering task

**Description / value:** A validated YAML format for scenarios. Tuning then changes data, not code, and every result can be traced to the pack version.

**Acceptance criteria**
- **Schema fields:** `id`, `title`, `parameters`, `fault_script`, `signature`, `effect_matrix`, `debrief_copy`. Pack-level fields: a `version` and the baseline-world defaults.
- On `sim` startup, files in `/app/scenarios/*.yaml` are validated. An invalid file stops startup with an error naming the file and field, so `/healthz` stays unhealthy.
- Exactly three scenario ids load: `pool_leak`, `poison_message`, and `retry_storm`.
- Every *(default)* tuning value from §8.7 can be overridden in the pack without code changes.
- The pack version is exposed to the controller for results and the UI footer (REL-01).

**Dependencies:** SIM-01

**TDD traceability:** §12.1 (`ScenarioDefinition`), §8.7, §4.3 (baked-in scenarios), OR-4

---

#### SCN-02 · Baseline world configuration and read-only Config data

**Type:** Engineering task

**Description / value:** One world shared by all scenarios, so that only the hidden fault differs. Its current settings are published as evidence.

**Acceptance criteria**
- The world uses the §7.1 values: the traffic rates; the `ledger` pool, queue cap, and pool-wait timeout; the `api` timeout and client pool; the `worker` concurrency and 5 s restart backoff; `jobs` semantics; retry policy `backoff` for both callers; flags `receipt_export` and `checkout_banner` (on).
- Each scenario may override only what §7.1 allows: `retry_storm` sets the `api` policy to `aggressive`; `pool_leak` sets `receipt_export` to off before onset.
- Every tick includes a read-only config snapshot: feature flags, retry policy per caller, timeouts, pool sizes, and the queue cap. It reflects changes made by actions within one tick of them taking effect.

**Dependencies:** SCN-01, SIM-04, SIM-05, SIM-06, SIM-07

**TDD traceability:** §7.1, §9.4 (Config panel)

---

#### SCN-03 · Fault injector framework

**Type:** Engineering task

**Description / value:** Runs a scenario's fault script against simulated objects only, and reports whether the root cause is neutralized.

**Acceptance criteria**
- Fault scripts can change only simulated objects: `ledger.db` leases, the head message on `jobs`, `api` retry settings, and `ledger` hold-time multipliers. The framework exposes no access to the operating system, files, the network, or subprocesses (enforced by SEC-02).
- Onset is scheduled from the scenario parameters with seed-driven jitter of ±20%.
- `fault.active` and `fault.neutralized` are evaluated every tick using the scenario's "holds" rule (§7.3–§7.5).
- The seed changes only noise, onset time, feed wording, and names. It never changes the mechanism (verified by QA-02).

**Dependencies:** SCN-01, SIM-01, SIM-02

**TDD traceability:** §5.2, §7 (intro), §8.6, SR-6

---

#### SCN-04 · Scenario `pool_leak`

**Type:** Engineering task

**Description / value:** A connection leak in `ledger`'s receipt-export path, which creeps up slowly before the page fires.

**Acceptance criteria**
- **Mechanism:** with `receipt_export` on, 1.25% *(default)* of exports never return their `ledger.db` connection, which is about one leak every 40 s. Leaked connections are never reclaimed on their own. Onset is when the flag is enabled, at about T−4:45.
- **Progression:** pool in-use climbs in steps from about 4 to 10 and doesn't fall when traffic dips. `ledger` p95 rises once about 6 connections have leaked. The pool is exhausted at about T−0:30, after which requests wait 2 s and fail with `pool_timeout`. The page is `api_latency_high`.
- **Holds rule:** neutralized only when `receipt_export` is off *and* no leaked leases remain.
- **Effect matrix** (§10.2) is encoded in the scenario YAML. Turning the flag off alone does not recover the pool. Recycling alone recovers for about 2.5–4 min and then degrades again.
- **Signature cells** (§7.2) are encoded for QA-02.
- **Debrief copy** is provided: the explanation, 2–3 clues, and the takeaway (SEC-06).

**Dependencies:** SCN-02, SCN-03, SIM-05

**TDD traceability:** §7.2, §7.3, §10.2, §8.7

---

#### SCN-05 · Scenario `poison_message`

**Type:** Engineering task

**Description / value:** One malformed order crash-loops the `worker` consumer.

**Acceptance criteria**
- **Mechanism:** at onset (about T−1:10), a `partner-import` batch adds 200 orders, one of which lacks `currency`. Processing it crashes the consumer before it acknowledges. The message is redelivered to the head, and the consumer crashes again after each 5 s backoff.
- **Symptoms:** `worker` is `Crash-looping`; its error rate is about 100% of attempts with reason `crash`; completed jobs are 0. `jobs` depth rises by about 10/s, and head delivery attempts climb every 5 s. `api` and `ledger` stay healthy. The page is `orders_backlog_high`.
- **Holds rule:** neutralized once the malformed message is no longer in `jobs` (through quarantine, purge, or `restart_all`).
- The effect matrix, signature cells, and debrief copy are encoded as in SCN-04.

**Dependencies:** SCN-02, SCN-03, SIM-06, SIM-07

**TDD traceability:** §7.2, §7.4, §10.2

---

#### SCN-06 · Scenario `retry_storm`

**Type:** Engineering task

**Description / value:** A short slowdown in `ledger` becomes a self-sustaining overload because of aggressive client retries.

**Acceptance criteria**
- **Mechanism:** at onset (about T−0:45), a 20 s index-maintenance window multiplies `ledger` hold times by 8 *(default)*. With the `api` policy set to `aggressive`, offered load reaches about 170–210 rps against about 100 rps of capacity. The overload continues after the window ends, with `ledger.requests` near its cap of 300 and goodput near 0.
- **Symptoms:** `ledger` throughput is about 100 rps (more than twice the customer rate) with retry share above 60%; errors are `timeout`, with `pool_timeout` and `queue_full` (D-20); the pool is pinned at 10/10. The page is `api_error_rate_high`.
- **Behavior under actions:** `set_retry_policy(api, backoff)` recovers within about 15 s of taking effect. `restart_service(ledger)` is followed by the storm resuming within seconds. `restart_service(api)` recovers but does not hold.
- **Holds rule:** neutralized only when the `api` policy is `backoff`.
- The effect matrix, signature cells, and debrief copy are encoded as in SCN-04.

**Dependencies:** SCN-02, SCN-03, SIM-04, SIM-05

**TDD traceability:** §7.2, §7.5, §10.2, §8.7

**Assumptions, risks, or open questions:** Risk: storm stability is sensitive to the capacity margin (§8.7). Tuning happens in REL-05 and REL-06.

---

#### SCN-07 · Recent-changes data with decoys

**Type:** Engineering task

**Description / value:** Timestamped change entries that are realistic evidence and never name a cause.

**Acceptance criteria**
- Each round produces 3–4 entries: the scenario's relevant entry plus decoys drawn from the shared pool. The relevant entries are:
  - `pool_leak`: `receipt_export` enabled about 30 s before the pool began climbing.
  - `poison_message`: `partner-import` batch started at onset.
  - `retry_storm`: `ledger` index maintenance (the 20 s window).
- The decoy pool is: `checkout_banner` enabled, a dashboard theme update, `api v2.3 deployed (yesterday)`, a `ledger` backup completed.
- Entry wording is short and factual and passes the banned-word lint (SEC-06).
- Entries are part of the player-visible stream from the start of the round.

**Dependencies:** SCN-01, SCN-04, SCN-05, SCN-06

**TDD traceability:** §9.4, §7.2 (recent-changes row)

---

#### SCN-08 · Restart actions: `restart_service` and `restart_all`

**Type:** Engineering task

**Description / value:** Simulated restarts as state transitions, never real container operations.

**Acceptance criteria**
- **`restart_service(target ∈ {api, worker, ledger})`:** the target is `Restarting` for 8 s, then its in-memory state is reset (in-flight work, retry state, `ledger` pool leases, `worker` consumer).
- **`restart_all`:** all three services are down for 25 s, and `jobs` is emptied. Every emptied message is recorded as `order_lost`.
- **During downtime:** `api` down means customer requests fail; `ledger` down means reads stall; `worker` down means orders wait.
- `evt.action_applied` is emitted when the effect completes.
- No Docker or process API is used (SEC-02).

**Dependencies:** SIM-04, SIM-05, SIM-07, SIM-08, SIM-10

**TDD traceability:** §10.1, §5.2, §3.1 (design choice), SR-6

---

#### SCN-09 · Configuration actions: `recycle_pool`, `set_feature_flag`, `set_retry_policy`

**Type:** Engineering task

**Description / value:** Targeted interventions that change pool and config state in the simulation.

**Acceptance criteria**
- **`recycle_pool(ledger)`:** 5 s delay. Closes and reopens every `ledger.db` connection, reclaiming leaked ones. In-flight `ledger` queries fail during the recycle.
- **`set_feature_flag(flag ∈ {receipt_export, checkout_banner}, enabled)`:** 3 s delay. With `receipt_export` off, exports return "temporarily unavailable" (`receipt_unavailable`). `checkout_banner` has no system effect.
- **`set_retry_policy(caller ∈ {api, worker}, mode ∈ {backoff, aggressive})`:** 5 s delay. The new policy applies to calls started after it takes effect.
- Each action emits `evt.action_applied`, and the config snapshot (SCN-02) reflects the change.

**Dependencies:** SIM-04, SIM-05, SIM-08, SCN-02, SIM-10

**TDD traceability:** §10.1, §7.3, §7.5

---

#### SCN-10 · Queue actions: `quarantine_head_message` and `purge_queue`

**Type:** Engineering task

**Description / value:** Targeted and destructive queue interventions.

**Acceptance criteria**
- **`quarantine_head_message(jobs)`:** 2 s delay. Moves the head message to `jobs.dlq`. If that message was a healthy order, it counts as `order_lost`.
- **`purge_queue(jobs)`:** 3 s delay. Deletes every message in `jobs`; each deleted message counts as `order_lost`.
- After quarantine of the poison message, the consumer resumes and drains at about 30/s net.

**Dependencies:** SIM-06, SIM-07, SIM-08, SIM-10

**TDD traceability:** §10.1, §7.4

---

### E4: Game controller (`CTL`)

#### CTL-01 · Controller service skeleton, health endpoints, and error envelope

**Type:** Engineering task

**Description / value:** The FastAPI service frame, with readiness that reflects safety and consistent errors.

**Acceptance criteria**
- `GET /api/health/live` returns 200 while the process is running.
- `GET /api/health/ready` returns 200 only when isolation is `pass` (its own check and `sim`'s) and the link to `sim` is up. Otherwise it returns 503 with a body naming the failing condition.
- Every error uses the envelope `{"error":{"code","message","details"}}` with the codes in §12.4 plus `session_complete` (409, D-13): `invalid_request` (400/422), `not_found` (404), `invalid_state`, `action_in_progress`, `no_change`, `insufficient_budget`, `target_unavailable`, `not_stable`, `session_complete` (409), `locked` (423), `sim_unavailable` (503), and `internal_error` (500) for a controller bug.
- The controller's runtime isolation self-check (ENV-07) runs at startup and every 60 s.

**Dependencies:** ENV-01, ENV-07

**TDD traceability:** §4.5, §12.2, §12.4, §5.5; decision D-13

---

#### CTL-02 · Controller ↔ `sim` link client

**Type:** Engineering task

**Description / value:** The controller's only outbound connection, fixed to the internal simulation.

**Acceptance criteria**
- Connects only to the constant address `ws://sim:9000/link`. The address cannot be overridden by environment variables in player builds.
- Before connecting, the client verifies that `sim` resolves to an address inside the `escape_internal` subnet. If not, isolation is set to `fail`.
- Sends the commands and consumes the events defined in SIM-10. Correlates action commands with `evt.action_applied`.
- A heartbeat missing for more than 3 s marks the link down and raises the `sim_unavailable` condition (CTL-20).
- Reconnects with backoff after `sim` restarts.

**Dependencies:** CTL-01, SIM-10

**TDD traceability:** §3.2, §5.3, §13 (`sim` crash), SR-2, SR-7

---

#### CTL-03 · Session management

**Type:** Story

**Description / value:** As a player, I want a session of three rounds, one per scenario, in random order, so that each incident stays hidden and I practice all three.

**Acceptance criteria**
- `POST /api/sessions {mode: "standard" | "practice"}` (default `standard`, D-02) creates a session with `round_order` as a random permutation of the three scenario ids, each exactly once. Any existing session is marked `abandoned`. The mode is fixed for the session.
- The session has `status ∈ {in_progress, complete, abandoned}`.
- `GET /api/sessions/current` returns the summary, mode, status, and current round.
- Given all three rounds have reached `DEBRIEF`, when the client calls `POST /api/sessions/current/rounds`, then the response is `409 session_complete` (D-13).
- `POST /api/sessions/current/complete` marks the session `complete` and records the final round's `debrief_closed_at`. It is idempotent, and the UI calls it when the session summary opens.
- The session is mirrored to `/data/session.json` on every change. Given a controller restart, when it starts again, then completed round summaries are restored.
- **Reset session** clears the session and creates a new order. `results.jsonl` is kept.

**Dependencies:** CTL-01, CTL-17

**TDD traceability:** §12.1 (Session), §12.2, §4.6, FR-1, FR-11; decisions D-02, D-12, D-13

---

#### CTL-04 · Round state machine and lifecycle endpoints

**Type:** Engineering task

**Description / value:** Implement the round lifecycle and the global `LOCKED` state.

**Acceptance criteria**
- **States:** `PREPARING`, `BRIEFING`, `ACTIVE`, `PAUSED`, `RESOLVED`, `TIMED_OUT`, `ENDED` (practice mode only, D-02), `ABORTED`, `DEBRIEF`, plus the global `LOCKED`.
- **Allowed transitions:** those in the §6.1 diagram, plus `ACTIVE`/`PAUSED` → `ENDED` → `DEBRIEF` in practice mode. `BRIEFING` → `ABORTED` is for game failures only (`sim` lost, isolation failed); the player can't restart from `BRIEFING`. In practice mode, `ACTIVE` → `TIMED_OUT` never occurs. Any other transition request returns `409 invalid_state`.
- **Endpoints:**
  - `POST /api/sessions/current/rounds` (prepare the next round)
  - `POST /api/rounds/{id}/start` (`BRIEFING` → `ACTIVE`; sends `cmd.resume`)
  - `POST /api/rounds/{id}/pause` and `/resume` (send `cmd.pause` and `cmd.resume`)
  - `POST /api/rounds/{id}/restart` (aborts the round and creates a new attempt of the same scenario with a new seed, fresh budget, and fresh timer)
- `GET /api/rounds/{id}` returns the state, timer, budget, health checks, alerts, and statuses.
- An aborted attempt has an `abort_reason` (`sim_unavailable`, `controller_restart`, `isolation_check_failed`, `preroll_no_alert`, `player_restart`) and is never scored.
- While `LOCKED`, every request to prepare or start a round returns `423 locked`.
- Unit tests cover every legal and illegal transition.

**Dependencies:** CTL-02, CTL-03, CTL-07

**TDD traceability:** §6.1, §6.5, §12.2, FR-2, FR-11, §5.6; decisions D-02, D-05

---

#### CTL-05 · Round preparation and pre-roll handshake (controller-stepped)

**Type:** Engineering task

**Description / value:** Pre-roll the world so the player arrives at the alert with real history on screen. Following D-05, the controller drives the pre-roll step by step, so there is one alert implementation and the page instant is exact.

**Acceptance criteria**
- On prepare, the controller sends `cmd.start_round {scenario_id, seed}` (the seed is random in play mode), then `cmd.step {n: 10}` for each simulated second, as fast as the link allows.
- After each `evt.tick`, the controller runs the normal health, alert, impact, and feed pipeline (CTL-07 to CTL-11). The baseline is at least 600 s of simulation time before onset.
- At the first second where a page rule fires (CTL-09), the controller stops stepping. T0 is that second, the simulation stays paused, and the round enters `BRIEFING`. The console opens with the full pre-roll history.
- **Bound:** if no page has fired by 900 s of simulation time after onset, the round goes to `ABORTED (preroll_no_alert)`. The controller retries once with a new seed; if that also fails, it shows the game-problem notice (UI-15).
- Neither the timer nor scored impact (B) advances during pre-roll.
- A `sim` error or isolation failure during pre-roll sends the round to `ABORTED`.
- Typical pre-roll completes in a few seconds of wall-clock time; it is measured in QA-17.

**Dependencies:** CTL-02, CTL-04, CTL-08, CTL-09, CTL-10, CTL-11, SIM-01, SIM-10

**TDD traceability:** §3.3, §3.5, §6.1, §6.2, §8.1, §9.6; decision D-05

---

#### CTL-06 · Round timer, stability tracking, and outcomes

**Type:** Engineering task

**Description / value:** Time the incident in simulation time, track continuous health, and assign outcomes.

**Acceptance criteria**
- The round timer runs for 720 s *(default)* of simulation time, starting at T0. It freezes while `PAUSED`.
- `healthy_since` is set when every health check (CTL-08) passes, and reset to empty whenever any check fails.
- At timeout:
  - stable for ≥ W (60 s) → outcome `recovered_undeclared`;
  - otherwise → `not_recovered`.
  
  Either way the round goes to `TIMED_OUT`, then `DEBRIEF`.
- After 180 s of continuous stability without a declaration, a single nudge event is emitted.
- TTR is recorded as `healthy_since − T0` for the healthy period that led to an accepted declaration or that was stable at timeout.

**Dependencies:** CTL-04, CTL-08

**TDD traceability:** §6.2, §6.4, §6.5, §11.1, §11.3, FR-2, FR-9

---

#### CTL-07 · Round event log and ordering

**Type:** Engineering task

**Description / value:** A strictly ordered, append-only record of everything that happens in a round. It supports the debrief, results, and the future timeline.

**Acceptance criteria**
- Every round event (state changes, alerts, actions, declarations, nudges, system notices) gets a strictly increasing `seq` and a `sim_time_ms`.
- At each 1 s boundary, the controller processes in this order:
  1. Health checks.
  2. Alerts.
  3. Impact accounting.
  4. Feed generation.
  5. State update.
  6. Broadcast.
- The `RoundEvent` log is kept in memory and stored compressed with the round result (CTL-17).

**Dependencies:** CTL-02

**TDD traceability:** §6.3, §12.1 (`RoundEvent`), §16.3 (extension point)

---

#### CTL-08 · Health-check evaluation

**Type:** Engineering task

**Description / value:** Evaluate the ten shared health checks every second. They drive stability, the health panel, and declaration.

**Acceptance criteria**
- **Checks** *(default thresholds)*:

  | Check | Pass condition |
  |---|---|
  | `api` errors | < 1% |
  | `api` p95 | < 500 ms |
  | `worker` errors | < 2% of attempts |
  | `worker` status | Up |
  | `ledger` errors | < 1% |
  | `ledger` p95 | < 300 ms |
  | `ledger.db` pool | < 80% in use |
  | `ledger.requests` | < 20 queued |
  | `ledger` retry share | < 25% of throughput |
  | `jobs` backlog | depth < 100 and not increasing (see below) |

- **"Not increasing" (D-07):** the least-squares slope of `jobs` depth over the trailing 30 one-second samples is ≤ +0.5 messages/s *(default)*. With fewer than 30 samples since T0, the available samples are used, with a minimum of 10.
- The same set applies in every scenario. Each check exposes `{id, passing, value, threshold}`.
- Unit tests cover the boundary values for each check, including the slope rule with synthetic noisy, draining, and growing series.

**Dependencies:** CTL-02

**TDD traceability:** §9.3, §7.3–§7.5 (recovery verification), FR-9; decision D-07

---

#### CTL-09 · Alert rules and page selection

**Type:** Engineering task

**Description / value:** Symptom-based alerting that starts the round and teaches that "cleared" is not "resolved."

**Acceptance criteria**
- **Rules:**
  - `api_error_rate_high`: `api` error rate ≥ 5% for 30 s.
  - `api_latency_high`: `api` p95 ≥ 1000 ms for 30 s.
- Rules that fire in the same second page in the order listed above (D-22).
  - `orders_backlog_high`: `jobs` depth ≥ 500 for 30 s.
- The first rule to fire after onset is marked `is_page: true` and defines T0. Rules that fire later are secondary and don't change T0.
- Each alert reports `FIRING` or `CLEARED` with `fired_at_ms` and `cleared_at_ms`.
- Alert text names the symptom only.
- In each scenario, one of the scenario's expected rules pages first (asserted in QA-02; `pool_leak` and `retry_storm` accept either `api` rule, D-22).

**Dependencies:** CTL-02

**TDD traceability:** §9.6, §7.2 (alert row), FR-5

---

#### CTL-10 · Impact accounting and counters

**Type:** Engineering task

**Description / value:** Compute scored impact B and the counters players see.

**Acceptance criteria**
- B = the weighted sum of bad events from T0 to round end (`order_lost` × 3, everything else × 1). Pre-alert impact is computed and shown but excluded from B.
- **"Customers affected, last 5 min"** = bad events in the trailing 5 minutes, capped at 2,500 *(default)*.
- **"Open support tickets":** opened at 1 per 40 bad events; closed at 1 per 10 s once every category has been at zero for 30 s.
- The counters are exact functions of the bad-event series (verified in QA-06).

**Dependencies:** CTL-02, SIM-08

**TDD traceability:** §9.8 (counters), §11.1 (B), §8.4

---

#### CTL-11 · Customer-impact feed generator

**Type:** Story

**Description / value:** As a player, I want a stream of fictional customer complaints that reflects what is actually failing, so that I feel the impact without being misled or spoiled.

**Acceptance criteria**
- **Seeded RNG (D-18):** the feed uses its own generator, seeded with `int.from_bytes(sha256(f"{seed}:feed").digest()[:8])`. The same seed and the same event series produce identical feed items.
- **Generation:** every 5 s of simulation time, take the trailing 10 s window and select the category with the highest count, as long as the count is at least 5. Emit with probability `min(1, count/50)`. At most 1 item per 5 s.
- Escalating templates are used when a category has been bad for more than 3 min.
- **Pre-roll (D-09):** generation runs throughout pre-roll in simulation time. Items before T0 are flagged `pre_alert: true` and delivered as history, not as live events. Neutral chatter (at most 1 per 60 s) appears only in the pre-onset baseline.
- Every item carries `evidence {category, count, window_start_ms, window_end_ms}` and fictional `customer` data (SEC-05).
- **Safeguards:**
  - No item is emitted if its evidence count is below the minimum.
  - Items are dropped if their category has had zero bad events for 10 s or more at emit time.
  - The category-to-template mapping is fixed.
  - Recovery messages appear only when every category has been at zero for 30 s *and* the health checks pass.

**Dependencies:** CTL-10, CTL-08, SEC-05, SEC-06

**TDD traceability:** §9.8, §8.1, FR-6, NFR-5, §14 (feed content); decisions D-09, D-18

---

#### CTL-12 · Action catalog endpoint and validation, budget, and idempotency

**Type:** Engineering task

**Description / value:** Accept only well-formed, permitted, affordable actions on enumerated sandbox targets.

**Acceptance criteria**
- `GET /api/actions/catalog` returns the seven actions with their costs (3 / 10 / 1 / 1 / 1 / 1 / 4), delays, descriptions, side effects, and valid targets and params (§10.1).
- Requests are validated against a JSON schema with enumerated `type`, `target`, and `params`. Unknown fields, or any hostname, URL, IP address, port, path, or command string, return `422 invalid_request`.
- **Preconditions**, each rejected with no charge and the stated code:
  - The round is not `ACTIVE` → `invalid_state`.
  - Budget < cost → `insufficient_budget`.
  - Target `Restarting`, `ledger` down for `recycle_pool`, or `jobs` empty for queue actions → `target_unavailable`.
  - An action is pending on the same target, or any pending `restart_all` → `action_in_progress`.
  - `set_*` to the value already set → `no_change`.
- The budget starts at 12 *(default)* and is charged on acceptance. A repeat after completion is allowed and charged again.
- Idempotency by `client_request_id`: a duplicate submission returns the original response and is not charged twice.
- Accepted responses include `sandbox_target` (for example `sim/api`).
- An action request is acknowledged in under 200 ms (NFR-2, verified in QA-17).

**Dependencies:** CTL-04, SCN-01

**TDD traceability:** §10.1, §10.3, §5.3, §6.5, §12.2–§12.4, SR-7, FR-7, NFR-2

---

#### CTL-13 · Action dispatch and lifecycle

**Type:** Engineering task

**Description / value:** Carry accepted actions through to the simulation and report their progress, keeping effect classification hidden until the debrief.

**Acceptance criteria**
- Accepted actions are sent as `cmd.action`. Status moves `pending` → `completed` on `evt.action_applied`. Updates are streamed as `action_update`.
- `submitted_at_ms` and `effective_at_ms` are recorded.
- Given an accepted action that `sim` cannot apply (for example because the link dropped), then its cost is refunded, its status is `refunded`, and the round is aborted (CTL-20).
- `effect_class` is looked up from the scenario's effect matrix and stored, but is not sent to the UI before `DEBRIEF` (QA-07).
- Rejected attempts are logged in the action log with `reject_reason`.

**Dependencies:** CTL-12, CTL-02, CTL-07, SCN-08, SCN-09, SCN-10

**TDD traceability:** §10.3, §12.1 (`PlayerAction`), §6.5, §13

---

#### CTL-14 · Declare-resolved endpoint

**Type:** Story

**Description / value:** As a player, I want to declare the incident resolved and be told clearly if it isn't stable yet, so that I learn to verify recovery before calling it done.

**Acceptance criteria**
- Given every check has been passing for ≥ W (60 s), when the player calls `POST /api/rounds/{id}/declare-resolved`, then the round becomes `RESOLVED` with outcome `recovered`, `cmd.stop` is sent, and the round moves to `DEBRIEF`.
- Given checks have been green for less than W, then the response is `409 not_stable` with `details {green_for_s, required_s, penalty: 50, failing_checks[]}` and a plain message such as "Checks have been green for 22 s of the required 60 s." The round continues.
- The premature penalty is counted at most 3 times.
- The health panel never exposes a countdown (§6.4).

**Dependencies:** CTL-06, CTL-08

**TDD traceability:** §6.4, §11.2 (P_premature), §12.3, FR-9

---

#### CTL-15 · Scoring engine

**Type:** Engineering task

**Description / value:** A transparent score that rewards judgment over speed alone.

**Acceptance criteria**
- `S_speed = 300 × clamp(1 − (TTR − 90)/(720 − 90), 0, 1)` if recovered, else 0.
- `S_impact = 300 × clamp(1 − B/15000, 0, 1)`.
- `S_hold` = +100 if the outcome is `recovered` (declared), plus +100 if neutralized. Only when recovered.
- `S_budget = 200 × remaining/12`. Only when recovered.
- `P_breadth` = 150 per `restart_all` and 25 per `restart_service`. `P_noeffect` = 30 per action marked "no effect" or "unhelpful". `P_premature` = 50 per rejected declaration, at most 3.
- The total is clamped to [0, 1000] and computed before rounding.
- **Outcome rules:**
  - `recovered`: all components.
  - `recovered_undeclared`: everything except the declaration +100.
  - `not_recovered`: S_impact minus penalties.
  - `aborted`: not scored.
- Every weight and threshold is configurable (§8.7).
- Unit tests reproduce the §11.4 worked examples from fixed inputs and cover the clamp boundaries.

**Dependencies:** CTL-06, CTL-10, CTL-13, CTL-14

**TDD traceability:** §11.1–§11.4, §10.4, FR-8, SC-3

---

#### CTL-16 · Debrief generation

**Type:** Engineering task

**Description / value:** Build the end-of-round explanation that turns play into learning.

**Acceptance criteria**
- `GET /api/rounds/{id}/debrief` is available only in `DEBRIEF`; otherwise it returns `409 invalid_state`.
- **Payload:** `outcome`; the score breakdown (with speed reported as "not scored" in practice mode, D-02); `scenario_id` and the root-cause explanation; timing (fault began, `first_signal_offset_s`, TTD = T0 − T_onset, TTR, declared at); 2–3 clues with chart-snapshot references; every action with time, cost, `effect_class`, and penalty, plus rejected attempts and their reasons; `held` with a one-line explanation; one takeaway.
- **First visible signal (D-08):** each scenario declares one leading signal and direction:
  - `pool_leak`: `ledger.db` pool in-use, upward.
  - `poison_message`: `worker` completed throughput, downward.
  - `retry_storm`: `ledger` retry share, upward.

  The band is mean ± max(3σ, floor), computed from 1 s samples over the 300 s before onset. Floors: 1 connection, 2 jobs/s, 5 percentage points. The first visible signal is the start of the first run of ≥ 10 consecutive seconds after onset with the signal outside the band in the declared direction. The band parameters live in the scenario pack.
- If saving the result failed, the debrief includes the note "Couldn't save this result" (CTL-17).

**Dependencies:** CTL-15, CTL-07, SCN-04, SCN-05, SCN-06

**TDD traceability:** §11.1, §11.5, §12.3 (debrief example), FR-10; decisions D-02, D-08

---

#### CTL-17 · Results and session persistence

**Type:** Engineering task

**Description / value:** Keep completed results and the session mirror on the project volume, removable by `make down`.

**Acceptance criteria**
- Each completed round appends one JSON line to `/data/results.jsonl`. The line contains the scenario id, seed, session mode, scenario-pack version, build version, outcome, timings, actions, score breakdown, and the compressed `RoundEvent` log.
- **Wall-clock phase times (D-12):** UTC timestamps for each round:
  - `briefing_opened_at`: the prepare request.
  - `on_call_at`: start.
  - `debrief_opened_at`.
  - `debrief_closed_at`: the next prepare request, or session complete.

  Plus total paused seconds. Given a round's results line has already been written when `debrief_closed_at` becomes known, then a follow-up line `{round_id, debrief_closed_at}` is appended.
- No player name or other personal data is stored.
- `/data/session.json` mirrors the session state (CTL-03).
- Given `/data` is not writable, when a round completes, then gameplay continues and the debrief shows the save-failure note.
- Metric samples are never persisted in the MVP.

**Dependencies:** CTL-01, ENV-03

**TDD traceability:** §4.6, §12.1 (lifetimes), §13 (results volume), §14 (no personal data), §15.7, §16.3; decisions D-02, D-12

---

#### CTL-18 · Player-visible snapshot, stream, and metric history

**Type:** Engineering task

**Description / value:** Broadcast the live game state at 1 Hz, with hidden fields removed.

**Acceptance criteria**
- `WS /api/rounds/{id}/stream` sends `snapshot` (1 Hz), `alert`, `impact_event`, `action_update`, `state_change`, and `system_notice` messages. Field shapes follow §12.3.
- Before `DEBRIEF`, these are stripped from every message: `scenario_id`, `fault.*`, `effect_class`, and `held`.
- `GET /api/rounds/{id}/metrics?since_ms=` returns player-visible series from a 15-minute in-memory buffer (about 900 points × about 60 series).
- Given a client reconnects, then it receives a full snapshot plus history.
- Snapshots include the config snapshot and recent changes (SCN-02, SCN-07).

**Dependencies:** CTL-02, CTL-08, CTL-09, CTL-10, CTL-11

**TDD traceability:** §3.2 (trust boundary), §3.3, §6.5 (refresh), §8.5, §9.7, §12.2, §12.3

---

#### CTL-19 · Test-mode controls

**Type:** Engineering task

**Description / value:** Deterministic controls for automated tests that cannot be reached in player mode.

**Acceptance criteria**
- With `ESCAPE_TEST_MODE=1`, these are available:
  - `POST /api/test/clock/step {n}` (forwarded as `cmd.step`).
  - A seed override on round creation.
  - **`POST /api/test/inject {kind: "ledger_slowdown", duration_s ∈ {10, 20}}` (D-10).** This multiplies `ledger` hold times by 8 for the duration, through `cmd.test_inject`. Values outside the enumerations return 422.
- Without the flag, every `/api/test/*` path and the seed override return 404, and `sim` rejects `cmd.test_inject` and play-time `cmd.step` with `evt.error`.
- The flag is set only by the `make test` profile (ENV-11).

**Dependencies:** CTL-04, ENV-11, SIM-10

**TDD traceability:** §5.3, §12.2, §15.1, §15.5 (T-STABLE b); decision D-10

---

#### CTL-20 · Controller resilience and fail-closed handling

**Type:** Engineering task

**Description / value:** Separate failures of the game from simulated failures, and never time a player who can't see evidence.

**Acceptance criteria**
- **`sim` heartbeat missing for more than 3 s:** the round freezes, then goes to `ABORTED (sim_unavailable)`. Pending action costs are refunded, and a `system_notice` is sent. Once readiness is green again, **Restart round** is allowed.
- **Controller restart:** the live round is marked `ABORTED (controller_restart)` from `session.json`, and completed rounds are kept.
- **No ticks for 3 s or more while `ACTIVE`:** the round auto-pauses.
- **Periodic isolation check fails during play:** the round goes to `ABORTED (isolation_check_failed)`, the simulation stops, and the controller enters `LOCKED`. New rounds then get `423`. Readiness is 503.
- **Isolation fails at startup:** `LOCKED`, readiness 503.

**Dependencies:** CTL-02, CTL-04, CTL-07, ENV-07

**TDD traceability:** §5.6, §6.5, §13, SR-9

---

#### CTL-21 · Practice mode (untimed) rules

**Type:** Story

**Description / value:** As a player who wants to learn without time pressure, I want an untimed practice mode, so that I can explore the incident at my own pace. This is a small MVP addition approved as decision D-02. It settles the WCAG 2.2 "Timing Adjustable" question, and standard mode stays the default.

**Acceptance criteria**
- Given a session created with `mode: "practice"`, then rounds have no countdown. The timer reports elapsed time, and the round never reaches `TIMED_OUT`.
- `POST /api/rounds/{id}/end` is available only in practice mode (standard mode returns `409 invalid_state`). It moves the round to `ENDED` → `DEBRIEF`, with outcome `recovered_undeclared` if the system has been stable for ≥ W, else `not_recovered`.
- **Scoring:** `S_speed` is reported as `null` ("not scored in practice"), and every other component and penalty is unchanged. The maximum shown is 700.
- Results lines carry `mode: "practice"`. Practice rounds are excluded from self-play success-criteria measurements (REL-03).
- Standard-mode behavior is unchanged (verified by the QA-03 and QA-05 runs in standard mode).

**Dependencies:** CTL-03, CTL-04, CTL-06, CTL-15, CTL-17

**TDD traceability:** §2.4 (AR-1 to AR-4), §6.1, §11.2, §16.2 (time-pressure risk), §17 Q2; decision D-02

---

### E5: Player UI (`UI`)

#### UI-01 · Frontend foundation: app shell, API and stream clients, strings, version footer

**Type:** Engineering task

**Description / value:** The React/TypeScript base that every screen builds on.

**Acceptance criteria**
- Screen routing covers: welcome → briefing → console → debrief → session summary.
- A typed REST client handles the §12.4 error envelope.
- A WebSocket client reconnects with backoff and requests a full snapshot plus history after reconnecting.
- All copy comes from the string resource file. All fonts and assets are bundled, and the built app makes no request to any origin other than its own (QA-09).
- The footer shows the build version and scenario-pack version (REL-01).
- The layout targets current Chrome, Firefox, Edge, and Safari at 1280×800 and larger.

**Dependencies:** ENV-01, CTL-01

**TDD traceability:** §3.2, §9.9, §14 (no CDN), §17 (strings externalized, desktop only), NFR-6, OR-4

---

#### UI-02 · Welcome and environment screen

**Type:** Story

**Description / value:** As a new player, I want to see right away that everything is a local simulation and that the sandbox is verified, so that I know it's safe and what to expect.

**Acceptance criteria**
- The screen shows the safety notice from §5.4: "Everything you see is a simulation of a made-up store running on your computer. Actions here only change the simulation. Never practice these actions on real systems; use the sandbox."
- It shows the isolation status from `/api/health/ready` ("Sandbox verified: local only") when it passes.
- **Start session** is enabled only when the environment is ready.
- Given the controller is `LOCKED` or not ready, then **Start session** is disabled and the screen shows the environment-problem state (UI-15).

**Dependencies:** UI-01, CTL-03, SEC-06

**TDD traceability:** §5.4, §9.9 (screen 1), SR-10

---

#### UI-03 · Briefing screen

**Type:** Story

**Description / value:** As a player, I want a short briefing with the rules and a map of the system before going on call, so that I understand the budget, timer, and how to finish a round.

**Acceptance criteria**
- Shows "Round *n* of 3", the five-rule briefing copy from §6.6, and a system map: `api` → `jobs` → `worker` → `ledger`, with `api` → `ledger` for reads.
- The briefing is shown while the round is `PREPARING`. **Go on call** is enabled once the round reaches `BRIEFING`, and calls `POST /api/rounds/{id}/start`.
- The copy takes about 60 seconds to read and includes "Looking is free" and the 60-second stability rule.

**Dependencies:** UI-01, CTL-04, CTL-05

**TDD traceability:** §6.6, §9.9 (screen 2), §10.1, AR-5, FR-2

---

#### UI-04 · Incident console layout and top bar

**Type:** Story

**Description / value:** As an on-call player, I want one console showing the alert, time left, and budget alongside the evidence, so that I can investigate under pressure without hunting for information.

**Acceptance criteria**
- **Top bar:** the persistent label "SIMULATION · Larkspur Goods sandbox"; the page alert banner (symptom text, `FIRING`/`CLEARED`, secondary alerts); the timer; the budget meter ("7 of 12 points left"); **Pause**; **Declare resolved**.
- When an alert shows `CLEARED`, the banner reads "Alert cleared — verify before declaring."
- **Regions:** left for status and health (UI-05); center for the metric grid (UI-06); right for impact (UI-09); a bottom drawer with Actions, Recent changes, Config, and Action log tabs (UI-08, UI-10).
- **Timer:** text plus a progress ring, with screen-reader announcements at 5:00, 1:00, and 0:15.
- The console updates from the 1 Hz stream with no full re-render flicker.

**Dependencies:** UI-01, CTL-18

**TDD traceability:** §9.9 (screen 3), §9.6, §9.10, §5.4, AR-3

---

#### UI-05 · Service status chips and health panel

**Type:** Engineering task

**Description / value:** Show process status and the health checks as evidence, without spoilers.

**Acceptance criteria**
- Each service row starts with a status chip, `Up`, `Restarting`, or `Crash-looping`, each with an icon and text. No chip implies "faulty service."
- The health panel lists all ten checks with ✓/✕ plus "passing"/"failing" text and the current value. There is **no** countdown or "green for N s" indicator.
- A pending-action spinner with time remaining appears on the affected target.
- Given the 180 s stability nudge event, then the gentle prompt "Things look steady. Ready to declare?" appears once.

**Dependencies:** UI-04, CTL-08, CTL-06

**TDD traceability:** §6.4, §9.2, §9.3, §9.7, §9.10, §10.3 (concurrency), AR-2

---

#### UI-06 · Metric grid and charts

**Type:** Story

**Description / value:** As a player, I want latency, errors, throughput, queue depth, and pool use for each service in one aligned grid, so that I can compare signals and isolate the failing component.

**Acceptance criteria**
- **Grid:** rows `api`, `worker`, `ledger`; columns are the five metric families, populated as in §9.2. Metrics that don't apply show "—" with an explanatory tooltip.
- **Breakdowns are toggleable in the legend:** errors by reason; `api` throughput by flow; `ledger` by caller × attempt; `worker` attempts vs completed; `jobs` head delivery attempts and DLQ count; `ledger.requests` against its cap of 300.
- **Interactions:**
  - A shared time cursor across all charts.
  - Time range 5 min, 15 min (default), or "since alert".
  - Threshold lines for health checks and alert rules on the relevant charts.
- **Palette (D-15):** series colors use the Okabe–Ito categorical palette, defined as UI style tokens. Status emphasis uses blue/orange with icons and text, never red/green alone. Lines, markers, and icons meet WCAG 1.4.11 non-text contrast (≥ 3:1) against the chart background in the shipped theme; shades are adjusted where needed and recorded in the tokens.
- History from pre-roll is visible when the console opens.

**Dependencies:** UI-04, CTL-18

**TDD traceability:** §9.1, §9.2, §9.5, §9.10, FR-4, AR-2; decision D-15

---

#### UI-07 · Chart alternatives: table view and text summaries

**Type:** Engineering task

**Description / value:** Make every chart usable without seeing it.

**Acceptance criteria**
- Every chart has **View as table**, showing the series values over the selected range.
- Every chart has a generated text summary built only from visible data, for example "ledger.db pool: 10 of 10 in use; has risen in steps over the last 4 minutes." Summaries never contain hidden fields or cause words.
- Summaries are reachable by screen reader and keyboard.

**Dependencies:** UI-06

**TDD traceability:** §9.5, AR-3

---

#### UI-08 · Recent changes and Config panels

**Type:** Engineering task

**Description / value:** Present change history and current settings as free evidence.

**Acceptance criteria**
- **Recent changes** lists 3–4 timestamped entries from the stream (SCN-07).
- **Config** (read-only) shows feature flags, retry policy per caller, timeouts, pool sizes, and the queue cap, and updates when an action takes effect.
- Viewing either panel costs nothing and changes nothing.

**Dependencies:** UI-04, CTL-18, SCN-02, SCN-07

**TDD traceability:** §9.4, §10.1 ("Investigating is always free")

---

#### UI-09 · Customer-impact feed and counters panel

**Type:** Engineering task

**Description / value:** Show customer impact as fictional complaints and counters.

**Acceptance criteria**
- Shows "Customers affected, last 5 min" and "Open support tickets" from the stream, and feed items in reverse time order with fictional customer details.
- **Pre-roll history (D-09):** items flagged `pre_alert` appear below a "Before the alert" divider when the console opens and are not announced by screen readers.
- Live items are announced through a polite live region, at most one announcement every 10 s.
- With no bad events, the panel shows no complaint items.

**Dependencies:** UI-04, CTL-10, CTL-11

**TDD traceability:** §9.8, §9.10, FR-6, AR-3; decision D-09

---

#### UI-10 · Actions drawer, confirmation dialog, and action log

**Type:** Story

**Description / value:** As a player, I want to see each action's cost, delay, and side effects and confirm expensive ones, so that I spend my change budget deliberately.

**Acceptance criteria**
- The drawer lists the catalog from `GET /api/actions/catalog`. Targets and params are chosen only from enumerated controls; there is no free-text field.
- **Confirmation dialog:** shows the target as `sim/<target>`, the cost, delay, side effects, budget remaining after the action, and the text "Simulated action: affects only this sandbox." It is required for actions costing 3 or more; for others, it is controlled by the "Confirm all actions" setting.
- **"Confirm all actions" (D-14):** stored per browser in `localStorage`, with reads and writes wrapped in try/catch and a fall-back to the default when storage is unavailable. Default off. It is never sent to the server and does not affect scoring.
- For `restart_all`, the dialog states that queued jobs will be lost.
- Rejections (`insufficient_budget`, `no_change`, `action_in_progress`, `target_unavailable`, `invalid_state`) are shown inline with the server message, and the budget is unchanged.
- Double-clicking or retrying sends the same `client_request_id` and is not charged twice.
- The **Action log** lists every action and rejected attempt with time, cost, and status.

**Dependencies:** UI-04, CTL-12, CTL-13

**TDD traceability:** §9.9 (screen 4), §10.1, §10.3, §5.4, §12.3, FR-7, SR-7, SR-10; decision D-14

---

#### UI-11 · Pause, restart round, and reset session controls

**Type:** Story

**Description / value:** As a player, I want to pause, restart a round, or reset the session, so that I can take a break or start over safely.

**Acceptance criteria**
- **Pause:** blurs the dashboard, shows a pause overlay with **Resume** and **Restart round**, and the timer visibly freezes. Pause is available throughout `ACTIVE`.
- **Restart round:** after a confirmation, it calls `/restart`. A new attempt of the same scenario opens at the briefing, and the aborted attempt is not scored.
- **Reset session:** after a confirmation, it creates a new session. Earlier results are kept.

**Dependencies:** UI-04, CTL-04, CTL-03

**TDD traceability:** §6.1 (`PAUSED`), §4.6 (reset behavior), §13 (safe reset paths), FR-11, AR-4

---

#### UI-12 · Declare-resolved flow

**Type:** Story

**Description / value:** As a player, I want to declare resolution and get clear feedback if it's premature, so that I learn to confirm a fix holds.

**Acceptance criteria**
- Clicking **Declare resolved** calls the endpoint. On acceptance, the debrief opens.
- On `409 not_stable`, the UI shows the server's message (for example "green for 22 s of the required 60 s") and the −50 penalty, and the round continues.
- Repeated premature declarations each show the penalty, up to the cap of 3, after which no further penalty is shown.

**Dependencies:** UI-04, CTL-14

**TDD traceability:** §6.4, §11.2, §12.3, FR-9

---

#### UI-13 · Debrief screen

**Type:** Story

**Description / value:** As a player, I want a clear explanation of what broke, what the evidence showed, and how my actions scored, so that I can explain the root cause and do better next time.

**Acceptance criteria**
- The screen shows:
  - The outcome and total score, with a breakdown table (each component against its maximum).
  - "What broke": 2–3 sentences, with a highlight on the system map.
  - Timing: fault began, first visible signal, alert (TTD), healthy from (TTR), declared at.
  - 2–3 clues with chart snapshots.
  - Every action with time, cost, and penalty, plus rejected attempts.
  - "Did it hold?" with a one-line reason.
  - One takeaway.
  - **Next round**.
- It shows the "Couldn't save this result" note when present.
- It does not show a metric-overlaid helped/hurt timeline (stretch, §16.3).

**Dependencies:** UI-01, CTL-16

**TDD traceability:** §9.9 (screen 5), §11.5, FR-10

---

#### UI-14 · Session summary screen

**Type:** Story

**Description / value:** As a player, I want a summary of all three rounds, so that I can see my progress and what to practice next.

**Acceptance criteria**
- Lists the three rounds with outcome, score, root cause, and the next learning tip for each, and labels the session mode (Standard or Practice).
- Opening the summary calls `POST /api/sessions/current/complete` (D-13).
- Restarted (aborted) attempts are not shown as scored rounds.
- Offers **Start new session**.

**Dependencies:** UI-13, CTL-03

**TDD traceability:** §9.9 (screen 6), FR-1; decisions D-02, D-13

---

#### UI-15 · System notices and game-failure states

**Type:** Engineering task

**Description / value:** Make it unmistakable when something is a game problem rather than part of the incident.

**Acceptance criteria**
- Game failures use a neutral grey banner with a "game" icon and the text "This is a problem with the game, not part of the incident." The incident styling is never reused for them.
- **States covered:**
  - "Reconnecting to the game…" with retry backoff on 502 or a dropped WebSocket.
  - Round aborted (`sim_unavailable`, `controller_restart`), with **Restart round** enabled once the environment is ready.
  - Per-panel error boundaries showing "Panel unavailable (game issue)" with a retry button.
  - Auto-pause on missing ticks.
  - "Starting…" and "Environment problem" before readiness.
  - A full-screen isolation failure: "Safety check failed — the game has stopped. Run `make down` and then `make up`." No continue option.
- No playable round is shown unless the environment is ready.

**Dependencies:** UI-01, CTL-20

**TDD traceability:** §13, §5.6, §6.5

---

#### UI-16 · Glossary tooltips for metrics and actions

**Type:** Engineering task

**Description / value:** Plain-language help so players without SRE expertise can follow the evidence.

**Acceptance criteria**
- Every metric name and every action has a one-line tooltip, for example "p95 latency: 95% of requests were faster than this."
- Tooltips are reachable by keyboard and by screen reader.
- Tooltip text contains no scenario-specific hints (it passes the SEC-06 lint).

**Dependencies:** UI-06, UI-10, SEC-06

**TDD traceability:** §9.5, AR-5

---

#### UI-17 · Accessibility compliance pass

**Type:** Engineering task

**Description / value:** Meet the accessibility requirements across every screen.

**Acceptance criteria**
- WCAG 2.2 AA contrast and visible focus throughout. Every control can be operated by keyboard.
- No state is conveyed by color alone.
- **Live regions:** the page alert is assertive; the feed and action completions are polite, rate-limited to one announcement every 10 s.
- With reduced motion set, pulsing and animations are disabled.
- Text scales to 200% without loss of content or function.
- An axe-core scan shows no serious or critical violations (QA-09).

**Dependencies:** UI-02 through UI-16

**TDD traceability:** §2.4 (AR-1 to AR-4), §9.10

---

#### UI-18 · Practice mode UI

**Type:** Story

**Description / value:** As a player, I want to choose an untimed practice session and see clearly that speed isn't scored, so that I can learn without pressure (D-02).

**Acceptance criteria**
- The welcome screen offers **Standard** (default) or **Practice (untimed)**, with one sentence explaining each.
- **In practice mode:**
  - The console shows elapsed time and a "Practice" badge in place of the countdown, and there are no timer announcements.
  - An **End round** button (with confirmation) calls `POST /api/rounds/{id}/end`.
  - The debrief shows speed as "not scored in practice" and a total out of 700.
- Standard mode shows no practice controls.
- Keyboard and screen-reader access matches UI-17.

**Dependencies:** UI-02, UI-04, UI-13, UI-14, CTL-21

**TDD traceability:** §2.4, §9.9, §9.10; decision D-02

---

### E6: Security, privacy, and content (`SEC`)

#### SEC-01 · Dependency and image pinning

**Type:** Engineering task

**Description / value:** A reproducible, tamper-resistant supply chain.

**Acceptance criteria**
- Base images are pinned by digest.
- Python dependencies are hash-pinned (a `uv` lock, or `pip-tools` with `--require-hashes`). The build fails on any unpinned dependency.
- UI dependencies are installed with `npm ci` from the committed lockfile.
- Nothing is installed at runtime (verified by starting containers with networking disabled).

**Dependencies:** ENV-01, ENV-02

**TDD traceability:** §14 (dependencies and containers), NFR-1

---

#### SEC-02 · Banned-API lint for `sim` (no outbound networking)

**Type:** Engineering task

**Description / value:** Make it impossible to merge `sim` code that can reach out of the sandbox or touch real processes.

**Acceptance criteria**
- ruff banned-api plus import-linter fail CI on any use within `sim/**` of: `socket.create_connection`, `socket.socket.connect`, `urllib.request`, `http.client`, `requests`, `httpx`, `aiohttp`, `websockets.connect`, `subprocess`.
- The `sim` WebSocket server code is the only allowed network code.
- A deliberately failing fixture proves the lint catches each banned API.

**Dependencies:** ENV-01

**TDD traceability:** §5.2, SR-6, T-ISO-3 (lint clause)

---

#### SEC-03 · CI security scanning and SBOM

**Type:** Engineering task

**Description / value:** Catch vulnerable dependencies and images before release.

**Acceptance criteria**
- CI runs `pip-audit` and `npm audit`. A high or critical finding fails the build.
- CI runs Trivy on all three images.
- An SBOM is generated and attached as a build artifact.

**Dependencies:** SEC-01, QA-18

**TDD traceability:** §14

---

#### SEC-04 · Local-only data handling verification

**Type:** Test

**Description / value:** Prove that no data leaves the machine and no personal data is stored.

**Acceptance criteria**
- **CSP header present:** `default-src 'self'; connect-src 'self'` (ENV-05).
- The UI bundle contains no telemetry, analytics, crash reporting, update check, or external font or CDN reference. A static scan of the build output finds no external URLs other than documentation links in the README.
- `results.jsonl` and `session.json` contain no player name or other personal field (schema check).
- The UI is reachable on loopback only (covered in QA-10).

**Dependencies:** ENV-05, UI-01, CTL-17

**TDD traceability:** §14 (local only, no real data, local exposure), SR-8

---

#### SEC-05 · Curated fictional data lists

**Type:** Engineering task

**Description / value:** Fictional customers, products, and cities for the feed, so no real people or companies ever appear.

**Acceptance criteria**
- Bundled lists of fictional first names with initials, products, and cities for "Larkspur Goods", and an active-customer pool of 2,500 *(default)*.
- The brand name is a single string constant, so it can be renamed without code changes.
- No list entry references a real company, person, or product. Review is recorded per the sign-off process in SEC-06 (D-03).
- The lists are baked into the image and need no runtime fetch.

**Dependencies:** ENV-01

**TDD traceability:** §14 (no real data), §9.8; decision D-03

---

#### SEC-06 · Player-facing copy, feed templates, and content lint

**Type:** Engineering task

**Description / value:** Write and gate every player-facing text so it stays safe, spoiler-free, and in the fictional world.

**Acceptance criteria**
- **Copy authored:**
  - Feed templates per category, including escalating and recovery variants.
  - Neutral chatter.
  - Briefing rules (§6.6) and the safety notice (§5.4).
  - Debrief explanation, clues, and takeaway per scenario, framed around observing and recovering.
  - Alert text, glossary tooltips, system notices, and practice-mode text.
- **Lint fails CI** on:
  - Banned cause words in feed templates (`pool`, `leak`, `retry`, `poison`, `queue`, `connection`, `storm`, `flag`).
  - Profanity-list matches in any template.
  - Any text suggesting players apply these techniques outside the sandbox.
- **Sign-off (D-03):** you are the sole approver. Before approving:
  1. The CI content lint passes.
  2. A fresh AI session with no project context reviews all player-facing copy against the checklist (tone, no spoilers, fictional names only, safety framing). Its findings are fixed or noted.
  3. You re-read the copy on a different day from writing it.
  
  The approval, the AI review transcript, and the pack version are recorded under `reviews/content/`.
- **Before publishing the repository or sharing the game:** run a name-clash search on "Larkspur Goods". If a real business uses the name, rename it through the brand constant (SEC-05).

**Dependencies:** ENV-01

**TDD traceability:** §5.4, §9.7, §9.8, §11.5, §14 (feed content boundaries), SR-10, §17 Q3; decision D-03

---

#### SEC-07 · README and safety-first documentation

**Type:** Engineering task

**Description / value:** Documentation that puts safety first and explains setup per supported host, commands, and troubleshooting.

**Acceptance criteria**
- The first README section is safety: everything is a local simulation, there is no setting that targets other systems, and the game refuses remote Docker engines.
- **Setup per supported host (D-01):**
  - **Linux:** Docker Engine ≥ 28.0 with Compose ≥ v2.20 and buildx.
  - **macOS with Colima:** `brew install colima docker docker-compose docker-buildx`; `cliPluginsExtraDirs` in `~/.docker/config.json`; `colima start --cpu 2 --memory 4`.
  - **Untested:** Docker Desktop (macOS or Windows) and Docker inside WSL2. Preflight warns, and the game runs only if every isolation check passes.
  - **Unsupported:** Podman.
- Documents all make targets (§4.7, plus `make export-results`), `ESCAPE_PORT`, `KEEP_ON_FAIL=1`, `make down FORCE=1`, offline preparation with `make build`, the reset paths (§13), practice mode, and that exported results files are not removed by `make down`.
- Explains dev mode (Vite inside the `ui` container; Colima shared-directory requirement) and that running Vite on the host is unsupported.
- Contains no guidance suggesting fault injection on real, shared, or public systems.
- Passes the SEC-06 copy lint.

**Dependencies:** ENV-09, ENV-10, ENV-11, ENV-13, ENV-14

**TDD traceability:** §5.4, §4.1, §4.2, §4.7, §13, SR-10; decisions D-01, D-02, D-04, D-06

---

### E7: Test automation and verification (`QA`)

#### QA-01 · Headless scenario harness and scripted policies

**Type:** Test

**Description / value:** Fast, container-free tests of scenarios and scoring.

**Acceptance criteria**
- A pytest harness drives the `sim` engine library directly with a manual clock and fixed seeds. It also runs the controller's game-rule modules (health, alerts, impact, scoring) against the resulting tick stream.
- Scripted policies run actions at chosen simulation times (for example, "at T0+60 s, do X").
- A full 12-minute round runs in a few seconds of wall time.
- The harness extracts the player-visible stream using the same stripping code as CTL-18.

**Dependencies:** SIM-10, SCN-04, SCN-05, SCN-06, CTL-08, CTL-09, CTL-10, CTL-15, CTL-18

**TDD traceability:** §15.1

---

#### QA-02 · T-DIAG: diagnosability and distinct signatures

**Type:** Test

**Description / value:** Automated proof that each scenario can be diagnosed from visible evidence and that the three are distinguishable (SC-2a).

**Acceptance criteria**
- For 3 scenarios × 50 seeds, a rule-based classifier reads **only** the player-visible stream at T0+60 s and applies the §7.2 signature rules. It classifies 100% correctly.
- Every signature cell in §7.2 holds for every seed. This includes the expected paging rule per scenario.
- Seed variation never changes the mechanism or signature (§8.6).

**Dependencies:** QA-01

**TDD traceability:** §15.5 (T-DIAG), §7.2, §8.6, SC-2

---

#### QA-03 · T-SCORE: targeted fix beats restart-all

**Type:** Test

**Description / value:** Prove the scoring invariant across seeds and decision times (SC-3).

**Acceptance criteria**
- For 3 scenarios × 50 seeds × decision times {30, 60, 120, 240} s, the targeted policy's score exceeds `restart_all`'s at the same decision time in 100% of runs, with a median margin of ≥ 250.
- **Fairness case:** the targeted fix at 180 s beats `restart_all` at 20 s in every scenario.
- `restart_all` reaches outcome `recovered` in every run (FR-8).
- Re-running after any tuning change (REL-05, REL-06) is required before merge.

**Dependencies:** QA-01, CTL-15

**TDD traceability:** §15.5 (T-SCORE), §11.4, §10.4, FR-8, SC-3

---

#### QA-04 · T-EFFECT: effect matrix matches behavior

**Type:** Test

**Description / value:** Prove that the authored effect classifications in §10.2 match what the simulation does.

**Acceptance criteria**
- Each action is applied to each scenario at T0+60 s.
- Actions classified "fix", "mitigates", or "restores" reach all-healthy within 120 s.
- Actions classified "no effect" or "unhelpful" do not.
- Actions classified "rejected: `no_change`" return 409 with no charge.

**Dependencies:** QA-01, SCN-08, SCN-09, SCN-10, CTL-12

**TDD traceability:** §15.5 (T-EFFECT), §10.2

---

#### QA-05 · T-STABLE: recovery must stay stable

**Type:** Test

**Description / value:** Prove the stability and holds rules.

**Acceptance criteria**
- (a) A declaration 10 s after a fix is rejected with `not_stable`.
- (b) Using `POST /api/test/inject {kind: "ledger_slowdown", duration_s: 10}` 50 s into the healthy window resets `healthy_since`, and a declaration 15 s later is rejected.
- (c) `restart_service(ledger)` in `retry_storm` never yields an accepted declaration.
- (d) `recycle_pool` alone in `pool_leak` reports `held = false`.

**Dependencies:** QA-01, CTL-14, CTL-19

**TDD traceability:** §15.5 (T-STABLE), §6.4; decision D-10

---

#### QA-06 · T-FEED: impact tracks real errors

**Type:** Test

**Description / value:** Prove that the feed and counters never contradict the system state.

**Acceptance criteria**
1. Every feed item's evidence count is at least the minimum and equals the simulation's bad-event count for that window.
2. Across baseline seconds with zero bad events, no complaint items appear.
3. The ticket and affected-customer counters exactly equal their formulas over the bad-event series.
4. The per-minute correlation between bad events and feed items is ≥ 0.8 across a round.
5. No recovery message appears while any category is non-zero.

**Dependencies:** QA-01, CTL-10, CTL-11

**TDD traceability:** §15.5 (T-FEED), §9.8

---

#### QA-07 · T-SPOIL: no hidden information leaks

**Type:** Test

**Description / value:** Prove the trust boundary holds.

**Acceptance criteria**
- No player-visible message (REST responses, stream messages, metric history) before `DEBRIEF` contains `scenario_id`, `fault.*`, `effect_class`, or `held`.
- This is checked across full rounds of all three scenarios, including reconnects and error responses.

**Dependencies:** CTL-18, CTL-13, QA-01

**TDD traceability:** §15.5 (T-SPOIL), §3.2, §9.7

---

#### QA-08 · Controller ↔ `sim` integration tests

**Type:** Test

**Description / value:** Verify the real WebSocket link and lifecycle behavior.

**Acceptance criteria**
- Starting a round produces ticks at 1 Hz in simulation time. Actions are applied after their exact delays.
- Pausing freezes ticks and delays. Resuming continues with identical results compared with an unpaused run.
- Killing `sim` mid-round produces abort, refund, a system notice, and readiness once `sim` restarts.
- Restarting the controller aborts the live round, keeps completed rounds, and restores `session.json`.

**Dependencies:** CTL-02, CTL-04, CTL-13, CTL-20, SIM-10

**TDD traceability:** §15.3, §13, §6.5

---

#### QA-09 · End-to-end, keyboard-only, and accessibility tests (test profile, per commit)

**Type:** Test

**Description / value:** Verify the full player journey and the accessibility and safety copy in a real browser, quickly enough to run on every change (D-11).

**Acceptance criteria**
- The suite runs against the full Compose stack in the `make test` profile, with isolation checks active, the manual clock, and fixed seeds.
- A full standard session of three rounds with scripted targeted fixes reaches the session summary. A practice-mode round ends through **End round**.
- A keyboard-only run-through completes a round.
- An axe-core scan of every screen reports no serious or critical violations.
- The safety notice appears on the welcome screen, the SIMULATION label on the console, and the sandbox-target text in every action dialog.
- The browser makes no network request to any origin other than `127.0.0.1:<port>`.
- The suite runs on current Chrome, Firefox, Edge (Chromium), and Safari (WebKit) at 1280×800.

**Dependencies:** UI-17, UI-18, ENV-09, CTL-19

**TDD traceability:** §15.4, NFR-6, AR-1–AR-4, SR-10, §14; decisions D-02, D-11

---

#### QA-10 · T-UP and T-DOWN: environment lifecycle and scoping

**Type:** Test

**Description / value:** Prove the one-command environment behavior (SC-5).

**Acceptance criteria**
- **T-UP:** on a clean Linux runner, `make up` exits 0; readiness is green in 60 s or less on a warm machine; isolation status is `pass`. The UI loads at `127.0.0.1:8080` and is *not* reachable on the runner's non-loopback IP.
- **T-DOWN:** before `make up`, create an unlabeled sentinel container, network, and volume. After `make down`:
  - no resource with the project label or name remains;
  - the sentinels and base images are unchanged;
  - `./.escape/` is gone.
- A second `make down` exits 0.

**Dependencies:** ENV-09, ENV-10, QA-18

**TDD traceability:** §15.6 (T-UP, T-DOWN), OR-1, OR-3, SR-1, SR-8, SC-5

---

#### QA-11 · T-ISO-1: static policy with negative fixtures

**Type:** Test

**Description / value:** Prove that unsafe Compose configuration cannot start.

**Acceptance criteria**
- The shipped config passes ENV-06.
- Each of these negative fixtures fails `make up` preflight with the matching rule named: `network_mode: host`, `privileged: true`, a Docker socket mount, and a port bound to `0.0.0.0`.

**Dependencies:** ENV-06, ENV-09

**TDD traceability:** §15.6 (T-ISO-1), §5.5

---

#### QA-12 · T-ISO-2: runtime routing and privileges

**Type:** Test

**Description / value:** Prove the isolation state inside the running containers.

**Acceptance criteria**
- Inside `sim` and `controller`:
  - no default route;
  - `CapEff` = 0;
  - non-root UID;
  - no bind mounts;
  - DNS for `isolation-check.invalid` fails.

**Dependencies:** ENV-07, ENV-09

**TDD traceability:** §15.6 (T-ISO-2), §5.5

---

#### QA-13 · T-ISO-3: no external traffic during a full session

**Type:** Test

**Description / value:** Prove empirically that no scenario sends traffic outside the sandbox.

**Acceptance criteria**
- **Method (D-17):** runs on an ephemeral Linux VM CI runner with passwordless sudo. `tcpdump` runs on the runner host, outside the Compose project, capturing the `escape_internal` bridge interface and the default egress interface during a full scripted session of all three scenarios.
- The capture shows zero packets from `sim` or `controller` to addresses outside the internal subnet, and zero DNS queries for non-service names. The pcap is kept as a CI artifact.
- No game container is given added capabilities or extra mounts for this test (asserted by ENV-06 on the same run).
- The `sim` banned-API lint (SEC-02) passes in the same pipeline.
- **Colima check (manual, in REL-02):** `colima ssh -- sudo tcpdump -i any` inside the VM during a session, with the same pass criteria.

**Dependencies:** ENV-09, QA-01, SEC-02, QA-18

**TDD traceability:** §15.6 (T-ISO-3), SR-2, SR-6; decision D-17

---

#### QA-14 · T-ISO-4: single upstream and target confinement

**Type:** Test

**Description / value:** Prove that the edge and API accept no external targets.

**Acceptance criteria**
- The nginx config has exactly one upstream (`controller:8000`) and no `resolver`.
- Action requests with a non-enumerated target, or with any field containing a URL, host, IP address, or path, return 422 with no charge.

**Dependencies:** ENV-05, CTL-12

**TDD traceability:** §15.6 (T-ISO-4), §5.1, §5.3, SR-7

---

#### QA-15 · T-ISO-5: fail-closed behavior

**Type:** Test

**Description / value:** Prove that failed isolation stops the game.

**Acceptance criteria**
- Each broken override makes `make up` exit non-zero and tear down. The overrides are: the internal network without `internal: true`; an injected fake `AWS_ACCESS_KEY_ID`.
- A periodic self-check failure forced mid-round aborts the round (`isolation_check_failed`), locks the controller (`423` on new rounds), and shows the UI full-screen notice.

**Dependencies:** ENV-09, CTL-20, UI-15, CTL-19

**TDD traceability:** §15.6 (T-ISO-5), §5.6, SR-9

---

#### QA-16 · T-ISO-6: test endpoints absent in player mode

**Type:** Test

**Description / value:** Prove that deterministic test controls are unreachable for players.

**Acceptance criteria**
- With the `make up` profile, every `/api/test/*` path and the seed override return 404, and `ESCAPE_TEST_MODE` is absent from every container's environment.

**Dependencies:** CTL-19, ENV-11

**TDD traceability:** §15.6 (T-ISO-6), §5.3

---

#### QA-17 · Non-functional verification: determinism, performance, resources, startup

**Type:** Test

**Description / value:** Verify the measurable non-functional requirements.

**Acceptance criteria**
- **NFR-5:** the same seed and the same timed actions produce identical tick streams *and* identical feed items across 3 runs per scenario.
- **NFR-2:**
  - One 100 ms step computes in under 20 ms at 4× baseline load (p99 over a run).
  - Action acknowledgment is under 200 ms (p99).
  - The dashboard receives snapshots at 1 Hz with no gaps under normal load.
  - Pre-roll (stepped) completes in 15 s of wall-clock time or less on the CI runner.
- **NFR-3:** measured peak CPU stays within 1 core and RAM within 600 MB across a full session, including `retry_storm`.
- **NFR-4:** warm `make up` reaches ready in 60 s or less. Cold `make up` (including builds) takes 5 minutes or less on a CI runner with typical bandwidth. The same two timings are recorded on Colima in REL-02.

**Dependencies:** QA-01, ENV-09, CTL-05, CTL-12

**TDD traceability:** §2.2 (NFR-2–NFR-5), §4.4; decisions D-05, D-18

---

#### QA-18 · CI pipeline

**Type:** Engineering task

**Description / value:** Run every automated check on every change.

**Acceptance criteria**
- **Per-commit stages:**
  1. Lint (including SEC-02 and the SEC-06 content lint).
  2. Unit tests.
  3. Headless scenario tests (QA-02 to QA-07).
  4. Integration (QA-08).
  5. Environment and isolation tests on a clean ephemeral Linux VM runner (QA-10 to QA-16).
  6. End-to-end in the test profile (QA-09).
  7. NFR checks (QA-17).
  8. Security scans and SBOM (SEC-03).
- **Architecture coverage (D-01):** images are built natively on `linux/amd64`. On `linux/arm64` (a native arm64 runner where available, otherwise buildx with emulation for the build only), the images are built and the unit and headless scenario suites run.
- **Nightly and pre-release:** the player-profile real-time smoke test (QA-19).
- A failure in any per-commit stage blocks merging. The environment and isolation stage starts each run from a clean Docker state.

**Dependencies:** ENV-11

**TDD traceability:** §15, §16.1 (Phase 0 CI); decisions D-01, D-11, D-17

---

#### QA-19 · Player-profile real-time smoke test (nightly and pre-release)

**Type:** Test

**Description / value:** Prove that the real `make up` experience works end to end without test controls (D-11).

**Acceptance criteria**
- Runs against `make up` (the player profile; test endpoints return 404) in real time.
- The test plays one round. It reads only the player-visible stream, uses the QA-02 classifier to choose the targeted fix, applies it through the UI, waits for stability, and declares.
- Asserts: outcome `recovered`; the safety notice and SIMULATION label are present; there are no requests to other origins; `make down` afterward leaves no labeled resources.
- Completes in about 3–6 minutes. Runs nightly and is required before tagging a release (REL-07).

**Dependencies:** QA-02, QA-10, ENV-09, UI-17

**TDD traceability:** §15.4 ("against `make up`"), SC-5; decision D-11

---

### E8: Self-testing, tuning, and release (`REL`)

#### REL-01 · Build and scenario-pack version stamping

**Type:** Engineering task

**Description / value:** Make every self-play result and review traceable to a build and a tuning set.

**Acceptance criteria**
- The build version is stamped into all three images at build time, and the scenario-pack version is read from SCN-01.
- Both versions appear in the UI footer (UI-01) and in every `results.jsonl` line (CTL-17).
- Any tuning change increments the scenario-pack version.

**Dependencies:** SCN-01, UI-01, CTL-17

**TDD traceability:** OR-4, §15.7 (tuning recorded in pack version), §17

---

#### REL-02 · Host verification: your Colima laptop and Linux CI

**Type:** Test

**Description / value:** Verify the two tier-1 hosts in D-01 before each release, using only your own laptop and CI.

**Acceptance criteria**
- **Linux with Docker Engine ≥ 28.0** is covered by CI (QA-10 to QA-17).
- **Colima on your laptop:**
  - Run `make up` cold and warm (recording the NFR-4 timings), a full standard session, `make export-results`, and `make down`.
  - Confirm the UI loads at `127.0.0.1:<port>` on the laptop. Confirm it is **not** reachable from another device you own on the same network (for example, your phone, using the laptop's LAN IP).
  - Confirm the runtime isolation checks pass, and that a `colima ssh -- sudo tcpdump -i any` capture during the session shows no external traffic (QA-13).
  - Before `make up`, create one unrelated sentinel container, network, and volume. After `make down`, confirm the sentinels are untouched.
- **Refusal checks:**
  - Create a dummy remote context, for example `docker context create escape-remote-test --docker host=ssh://nobody@escape-test.invalid`. Preflight (ENV-13) must refuse it before attempting any connection. Delete the context afterward.
  - Podman refusal is covered by ENV-13's unit tests with recorded output, so no Podman install is needed.
- Docker Desktop and Docker inside WSL2 are **not verified**. The README lists them as untested.
- Results are recorded with the build and pack versions.

**Dependencies:** ENV-09, ENV-10, ENV-13, ENV-14, QA-12, QA-13

**TDD traceability:** §4.1, §16.2 (Docker host differences risk), SR-8, NFR-4; decisions D-01, D-17, D-19

---

#### REL-03 · Self-play protocol and evidence log

**Type:** Other (self-testing and preparation)

**Description / value:** A repeatable way for you, as the only tester, to play the game and record evidence for the success criteria. It is honest about what self-play can and cannot show (D-19).

**Acceptance criteria**
- Sessions use **standard mode** with fresh random seeds. Practice rounds are excluded. Results are exported after each session (ENV-14).
- **Per-round evidence log** (a Markdown or CSV template in `reviews/self-play/`):
  - Round duration from `briefing_opened_at` to `debrief_closed_at` (CTL-17).
  - Time per phase.
  - The first non-restart action and whether it targeted the culprit.
  - Friction notes.
  - A fairness rating on a 1–5 scale.
- The template marks self-play timing as a **lower bound** for SC-1, because the developer already knows each scenario's cause.
- A summary script reads the exported files and the log, and reports the status of each success criterion as one of: verified, proxy-verified, or not validated (D-19).

**Dependencies:** UI-17, QA-09, CTL-17, ENV-14

**TDD traceability:** §2.6 (SC-1, SC-2c, SC-4), §15.7; decisions D-04, D-12, D-19

---

#### REL-04 · Blind diagnosability review by fresh AI sessions (SC-2b proxy)

**Type:** Test

**Description / value:** With no human reviewers available, check that the dashboards can be read without inside knowledge by asking AI sessions that have never seen the project (D-16, D-19).

**Acceptance criteria**
- **Inputs:** using the test profile with fixed seeds, capture full-console screenshots 90 s after the alert for each scenario, plus the metric glossary text.
  - Each set is labeled only A, B, or C, in shuffled order.
  - Nothing (file names, metadata, or visible text) names the scenario.
- **Reviewers:** three separate, fresh AI chat sessions with no project context, design documents, tickets, or scenario YAML. Each is asked to name, for every set, the failing component and the mechanism.
- **Pass:** at least 8 of 9 answers name the correct component *and* mechanism.
- The prompts, inputs, and responses are saved under `reviews/diagnosability/<pack-version>/`.
- The review is recorded as a **proxy**: the AI sessions are not the target players.

**Dependencies:** QA-02, UI-06

**TDD traceability:** §2.6 (SC-2b); decisions D-16, D-19

---

#### REL-05 · Self-play round 1 and tuning

**Type:** Other (self-testing and tuning)

**Description / value:** First self-play pass, followed by tuning that changes data only.

**Acceptance criteria**
- At least one full standard session is played and logged with the REL-03 protocol.
- Tuning changes go only through scenario-pack and controller configuration, limited to the parameters marked in §8.7:
  - noise
  - leak probability
  - maintenance multiplier and duration
  - capacity margin
  - alert thresholds
  - stability window (W)
  - round time limit
  - action costs and score weights
  - feed rate cap
- The pack version is incremented (REL-01).
- QA-02, QA-03, QA-04, QA-05, and QA-06 pass on the tuned pack.

**Dependencies:** REL-03, REL-01, QA-02, QA-03

**TDD traceability:** §8.7, §15.7, §16.2 (tuning risk); decision D-19

---

#### REL-06 · Self-play round 2 and success-criteria sign-off

**Type:** Other (self-testing and acceptance)

**Description / value:** Confirm the tuned build meets every success criterion that can be checked alone, and record plainly the ones that can't (D-19).

**Acceptance criteria**
- A second standard session is played and logged on the tuned pack.
- **Release gates** (all must pass on the same build):
  - **SC-2a:** T-DIAG (QA-02).
  - **SC-2b proxy:** blind AI review (REL-04).
  - **SC-3:** QA-03.
  - **SC-5:** QA-10 to QA-16, QA-19, and REL-02.
  - **SC-4 proxy:** for each scenario, a fresh AI session given **only** that scenario's debrief text restates the failing component and the mechanism correctly (3 of 3). Prompts and answers are saved under `reviews/debrief/<pack-version>/`.
  - **SC-1 bound:** the round time limit, plus the briefing and debrief, keeps a round under about 17 minutes, and the median self-play round is 20 minutes or less.
- **Recorded as not validated (accepted gaps):**
  - SC-1 for genuinely new players.
  - SC-2c (other players' first action).
  - SC-4 with real players.
- A sign-off note in `reviews/signoff-<pack-version>.md` lists each criterion as verified, proxy-verified, or not validated, with the measured values. A failing gate is reported with its measured value; it is not waived.

**Dependencies:** REL-05, REL-04, QA-10, QA-19

**TDD traceability:** §2.6 (all success criteria), §15.7; decision D-19

---

#### REL-07 · Release candidate and offline readiness

**Type:** Release

**Description / value:** A tagged release candidate that can be prepared in advance and played offline.

**Acceptance criteria**
- A tagged release candidate with:
  - every CI stage green;
  - a passing QA-19 smoke run;
  - REL-02 passed;
  - REL-06 sign-off recorded;
  - the content sign-off recorded (SEC-06, D-03).
- On your Colima laptop, `make build` while connected, followed by `make up` with the network disconnected, starts a playable game (NFR-1).
- **Release notes list:**
  - The build and pack versions.
  - The tier-1 hosts and the untested ones (D-01).
  - Known limitations, including the accepted `ui` residual risk (§5.1) and the success-criteria validation gaps (D-19).
  - The out-of-scope stretch goals.

**Dependencies:** REL-06, REL-02, QA-18, QA-19, SEC-03, SEC-06, SEC-07

**TDD traceability:** §4.1, §5.1, §16.1, NFR-1; decisions D-01, D-03, D-19

---

## 5. Traceability matrix

### 5.1 Requirements

| TDD item | Ticket(s) |
|---|---|
| FR-1 Three rounds, random order, each once | CTL-03, UI-14, QA-09 |
| FR-2 Briefing → active (12-min timer) → debrief | CTL-04, CTL-06, UI-03, UI-13 |
| FR-3 Model of `api` / `jobs` / `worker` / `ledger` with traffic | SIM-03, SIM-04, SIM-05, SIM-06, SIM-07 |
| FR-4 Five metric families per applicable service | SIM-09, UI-06 |
| FR-5 Single symptom-only page alert starts the timer | CTL-09, UI-04 |
| FR-6 Impact feed from simulated bad events | SIM-08, CTL-10, CTL-11, UI-09, QA-06 |
| FR-7 Action catalog and 12-point budget | SCN-08, SCN-09, SCN-10, CTL-12, CTL-13, UI-10 |
| FR-8 `restart_all` restores but scores worse | SCN-08, CTL-15, QA-03 |
| FR-9 Declaration accepted only after W of stability | CTL-06, CTL-08, CTL-14, UI-12, QA-05 |
| FR-10 Debrief contents | CTL-16, UI-13 |
| FR-11 Pause, restart round, reset session | CTL-03, CTL-04, UI-11 |
| NFR-1 No runtime internet | ENV-02, SEC-01, REL-07 |
| NFR-2 1 Hz, < 200 ms action ack, < 20 ms step | SIM-01, CTL-12, QA-17 |
| NFR-3 ≤ 1 CPU, ≤ 600 MB | ENV-04, QA-17 |
| NFR-4 Warm ≤ 60 s, cold ≤ 5 min | ENV-04, ENV-09, QA-17 |
| NFR-5 Deterministic per seed | SIM-01, SIM-02, CTL-11, QA-17 |
| NFR-6 Browser and resolution support | UI-01, QA-09 |
| SR-1 Project scoping and labels | ENV-03, ENV-06, ENV-10, QA-10 |
| SR-2 Internal-only network for game logic | ENV-03, ENV-07, ENV-08, CTL-02, QA-12, QA-13 |
| SR-3 No privileged settings or socket | ENV-02, ENV-03, ENV-06, QA-11 |
| SR-4 No host mounts; read-only filesystems | ENV-02, ENV-03, ENV-07 |
| SR-5 No credentials | ENV-03, ENV-06, ENV-07, QA-15 |
| SR-6 Fault injection only inside `sim` | SCN-03, SCN-08, SEC-02, QA-13 |
| SR-7 Closed target enumerations | CTL-12, UI-10, QA-14 |
| SR-8 Only `127.0.0.1:8080` published | ENV-03, ENV-05, ENV-06, ENV-13, QA-10, SEC-04, REL-02 |
| SR-9 Isolation checks with fail-closed behavior | ENV-06, ENV-07, ENV-08, ENV-09, CTL-20, QA-15 |
| SR-10 UI and docs state simulation-only | UI-02, UI-04, UI-10, SEC-06, SEC-07, QA-09 |
| AR-1 WCAG 2.2 AA, keyboard | UI-17, QA-09 |
| AR-2 No color-only state; CVD-safe palette | UI-05, UI-06, UI-17 |
| AR-3 Text summaries, table view, live regions | UI-04, UI-07, UI-09, UI-17 |
| AR-4 Pause, reduced motion, 200% text; untimed practice mode (D-02) | UI-11, UI-17, CTL-21, UI-18 |
| AR-5 Tooltips; one-minute briefing | UI-03, UI-16 |
| OR-1 `make up` / `make down` scoping | ENV-09, ENV-10, QA-10 |
| OR-2 status / logs / test, local output | ENV-11 |
| OR-3 Repeatable up and down | ENV-09, ENV-10, QA-10 |
| OR-4 Version in footer | REL-01, UI-01 |
| SC-1 Session timing | REL-03, REL-05, REL-06 (self-play bound; new-player timing is an accepted gap, D-19) |
| SC-2 Diagnosable and distinct | QA-02 (a); REL-04 (b, AI proxy); (c) is an accepted gap, D-19 |
| SC-3 Targeted beats restart-all | CTL-15, QA-03 |
| SC-4 Players can explain the root cause | REL-06 (AI proxy on the debrief text), SEC-06 (debrief copy); real-player check is an accepted gap, D-19 |
| SC-5 One-command lifecycle and isolation | ENV-09, ENV-10, ENV-13, QA-10, QA-11 to QA-16, QA-19, REL-02 |

### 5.2 Design elements by section

| TDD section / design element | Ticket(s) |
|---|---|
| §1 MVP boundary; stretch goals excluded | Scope note (§2 of this doc); REL-07 release notes |
| §3.1 Components; single-process simulation design choice | ENV-01, SIM-01–SIM-10, CTL-01 |
| §3.2 Protocols, hard-coded peers, `sim` server-only, trust boundary | ENV-05, SIM-10, CTL-02, CTL-18, SEC-02, QA-07 |
| §3.3 Per-second data flow | SIM-01, SIM-10, CTL-07, CTL-18 |
| §3.4 / §3.5 Architecture and round sequence | ENV-03, CTL-05, QA-08, QA-09 |
| §4.1 Host prerequisites, offline `make build` | ENV-09, ENV-11, ENV-13, REL-02, REL-07, SEC-07 |
| §4.2 Dev mode | ENV-12 |
| §4.3 Topology and security settings | ENV-02, ENV-03 |
| §4.4 Resource limits | ENV-04, QA-17 |
| §4.5 Health checks and startup order | ENV-04, CTL-01, SIM-10 |
| §4.6 Persistence and reset behavior | CTL-03, CTL-17, ENV-10, UI-11 |
| §4.7 User-facing commands | ENV-09, ENV-10, ENV-11, SEC-07 |
| §5.1 Environment isolation; `ui` residual risk | ENV-03, ENV-05, QA-14, REL-07 |
| §5.2 Fault injection confined; banned APIs | SCN-03, SCN-08, SEC-02 |
| §5.3 Action and API confinement; test-mode gating | CTL-12, CTL-19, ENV-11, QA-14, QA-16 |
| §5.4 UI and documentation safeguards | UI-02, UI-04, UI-10, SEC-06, SEC-07 |
| §5.5 Static, runtime, and host isolation checks | ENV-06, ENV-07, ENV-08 |
| §5.6 Safe failure behavior | ENV-09, CTL-20, UI-15, QA-15 |
| §6.1 Lifecycle states and `LOCKED` | CTL-04, UI-11, UI-15 |
| §6.2 Clocks, pre-roll, W | SIM-01, CTL-05, CTL-06 |
| §6.3 Event ordering | SIM-01, CTL-07 |
| §6.4 Recovery determination, nudge, holds | CTL-06, CTL-14, SCN-03, UI-05, UI-12 |
| §6.5 Edge cases | CTL-06, CTL-12, CTL-13, CTL-18, CTL-20, QA-08 |
| §6.6 Briefing rules copy | UI-03, SEC-06 |
| §7.1 Baseline world | SCN-02 |
| §7.2 Signature table | SCN-04, SCN-05, SCN-06, CTL-09, QA-02 |
| §7.3 `pool_leak` | SCN-04 |
| §7.4 `poison_message` | SCN-05 |
| §7.5 `retry_storm` | SCN-06 |
| §8.1 Engine, RNG substreams, pacing | SIM-01, SIM-02 |
| §8.2 Traffic generator | SIM-03 |
| §8.3 Request-chain behavior | SIM-04, SIM-05, SIM-06, SIM-07 |
| §8.4 Bad customer events | SIM-08 |
| §8.5 Metric cadence and 15-min buffer | SIM-09, CTL-18 |
| §8.6 Repeatability without player-facing replay | SIM-02, SCN-03, QA-02 |
| §8.7 Defaults and tuning | SCN-01, CTL-15, REL-05 |
| §9.1 Metric definitions | SIM-09, UI-06 |
| §9.2 Per-service presentation, status chips | SIM-09, UI-05, UI-06 |
| §9.3 Health checks | CTL-08, UI-05 |
| §9.4 Recent changes and Config | SCN-02, SCN-07, UI-08 |
| §9.5 Dashboard interactions | UI-06, UI-07, UI-16 |
| §9.6 Alerts | CTL-09, UI-04 |
| §9.7 Spoiler avoidance | CTL-18, SEC-06, QA-07 |
| §9.8 Impact feed and counters | CTL-10, CTL-11, UI-09, SEC-05, SEC-06, QA-06 |
| §9.9 Essential screens | UI-02, UI-03, UI-04, UI-10, UI-13, UI-14 |
| §9.10 Accessible status cues | UI-04, UI-05, UI-06, UI-17 |
| §10.1 Action catalog | SCN-08, SCN-09, SCN-10, CTL-12, UI-10 |
| §10.2 Effect by scenario | SCN-04, SCN-05, SCN-06, CTL-13, QA-04 |
| §10.3 Budget and validation | CTL-12, CTL-13 |
| §10.4 Broad-versus-targeted levers | CTL-15, QA-03 |
| §11.1 Definitions (TTD, TTR, B, W) | CTL-06, CTL-10, CTL-16 |
| §11.2 / §11.3 Formula and outcomes | CTL-15 |
| §11.4 Worked examples | CTL-15 (unit), QA-03 |
| §11.5 Debrief contents | CTL-16, UI-13, SEC-06 |
| §12.1 Entities and lifetimes | CTL-03, CTL-07, CTL-13, CTL-17, SCN-01 |
| §12.2 API endpoints and internal messages | CTL-01, CTL-03, CTL-04, CTL-12, CTL-14, CTL-16, CTL-18, CTL-19, SIM-10 |
| §12.3 Example payloads | CTL-12, CTL-14, CTL-16, CTL-18 |
| §12.4 Error codes and idempotency | CTL-01, CTL-12 |
| §13 Failure handling and reset paths | CTL-20, UI-15, ENV-09, ENV-10, CTL-17, QA-08 |
| §14 Security, privacy, content | SEC-01, SEC-03, SEC-04, SEC-05, SEC-06, ENV-05 |
| §15.1 Deterministic test controls | CTL-19, ENV-11, QA-01 |
| §15.2 Unit-test coverage | Embedded in SIM-*, CTL-*, ENV-07, SEC-06 (planning assumption 2) |
| §15.3 Integration tests | QA-08 |
| §15.4 End-to-end tests | QA-09, QA-19 |
| §15.5 Scenario tests | QA-02 to QA-07 |
| §15.6 Isolation and environment tests | QA-10 to QA-16 |
| §15.7 Playtests | REL-03, REL-05, REL-06, ENV-14 |
| §16.1 Implementation sequence (Phase 0 first) | Dependency ordering (ENV-* before game logic); QA-18 |
| §16.2 Risks and mitigations | REL-02 (host differences), REL-05 (tuning), QA-03 (restart temptation), QA-07 (leaks), UI-11 (pause), §2 of this doc (scope) |
| §16.3 Extension points (seed, event log, `effect_class`) | SIM-02, CTL-07, CTL-13, CTL-17 |
| §17 Open questions | Decided: D-01 to D-04 (§6) |
| §17 Assumptions (desktop, single player, English, versioned defaults, single-process simulation) | UI-01, ENV-01, SCN-01, REL-01 |

### 5.3 Decisions

| Decision | Ticket(s) |
|---|---|
| D-01 Colima laptop plus Linux CI, Docker ≥ 28, local-engine guard, multi-arch | ENV-02, ENV-09, ENV-13, QA-18, REL-02, REL-07, SEC-07 |
| D-02 Practice (untimed) mode | CTL-03, CTL-04, CTL-16, CTL-17, CTL-21, UI-14, UI-18, QA-09, SEC-06 |
| D-03 Content sign-off and name-clash check | SEC-05, SEC-06, REL-07 |
| D-04 `make export-results` | ENV-14, REL-03, SEC-07 |
| D-05 Controller-stepped pre-roll and no-alert bound | SIM-01, SIM-10, CTL-04, CTL-05, QA-17 |
| D-06 Dev mode without a second port | ENV-06, ENV-12, SEC-07 |
| D-07 Backlog slope rule | CTL-08 |
| D-08 First-visible-signal band | CTL-16 |
| D-09 Feed history from pre-roll | CTL-11, UI-09 |
| D-10 Test-only relapse injection | SIM-10, CTL-19, QA-05 |
| D-11 Two end-to-end suites | QA-09, QA-18, QA-19, REL-07 |
| D-12 Wall-clock phase timestamps | CTL-03, CTL-17, REL-03 |
| D-13 `session_complete` and session completion | CTL-01, CTL-03, UI-14 |
| D-14 "Confirm all" stored in `localStorage` | UI-10 |
| D-15 Okabe–Ito palette | UI-06, UI-17 |
| D-16 No human testers; self-play and AI-proxy reviews | REL-03, REL-04, REL-05, REL-06 |
| D-17 CI and Colima packet capture | QA-13, QA-18, REL-02 |
| D-18 Controller-owned feed RNG via SHA-256 | SIM-02, CTL-11, QA-17 |
| D-19 Solo project and accepted validation gaps | REL-02 to REL-07, SEC-06, ENV-14, CTL-21 |
| D-20 `ledger` pool wait counts from arrival | SIM-05, SCN-04, SCN-06 |
| D-21 Pool use is a mean; `ledger` throughput counts served work | SIM-09, SCN-04, SCN-06 |
| D-22 Same-second alert ties; either `api` rule may page in `pool_leak` and `retry_storm` | CTL-09, SCN-04, SCN-06, QA-02 |
| D-23 Signature cells the model cannot meet as written | SCN-04, SCN-06, QA-02 |
| D-24 `ledger.db` has 13 connections | SIM-05, SCN-04, SCN-06, SCN-09, REL-05, REL-06 |
| D-25 Pack tuning travels in the heartbeat | SIM-10, CTL-02, CTL-05 |

---

## 6. Decisions on the previously open questions

All 18 questions from the previous version are now **decided**, and v3 adds D-19 for the solo-project correction (revising D-01, D-03, D-04, and D-16). The product owner delegated the choices to the recommendations below, with one fixed input: **Colima must be supported**. Each decision's effects are already written into the tickets listed. Decisions that change TDD text are also recorded in the TDD's decision addendum (§18).

| ID | Was | Decision | Rationale | Tickets |
|---|---|---|---|---|
| **D-01** | UQ-01: host platforms (revised in v3) | **Tier 1, the only verified hosts:**<br>• **Colima on your laptop** (Docker runtime, with the Compose ≥ v2.20 and buildx CLI plugins).<br>• Linux with Docker Engine ≥ 28.0 in CI (amd64 and arm64).<br>**Untested:** Docker Desktop (macOS or Windows) and Docker inside WSL2. Preflight warns, and they run only if every isolation check passes.<br>**Refused:** Podman and any remote Docker engine.<br>**Also:**<br>• The minimum Docker Engine version is **28.0**.<br>• Images are multi-arch and pinned by index digest.<br>• Colima VM: 2 CPUs and 4 GiB recommended (warn only). | Colima is required, and CI needs Linux. With one tester, unverified platforms are labeled honestly instead of promised. Docker documents that before 28.0, hosts on the same network segment could reach ports published to localhost, which undermines SR-8. Colima on Apple Silicon runs an arm64 VM and needs the Compose and buildx plugins installed separately. | ENV-02, ENV-09, ENV-13, QA-18, REL-02, REL-07, SEC-07 |
| **D-02** | UQ-02: relaxed or untimed mode | **Add a small "Practice (untimed)" session mode to the MVP:**<br>• Elapsed time instead of a countdown, with no timeout.<br>• An **End round** button.<br>• Speed is not scored (maximum 700).<br>• Standard mode stays the default and is the only mode used for playtest measurement. | WCAG 2.2 SC 2.2.1 (Timing Adjustable, Level A) applies under the TDD's AA target. A game timer may qualify for the "essential" exception, but a practice mode removes the doubt at low cost and helps nervous first-timers. This is a deliberate, labeled scope addition. | **CTL-21**, **UI-18**, CTL-03, CTL-04, CTL-16, CTL-17, UI-14, QA-09, SEC-06 |
| **D-03** | UQ-03: content sign-off (revised in v3) | **You are the sole approver.** Before approving: the CI content lint passes; a fresh AI session with no project context reviews all copy against the checklist; and you re-read the copy on a different day from writing it. Record everything under `reviews/content/`. Before publishing or sharing, run a name-clash search on "Larkspur Goods" and rename through the brand constant if needed. | There is no second person, so the second reader is a context-free AI session, plus distance in time from the writing. A fictional name can still collide with a real business. | SEC-05, SEC-06, REL-07 |
| **D-04** | UQ-04: results export | **No automatic collection, ever.** `make export-results` copies `results.jsonl` with `docker compose cp` into the current folder, for analyzing your own self-play. | Self-play evidence (REL-03) needs the results file. A command run at the keyboard keeps the "local only" promise and adds no mounts. | ENV-14, REL-03, SEC-07 |
| **D-05** | UQ-05: who detects the page during pre-roll | **The controller is the only component that evaluates alerts and health.** During `PREPARING`, the controller drives `sim` with `cmd.step {n: 10}` per simulated second, as fast as possible (this replaces the 30× wall-clock pacing). It stops at the second the page fires; that second is T0, and `sim` stays paused. `evt.prealert_ready` is removed. `cmd.step` is accepted in player mode only during pre-roll. **Bound:** if no page has fired by 900 s after onset, the round aborts with `preroll_no_alert`, is retried once with a new seed, and otherwise shows the game-problem notice. | One alert implementation, an exact T0, determinism without a wall-clock dependency, and a faster briefing. The bound turns a tuning bug into a visible, recoverable error instead of a hang. | CTL-05, CTL-04, SIM-01, SIM-10, QA-17 |
| **D-06** | UQ-06: dev port versus the single-port rule | **No second port.** In dev mode the `ui` service runs the Vite dev server (with hot reload) in place of nginx, on the same single `127.0.0.1` port, proxying to `controller:8000` over the internal network. The static checker's dev profile relaxes only the three read-only source mounts. Running Vite on the host is unsupported. | Publishing the controller would force it onto a bridge network with egress, breaking SR-2 even in dev. This option keeps the safety rules identical across modes. | ENV-06, ENV-12, SEC-07 |
| **D-07** | UQ-07: "not increasing over 30 s" | The **least-squares slope** of `jobs` depth over the trailing 30 one-second samples must be ≤ **+0.5 messages/s** *(default)*, alongside depth < 100. | It tolerates arrival noise, passes while a backlog drains, and fails clearly during the poison growth of about +10/s. | CTL-08 |
| **D-08** | UQ-08: baseline band for the first visible signal | Each scenario declares one leading signal and direction:<br>• `pool_leak`: pool in-use, upward.<br>• `poison_message`: `worker` completions, downward.<br>• `retry_storm`: `ledger` retry share, upward.<br>Band = mean ± max(3σ, floor) over the 300 s before onset. Floors: 1 connection, 2 jobs/s, 5 percentage points. The signal counts as visible at the start of the first run of ≥ 10 s outside the band. | It is simple to explain in the debrief, robust to noise, and kept in the pack so it can be tuned. | CTL-16 |
| **D-09** | UQ-09: feed during pre-roll | Generate the feed and counters throughout pre-roll in simulation time. Pre-alert items are shown under a "Before the alert" divider and are not announced. Neutral chatter appears only in that baseline history. Scored impact still starts at T0. | The console opens with realistic context, and the rule that the feed tracks real errors holds through the whole history. | CTL-11, UI-09 |
| **D-10** | UQ-10: relapse hook | Add the test-mode-only `POST /api/test/inject {kind: "ledger_slowdown", duration_s ∈ {10, 20}}`, which multiplies `ledger` hold times by 8 for the duration. It returns 404 in player mode, and `sim` rejects it outside test mode. | The smallest enumerated hook that proves `healthy_since` resets. Because it is enumerated and test-only, there is no new attack surface for players. | CTL-19, SIM-10, QA-05, QA-16 |
| **D-11** | UQ-11: end-to-end run mode | **Both, with different jobs:**<br>• **Per commit:** a full three-round end-to-end suite on the test profile (real Compose stack, isolation on, manual clock).<br>• **Nightly and pre-release:** a real-time smoke test on `make up` that plays one round using the T-DIAG classifier. | Fast feedback on every change, plus proof that the true player configuration works without test controls. | QA-09, **QA-19**, QA-18, REL-07 |
| **D-12** | UQ-12: phase timing | The controller records UTC wall-clock times per round: `briefing_opened_at`, `on_call_at`, `debrief_opened_at`, `debrief_closed_at`, and paused seconds. | It measures SC-1 objectively, contains no personal data, and needs no stopwatch. | CTL-17, CTL-03, REL-03 |
| **D-13** | UQ-13: after the third round | `POST /api/sessions/current/rounds` returns `409 session_complete`. The new idempotent `POST /api/sessions/current/complete` (called when the summary opens) sets the session status to `complete`. | Explicit end-of-session state, and the point where the final `debrief_closed_at` is recorded. | CTL-01, CTL-03, UI-14 |
| **D-14** | UQ-14: "Confirm all actions" persistence | Stored per browser in `localStorage` (guarded with try/catch), default off. It is never sent to the server. | It is a personal UI preference with no effect on gameplay or scoring. | UI-10 |
| **D-15** | UQ-15: chart palette | **Okabe–Ito** categorical palette as UI tokens. Status uses blue/orange plus icon and text. Non-text contrast ≥ 3:1 (WCAG 1.4.11). | A widely used palette that is safe for color-vision deficiency, with no dependency on an unidentified design system. | UI-06, UI-17 |
| **D-16** | UQ-16: playtest people (revised in v3) | **No human playtesters or reviewers.**<br>• Self-play replaces playtests (REL-03, REL-05, REL-06).<br>• Three fresh, context-free AI sessions replace the blind expert review (REL-04).<br>• A fresh AI session reading only the debrief text replaces the playtester-explanation check (REL-06).<br>All prompts and answers are saved in `reviews/`. | It keeps each check achievable alone. The AI sessions are proxies, not the target players, and are labeled that way. | REL-03, REL-04, REL-05, REL-06 |
| **D-17** | UQ-17: CI packet capture | Run QA-13 on an ephemeral Linux VM runner with passwordless sudo, with `tcpdump` on the runner host outside the Compose project and the pcap kept as an artifact. Game containers never get added capabilities. On Colima, capture inside the VM with `colima ssh -- sudo tcpdump -i any`. | Empirical proof without weakening the game environment. | QA-13, QA-18, REL-02 |
| **D-18** | UQ-18: feed RNG ownership | The controller derives its own `feed` generator from the round seed with SHA-256 (`sha256(f"{seed}:feed")`). `sim` keeps only the `traffic`, `latency`, and `fault` streams. Python's built-in `hash()` is never used for seeding. | Deterministic, independent of the link, and no cross-process RNG sharing. | SIM-02, CTL-11, QA-17 |
| **D-19** | New in v3: who builds and tests | **Solo project.** You are the only person who develops, tests, reviews, and approves.<br>**Consequences:**<br>• Every ticket has one owner (you).<br>• Human review steps become checklists, CI gates, and fresh-session AI reviews (D-03, D-16).<br>• Success criteria that depend on other players cannot be validated before release: **SC-1 for new players, SC-2c, and SC-4 with real players**. They are replaced by proxies and recorded as **accepted validation gaps** in the sign-off and release notes.<br>• If other people ever play the game, the original human playtest protocol (TDD §15.7, v1) can be run as optional validation after release. | It makes every release gate achievable alone, without implying that self-play or AI review proves how new players will do. | REL-02 to REL-07, SEC-06, ENV-14, CTL-21 |
| **D-20** | New after v3: when the `ledger` pool wait starts | A request fails with `pool_timeout` if it has not got a `ledger.db` connection within 2000 ms of arriving; time in `ledger.requests` counts. | The TDD left the start of the clock open, and `pool_leak` (requests wait 2 s, then `pool_timeout`) needs it to start at arrival. A probe of `retry_storm` under this rule still shows a self-sustaining storm: queue at about 220–300, about 105 rps of wasted work, retry share about 80%. | SIM-05, SCN-04, SCN-06 |
| **D-21** | New after v3: what `pool_in_use` and `ledger` throughput measure | `pool_in_use` is the mean over the second (time-weighted for `ledger.db`), not the maximum. `ledger` throughput counts requests that got a connection, including wasted work; `queue_full` and `pool_timeout` refusals count only toward error rate. | With the maximum, `ledger.db` sat near 7/10 at baseline and pinned at 10 a minute after a leak began, hiding `pool_leak`'s step climb; the TDD's baseline figures (about 4; normal 2–4) are means. Counting refusals would show `retry_storm` at 170–210 rps instead of about 100. | SIM-09, SCN-04, SCN-06 |
| **D-22** | New after v3: `pool_leak` and `retry_storm` start both `api` alert conditions within a second of each other | Same-second ties page in §9.6 table order. Either `api` rule may page in those two scenarios; the signature's page cell lists both. Thresholds stay at the TDD defaults. | With a 1 s client timeout, every `api` request slower than 1000 ms is a failed one, so the latency and error conditions coincide. Thresholds from 600 to 1000 ms were measured over 130–150 seeds and none gave each scenario its own page reliably. The other §7.2 cells still separate the scenarios. | CTL-09, SCN-04, SCN-06, QA-02 |
| **D-23** | New after v3: signature cells the model cannot meet as written | At T0+60 s `ledger` throughput is ≤ 50 rps (below normal, reaching 0 only when every connection has leaked); the retry share ≤ 35% cell is dropped. | Once requests time out, two of every three `ledger` requests are `backoff` retries (retry share 0.6–0.75). Throughput level (≤ 50 versus ≥ 80 rps) separates `pool_leak` from `retry_storm`. In `retry_storm` the `api` error cell is ≥ 60% (about 75% measured), not ≥ 90%: orders, a quarter of `api` traffic, still get their 202. Its `worker` cell checks completions (≤ 6 jobs/s) and `jobs` depth, since some writes get through and a 10 s window can hold no `worker` errors. | SCN-04, SCN-06, QA-02 |
| **D-24** | New after v3: `ledger` capacity margin | `ledger.db` has 13 connections (capacity about 130 rps, baseline about 32%). The pack sets it; tests pin the measured behaviour. | With 10, the post-fix load (3 attempts per timed-out read under `backoff`, plus `worker` draining its backlog at full speed) exceeded capacity, so `backoff` and `recycle_pool` usually failed to recover. With 13: the storm sustains in 30 of 30 seeds, `backoff` drains it in 5–24 s, the targeted `pool_leak` fix holds in every seed, and recycle alone recovers in about 5 of 6. At 14 or 15 the storm dissolves by itself. `pool_leak` pages a median of about 400 s after onset; revisit in REL-05/REL-06. | SIM-05, SCN-04, SCN-06, SCN-09, REL-05, REL-06 |
| **D-25** | New after v3: how the controller gets the pack's tuning | `evt.heartbeat` carries `pack_version` and the pack's `controller` section. | The controller then keeps no copy of the pack, so `sim` and the controller can't disagree. Until a heartbeat has arrived, preparing a round returns `503 sim_unavailable`. | SIM-10, CTL-02, CTL-05 |

### Remaining open items

None that block implementation. One delivery action remains for you: record the content sign-off (D-03) before tagging a release.

---

## 7. Completeness check

- **Coverage.** Every requirement (FR-1–FR-11, NFR-1–NFR-6, SR-1–SR-10, AR-1–AR-5, OR-1–OR-4, SC-1–SC-5), every TDD design section from §1 through §17, and every decision D-01 to D-19 maps to at least one ticket (§5). The stretch goals remain intentionally unticketed. Their MVP extension points are covered in SIM-02, CTL-07, CTL-13, and CTL-17.
- **Changes in v3 (solo project).** Ticket REL-02 through REL-07 are rewritten for self-play, AI-proxy reviews, and your Colima laptop. SEC-06, SEC-07, ENV-09, ENV-11, ENV-13, ENV-14, CTL-21, and REL-01 are adjusted. D-01, D-03, D-04, and D-16 are revised, and D-19 is added. The ticket count is unchanged at 106. No ticket now needs a second person.
- **Consistency.** The TDD is updated to match: the audience, §2.6, §4.1, §5.4, §14, §15.7, §16, and the decision addendum (§18).
- **Dependencies.** Rechecked after the edits. Every referenced ticket exists, and there are no cycles.
- **Readiness.** Every ticket has specific, testable acceptance criteria, and implementation is not blocked anywhere.
- **Gaps, stated plainly.** **SC-1 (for new players), SC-2c, and SC-4 (with real players) cannot be validated** without other people. They have proxies (self-play timing bounds, and fresh-session AI reviews of the dashboards and debriefs), but a proxy is not proof of how new on-call engineers will experience the game. These gaps are recorded as accepted in the REL-06 sign-off and in the release notes rather than hidden.
