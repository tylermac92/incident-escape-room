"""Seeded random-number substreams (SIM-02, TDD §8.1, §8.6, NFR-5, D-18).

This module is sim's only source of randomness. Each name gets its own random.Random,
so adding draws in one area never shifts another. The controller derives its `feed`
stream the same way.
"""

import hashlib
import random

NAMES = ("traffic", "latency", "fault")


def stream(seed: int, name: str) -> random.Random:
    # sha256, never hash(): str hashes are salted per process.
    return random.Random(int.from_bytes(hashlib.sha256(f"{seed}:{name}".encode()).digest()[:8]))


def streams(seed: int) -> dict[str, random.Random]:
    return {name: stream(seed, name) for name in NAMES}
