"""Host runtime preflight (ENV-13, TDD §4.1, D-01): supported runtime, versions, resources.

Standalone on purpose, like compose_policy: host/up.sh runs this file with `python -c`
in a network-less container, after engine_guard.sh has confirmed the engine is local.
Reads {"version": <docker version json>, "info": <docker info json>} on stdin.
Prints "runtime: ..." plus WARN/FAIL lines; exits 1 on any FAIL.
"""

import argparse
import json
import re
import sys

MIN_ENGINE = (28, 0)  # below this, other machines on the LAN may reach ports published to localhost
MIN_COMPOSE = (2, 20)  # for `up --wait`
MIN_CPUS = 2
MIN_MEMORY = 4 * 1024**3
COLIMA_PLUGIN_FIX = ("install docker-compose and docker-buildx, and register them with "
                     "cliPluginsExtraDirs in ~/.docker/config.json")


def version_tuple(text):
    """(major, minor) from strings like '29.10.0', 'v2.29.1', '2.20.0-desktop.1'; None if unparseable."""
    match = re.match(r"v?(\d+)\.(\d+)", text or "")
    return (int(match[1]), int(match[2])) if match else None


def detect(version, info, context, endpoint):
    """One of: podman, colima, docker-desktop, wsl2, linux-engine, other."""
    server = version.get("Server") or {}
    components = {c.get("Name") for c in server.get("Components") or []}
    if "Podman Engine" in components:
        return "podman"
    if context.startswith("colima") or "/.colima/" in endpoint:
        return "colima"
    if info.get("OperatingSystem") == "Docker Desktop" or context.startswith("desktop-"):
        return "docker-desktop"
    if "microsoft" in (info.get("KernelVersion") or "").lower():
        return "wsl2"
    if "Engine" in components and (version.get("Client") or {}).get("Os") == "linux":
        return "linux-engine"
    return "other"


NAMES = {"podman": "Podman", "colima": "Colima", "docker-desktop": "Docker Desktop",
         "wsl2": "Docker Engine in WSL2", "linux-engine": "Linux Docker Engine", "other": "unknown runtime"}


def evaluate(version, info, context, endpoint, compose, buildx):
    """Return (runtime line, warnings, failures)."""
    runtime = detect(version, info, context, endpoint)
    server = version.get("Server") or {}
    engine = server.get("Version") or "?"
    line = f"runtime: {NAMES[runtime]}, engine {engine}, {server.get('Arch') or '?'}"
    warnings, failures = [], []

    if runtime == "podman":
        return line, warnings, ["Podman is not supported; use Docker Engine (Linux) or Colima (macOS)."]
    if runtime in ("docker-desktop", "wsl2", "other"):
        warnings.append(f"untested runtime ({NAMES[runtime]}): continuing only if every isolation check passes.")

    if (version_tuple(engine) or (0, 0)) < MIN_ENGINE:
        failures.append(f"Docker Engine {engine} is too old; 28.0 or later is required "
                        "(older engines can expose localhost ports to the local network).")
    fix = f" On Colima: {COLIMA_PLUGIN_FIX}." if runtime == "colima" else ""
    if not compose:
        failures.append(f"the Docker Compose plugin is missing; v2.20 or later is required.{fix}")
    elif (version_tuple(compose) or (0, 0)) < MIN_COMPOSE:
        failures.append(f"Docker Compose {compose} is too old; v2.20 or later is required.{fix}")
    if not buildx:
        failures.append(f"the Docker buildx plugin is missing.{fix}")

    cpus, memory = info.get("NCPU") or 0, info.get("MemTotal") or 0
    if cpus < MIN_CPUS or memory < MIN_MEMORY:
        hint = " Try: colima start --cpu 2 --memory 4" if runtime == "colima" else ""
        warnings.append(f"the engine has {cpus} CPUs and {memory / 1024**3:.1f} GiB of memory; "
                        f"2 CPUs and 4 GiB are recommended.{hint}")
    return line, warnings, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for arg in ("--context", "--endpoint", "--compose", "--buildx"):
        parser.add_argument(arg, default="")
    args = parser.parse_args(argv)
    try:
        state = json.load(sys.stdin)
        line, warnings, failures = evaluate(state["version"], state["info"], args.context, args.endpoint,
                                            args.compose.strip(), args.buildx.strip())
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        line, warnings, failures = "runtime: unknown", [], [f"could not read docker version/info ({exc!r})"]
    print("\n".join([line] + [f"WARN {w}" for w in warnings] + [f"FAIL {f}" for f in failures]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
