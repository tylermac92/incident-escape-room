"""Summary and privacy check for `make export-results` (ENV-14, TDD §14, D-04).

Standalone on purpose, like compose_policy: host/export-results.sh runs this file with
`python -c` in a network-less container. Reads results.jsonl on stdin, prints the number
of rounds and the field names, and exits 1 if the file is empty, malformed, or has a
player-identifying field anywhere.
"""

import json
import re
import sys

# shortcut: a denylist of identifying key names, because the results schema (CTL-17) does not
# exist yet; once it does, check every key against the schema's allowlist instead.
IDENTIFYING = re.compile(
    r"(^|_)(player|user|username|user_name|email|e_mail|ip|ip_address|"
    r"hostname|host_name|machine_id|device_id|account|login|real_name|full_name)($|_)"
)
FOLLOW_UP = {"round_id", "debrief_closed_at"}  # CTL-17 appends these once the debrief closes


def identifying_keys(value, path=""):
    """Paths of keys, at any depth, whose name identifies a person or machine."""
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            if IDENTIFYING.search(str(key).lower().replace("-", "_")):
                found.append(here)
            found += identifying_keys(inner, here)
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            found += identifying_keys(inner, f"{path}[{i}]")
    return found


def summarize(text):
    """Return (rounds, field names, problems)."""
    rounds, fields, problems = 0, set(), []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {number} is not valid JSON")
            continue
        if not isinstance(record, dict):
            problems.append(f"line {number} is not a JSON object")
            continue
        problems += [f"line {number} has a player-identifying field: {p}" for p in identifying_keys(record)]
        if set(record) != FOLLOW_UP:
            rounds += 1
            fields |= set(record)
    if rounds == 0 and not problems:
        problems.append("there are no completed rounds to export")
    return rounds, sorted(fields), problems


def main():
    rounds, fields, problems = summarize(sys.stdin.read())
    if problems:
        print("\n".join(f"FAIL {p}" for p in problems))
        return 1
    print(f"rounds: {rounds}")
    print(f"fields: {', '.join(fields)}")
    print("player-identifying fields: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
