"""Customer-impact feed (CTL-11, TDD §9.8, D-09, D-18).

Every `interval_s` of sim time, the feed looks at the trailing 10 s of bad-event counts and may emit
one item about the worst category, with probability min(1, count/50). Each complaint carries the
evidence it was built from. Recovery and neutral chatter items carry no evidence. Its random stream
is seeded from the round seed alone, so the same seed and event series give the same feed.
"""

import hashlib
import json
import random
from collections import deque
from pathlib import Path

FEED_DIR = Path("/app/feed_templates")  # baked into the image (Dockerfile)
CATEGORIES = ("read_failed", "read_slow", "receipt_unavailable", "order_rejected", "order_delayed", "order_lost")
WINDOW_S = 10
FULL_RATE_COUNT = 50  # emit probability min(1, count / 50)
ESCALATE_AFTER_MS = 180_000
STALE_AFTER_MS = 10_000
RECOVERY_QUIET_MS = 30_000
CHATTER_EVERY_MS, CHATTER_PROBABILITY = 60_000, 0.25


def load_content(directory: Path = FEED_DIR) -> dict:
    """Templates and fictional lists. Raises if a file is missing or a category has no templates."""
    content = {name: json.loads((directory / f"{name}.json").read_text()) for name in ("templates", "lists")}
    for kind in ("complaint", "escalation"):
        missing = set(CATEGORIES) - {c for c, texts in content["templates"][kind].items() if texts}
        if missing:
            raise ValueError(f"feed templates: {kind} has none for {sorted(missing)}")
    return content


def feed_rng(seed: int) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(f"{seed}:feed".encode()).digest()[:8], "big"))


class Feed:
    def __init__(self, seed: int, content: dict, config: dict):
        self.rng, self.content = feed_rng(seed), content
        self.interval_ms, self.min_count = config["interval_s"] * 1000, config["min_count"]
        self.window: deque = deque(maxlen=WINDOW_S)  # (t_ms, counts) per second
        self.last_bad: dict[str, int] = {}  # category -> latest second with a bad event
        self.bad_since: dict[str, int] = {}  # category -> start of its current bad spell
        self.items: list[dict] = []
        self.last_chatter_ms = -CHATTER_EVERY_MS
        self.recovered = True  # nothing to recover from until something has gone wrong

    def add(self, t_ms: int, counts: dict, checks_pass: bool, before_onset: bool, t0_ms: int | None) -> dict | None:
        """One second of counts. Returns the item emitted this second, if any."""
        self.window.append((t_ms, counts))
        for category in CATEGORIES:
            if counts.get(category, 0):
                if t_ms - self.last_bad.get(category, -STALE_AFTER_MS) >= STALE_AFTER_MS:
                    self.bad_since[category] = t_ms  # a new spell after 10 quiet seconds
                self.last_bad[category] = t_ms
                self.recovered = False
        if t_ms % self.interval_ms:
            return None
        totals = {c: sum(counts.get(c, 0) for _, counts in self.window) for c in CATEGORIES}
        category = max(CATEGORIES, key=lambda c: totals[c])  # ties: the fixed category order
        if totals[category] >= self.min_count:  # evidence gate: only then may a complaint be emitted
            item = self._complaint(t_ms, category, totals[category])
        else:
            item = self._recovery(t_ms, checks_pass) or self._chatter(t_ms, before_onset, any(totals.values()))
        if item:
            item |= {"id": f"f_{len(self.items) + 1:04d}", "t_ms": t_ms, "pre_alert": t0_ms is None or t_ms <= t0_ms}
            self.items.append(item)
        return item

    def _fill(self, text: str) -> tuple[str, dict]:
        lists = self.content["lists"]
        customer = {"name": self.rng.choice(lists["names"]), "city": self.rng.choice(lists["cities"])}
        return text.format(brand=lists["brand"], product=self.rng.choice(lists["products"])), customer

    def _complaint(self, t_ms: int, category: str, count: int) -> dict | None:
        if self.rng.random() >= min(1, count / FULL_RATE_COUNT):
            return None
        if t_ms - self.last_bad[category] >= STALE_AFTER_MS:  # staleness cutoff
            return None
        kind = "escalation" if t_ms - self.bad_since[category] > ESCALATE_AFTER_MS else "complaint"
        text, customer = self._fill(self.rng.choice(self.content["templates"][kind][category]))
        evidence = {"category": category, "count": count,
                    "window_start_ms": self.window[0][0] - 1000, "window_end_ms": t_ms}
        return {"kind": kind, "category": category, "text": text, "customer": customer, "evidence": evidence}

    def _recovery(self, t_ms: int, checks_pass: bool) -> dict | None:
        quiet = all(t_ms - last >= RECOVERY_QUIET_MS for last in self.last_bad.values())
        if self.recovered or not (quiet and checks_pass):
            return None
        self.recovered = True  # one recovery item per bad spell
        text, customer = self._fill(self.rng.choice(self.content["templates"]["recovery"]))
        return {"kind": "recovery", "category": None, "text": text, "customer": customer, "evidence": None}

    def _chatter(self, t_ms: int, before_onset: bool, any_bad: bool) -> dict | None:
        """Quiet means healthy: only in the baseline, only with no bad event in the window."""
        if not before_onset or any_bad or t_ms - self.last_chatter_ms < CHATTER_EVERY_MS:
            return None
        if self.rng.random() >= CHATTER_PROBABILITY:
            return None
        self.last_chatter_ms = t_ms
        text, customer = self._fill(self.rng.choice(self.content["templates"]["chatter"]))
        return {"kind": "chatter", "category": None, "text": text, "customer": customer, "evidence": None}
