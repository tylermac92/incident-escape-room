"""Host-side check, after `up`, that the running containers match the network policy (ENV-08, TDD §5.5).

Standalone on purpose, like compose_policy: `make verify-isolation` runs this file with
`python -c` in a network-less container. It reads {"networks": <docker network inspect>,
"containers": <docker inspect>} on stdin, prints a report, and exits 1 on any mismatch.
"""

import json
import sys

PROJECT = "incident-escape-room"
INTERNAL = f"{PROJECT}_escape_internal"
EDGE = f"{PROJECT}_escape_edge"
EXPECTED = {"sim": {INTERNAL}, "controller": {INTERNAL}, "ui": {EDGE, INTERNAL}}


def mismatches(networks, containers):
    """Return human-readable problems; empty means the running state matches."""
    found = []
    ids = {n.get("Name"): n.get("Id") for n in networks}
    internal = next((n for n in networks if n.get("Name") == INTERNAL), None)
    if internal is None:
        found.append(f"network {INTERNAL} does not exist")
    elif internal.get("Internal") is not True:
        found.append(f"network {INTERNAL} has Internal={internal.get('Internal')}, not true")

    seen = set()
    for c in containers:
        name = c.get("Name", "?").lstrip("/")
        service = ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service")
        if service not in EXPECTED:
            found.append(f"container {name} (service {service!r}) is not part of the policy")
            continue
        seen.add(service)
        attached = ((c.get("NetworkSettings") or {}).get("Networks")) or {}
        for net in sorted(set(attached) - EXPECTED[service]):
            found.append(f"container {name} is attached to {net}; {service} must not be")
        for net in sorted(EXPECTED[service] - set(attached)):
            found.append(f"container {name} is not attached to {net}")
        for net in sorted(set(attached) & EXPECTED[service]):
            # The same name could belong to a network outside this project; compare IDs.
            if attached[net].get("NetworkID") != ids.get(net):
                found.append(f"container {name} is attached to a {net} that is not the project's network")
    for service in sorted(set(EXPECTED) - seen):
        found.append(f"no running container for {service}")
    return found


def main():
    try:
        state = json.load(sys.stdin)
        found = mismatches(state["networks"], state["containers"])
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        found = [f"could not read docker inspect output ({exc!r})"]
    print("\n".join([f"FAIL {problem}" for problem in found]
                    + ["host isolation: " + (f"{len(found)} mismatch(es)" if found else "ok")]))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
