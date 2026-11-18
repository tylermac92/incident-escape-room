"""Static isolation policy over `docker compose config --format json` (ENV-06, TDD §5.5).

Standalone on purpose: `make check-compose` runs this file with `python -c` in a
network-less container, so it must not import anything outside the standard library.
Reads the rendered config on stdin, prints a report, and exits 1 on any violation.
"""

import argparse
import json
import re
import sys

PROJECT = "incident-escape-room"
LABEL = "com.incident-escape-room.managed"
ISOLATED_SERVICES = ("sim", "controller")
FORBIDDEN_OPTIONS = ("network_mode", "privileged", "cap_add", "devices", "pid", "ipc")
DEV_SOURCE_DIRS = ("ui", "controller", "sim")
ENV_ALLOWED = re.compile(r"ESCAPE_[A-Z0-9_]+|TZ")
UI_SERVICE = "ui"
# Flags allowed only in one profile: make up (player) can never enable dev or test mode.
MODE_FLAGS = {"ESCAPE_DEV": "dev", "ESCAPE_TEST_MODE": "test"}


def _labelled(resource):
    return (resource.get("labels") or {}).get(LABEL) == "true"


def violations(config, profile="player", root=""):
    """Return (rule, detail) pairs; empty means the config passes."""
    dev = profile == "dev"
    found = []
    services = config.get("services") or {}
    networks = config.get("networks") or {}
    volumes = config.get("volumes") or {}

    if config.get("name") != PROJECT:
        found.append(("label", f"project name is {config.get('name')!r}, not {PROJECT!r}"))

    # 1. sim and controller attach only to internal networks (no networks key means "default").
    for name in ISOLATED_SERVICES:
        for net in (services.get(name) or {}).get("networks") or {"default": None}:
            if not (networks.get(net) or {}).get("internal"):
                found.append(("internal-network", f"{name} uses network {net!r} without internal: true"))

    # 5. Every resource carries the project label.
    for kind, group in (("service", services), ("network", networks), ("volume", volumes)):
        for name, resource in group.items():
            if not _labelled(resource):
                found.append(("label", f"{kind} {name!r} lacks {LABEL}=true"))

    # Compose secrets and configs with `file:` are host bind mounts in disguise.
    for kind in ("secrets", "configs"):
        if config.get(kind):
            found.append(("host-mount", f"top-level {kind} are not allowed"))
    for name, vol in volumes.items():
        if (vol or {}).get("driver_opts") or (vol or {}).get("external"):
            found.append(("host-mount", f"volume {name!r} uses driver_opts or external"))

    allowed_sources = {f"{root.rstrip('/')}/{d}" for d in DEV_SOURCE_DIRS} if dev else set()
    ports = []
    for name, svc in services.items():
        # 2. No host namespaces, privileges, or devices.
        for option in FORBIDDEN_OPTIONS:
            if svc.get(option):
                found.append(("forbidden-option", f"{name} sets {option}"))
        for kind in ("secrets", "configs"):
            if svc.get(kind):
                found.append(("host-mount", f"{name} uses {kind}"))

        # 2. No Docker socket and no host paths, except dev's read-only source mounts.
        for mount in svc.get("volumes") or []:
            source, target, kind = mount.get("source", ""), mount.get("target", ""), mount.get("type")
            if "docker.sock" in source or "docker.sock" in target:
                found.append(("docker-socket", f"{name} mounts {source or target}"))
            elif kind == "volume" and source in volumes:
                continue
            elif kind == "bind" and source in allowed_sources and mount.get("read_only"):
                continue
            elif kind != "tmpfs":
                found.append(("host-mount", f"{name} mounts {kind} {source!r} at {target!r}"))

        # 4. Environment variables stay inside the allowlist; each mode flag only in its own profile.
        for var, value in (svc.get("environment") or {}).items():
            if var in MODE_FLAGS:
                if not (profile == MODE_FLAGS[var] and value == "1"):
                    found.append(("environment", f"{name} sets {var}={value} in the {profile} profile"))
            elif not ENV_ALLOWED.fullmatch(var):
                found.append(("environment", f"{name} sets {var}, outside the allowlist (ESCAPE_*, TZ)"))

        ports += [(name, p) for p in svc.get("ports") or []]

    # 3. Exactly one published port: ui, on 127.0.0.1, a single port number.
    if len(ports) != 1:
        found.append(("ports", f"{len(ports)} published ports; exactly one is allowed"))
    for name, p in ports:
        published = str(p.get("published", ""))
        if name != UI_SERVICE or p.get("host_ip") != "127.0.0.1" or not published.isdigit():
            found.append(("ports", f"{name} publishes {p.get('host_ip') or '0.0.0.0'}:{published or '?'}"
                                   f"->{p.get('target')}; only {UI_SERVICE} on 127.0.0.1 is allowed"))
    return found


def report(found, profile):
    lines = [f"FAIL {rule}: {detail}" for rule, detail in found]
    lines.append(f"compose policy ({profile}): " + (f"{len(found)} violation(s)" if found else "ok"))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=("player", "dev", "test"), default="player")
    parser.add_argument("--root", default="", help="host project directory (for dev source mounts)")
    args = parser.parse_args(argv)
    try:
        config = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"FAIL input: not valid compose JSON ({exc})\ncompose policy ({args.profile}): 1 violation(s)")
        return 1
    found = violations(config, args.profile, args.root)
    print(report(found, args.profile))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
