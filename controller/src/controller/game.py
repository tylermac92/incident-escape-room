"""Sessions (CTL-03, TDD §4.6, §12.1, §12.2).

A session is three rounds, one per scenario, in a random order. It is mirrored to
/data/session.json on every change, so a controller restart keeps completed rounds. The round
order and scenario ids are never sent to the UI before a round's debrief (§9.7).
"""

import dataclasses
import json
import os
import random
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from controller.errors import ApiError

SCENARIO_IDS = ("pool_leak", "poison_message", "retry_storm")  # the closed set sim also enforces
SESSION_FILE = Path("/data/session.json")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


@dataclass
class Round:
    id: str
    session_id: str
    scenario_id: str
    seed: int
    attempt: int
    state: str = "PREPARING"
    t_onset_ms: int | None = None
    t0_ms: int | None = None
    time_limit_s: int | None = None
    budget_total: int | None = None
    budget_remaining: int | None = None
    healthy_since_ms: int | None = None
    outcome: str | None = None
    abort_reason: str | None = None
    # Wall-clock phase times, UTC (D-12).
    briefing_opened_at: str | None = None
    on_call_at: str | None = None
    debrief_opened_at: str | None = None
    debrief_closed_at: str | None = None
    paused_s: float = 0.0

    def summary(self) -> dict:
        """What the UI may see in a session summary: the scenario only once it is debriefed."""
        out = {"id": self.id, "attempt": self.attempt, "state": self.state,
               "outcome": self.outcome, "abort_reason": self.abort_reason}
        if self.state == "DEBRIEF":
            out["scenario_id"] = self.scenario_id
        return out


@dataclass
class Session:
    id: str
    created_at: str
    mode: str
    round_order: list[str]
    status: str = "in_progress"  # in_progress, complete, abandoned (D-13)
    rounds: list[Round] = field(default_factory=list)  # every attempt, in order
    current_index: int = 0

    @property
    def current_round(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None

    def debriefed(self) -> int:
        return len({r.scenario_id for r in self.rounds if r.state == "DEBRIEF"})

    def summary(self) -> dict:
        current = self.current_round
        return {"id": self.id, "created_at": self.created_at, "mode": self.mode, "status": self.status,
                "rounds_total": len(self.round_order), "rounds_debriefed": self.debriefed(),
                "current_round": current.summary() if current else None,
                "rounds": [r.summary() for r in self.rounds]}


class Game:
    """The controller's one session, and the file that mirrors it."""

    def __init__(self, path: Path = SESSION_FILE):
        self.path = path
        self.session: Session | None = None

    def save(self) -> None:
        if self.session is None:
            return
        tmp = self.path.with_suffix(".tmp")
        try:  # write then rename, so a crash never leaves half a file
            tmp.write_text(json.dumps(dataclasses.asdict(self.session)))
            os.replace(tmp, self.path)
        except OSError as e:  # the game still works; only a controller restart would lose it (§13)
            print(f"controller: could not save {self.path}: {e}", flush=True)

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            rounds = [Round(**r) for r in data.pop("rounds")]
            self.session = Session(**data, rounds=rounds)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, KeyError) as e:  # unreadable: start without a session
            print(f"controller: ignoring unreadable {self.path}: {e!r}", flush=True)
            return

    def current(self) -> Session:
        if self.session is None:
            raise ApiError(404, "not_found", "There is no session yet.")
        return self.session

    def new_session(self, mode: str) -> Session:
        if self.session is not None and self.session.status == "in_progress":
            self.session.status = "abandoned"
        order = random.SystemRandom().sample(SCENARIO_IDS, len(SCENARIO_IDS))
        self.session = Session(new_id("s"), utc_now(), mode, order)
        self.save()
        return self.session

    def complete(self) -> Session:
        session = self.current()
        if session.status == "complete":
            return session  # idempotent
        if session.debriefed() < len(session.round_order):
            raise ApiError(409, "invalid_state", "The session still has rounds to play.")
        session.status = "complete"
        session.current_round.debrief_closed_at = utc_now()
        self.save()
        return session
