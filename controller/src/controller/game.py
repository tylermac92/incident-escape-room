"""Sessions (CTL-03) and the round lifecycle (CTL-04): TDD §4.6, §6.1, §12.1, §12.2.

A session is three rounds, one per scenario, in a random order. It is mirrored to
/data/session.json on every change, so a controller restart keeps completed rounds. The round
order and scenario ids are never sent to the UI before a round's debrief (§9.7).

Every attempt at a scenario is its own Round; restarting aborts the attempt and adds a new one.
"""

import asyncio
import dataclasses
import json
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from controller.errors import ApiError
from controller.link import LinkDown

SCENARIO_IDS = ("pool_leak", "poison_message", "retry_storm")  # the closed set sim also enforces
SESSION_FILE = Path("/data/session.json")

# §6.1. BRIEFING -> ABORTED is not in the diagram; it is for game failures only (sim lost, isolation).
TRANSITIONS = {
    "PREPARING": {"BRIEFING", "ABORTED"},
    "BRIEFING": {"ACTIVE", "ABORTED"},
    "ACTIVE": {"PAUSED", "RESOLVED", "TIMED_OUT", "ENDED", "ABORTED"},
    "PAUSED": {"ACTIVE", "ENDED", "ABORTED"},
    "RESOLVED": {"DEBRIEF"},
    "TIMED_OUT": {"DEBRIEF"},
    "ENDED": {"DEBRIEF"},
}
LIVE = ("PREPARING", "BRIEFING", "ACTIVE", "PAUSED")  # a controller restart aborts these
ABORT_REASONS = ("sim_unavailable", "controller_restart", "isolation_check_failed", "preroll_no_alert", "player_restart")


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
    mode: str = "standard"
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

    def can(self, to: str) -> bool:
        if to == "ENDED" and self.mode != "practice" or to == "TIMED_OUT" and self.mode == "practice":
            return False  # D-02: only practice rounds end by choice, and they never time out
        return to in TRANSITIONS.get(self.state, ())

    def move(self, to: str, abort_reason: str | None = None) -> None:
        if not self.can(to):
            raise ApiError(409, "invalid_state", f"The round can't go from {self.state} to {to}.")
        assert (to == "ABORTED") == (abort_reason in ABORT_REASONS), abort_reason
        self.state, self.abort_reason = to, abort_reason
        if to == "DEBRIEF":
            self.debrief_opened_at = utc_now()

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

    def __init__(self, link, locked, path: Path = SESSION_FILE):
        self.link, self.locked, self.path = link, locked, path  # locked() -> True while LOCKED (§5.6)
        self.session: Session | None = None
        self.lock = asyncio.Lock()  # one lifecycle request at a time
        self._paused_at: float | None = None

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
        for rnd in rounds:  # its live state was in memory and is gone (§6.5)
            if rnd.state in LIVE:
                rnd.move("ABORTED", "controller_restart")
        self.save()

    def current(self) -> Session:
        if self.session is None:
            raise ApiError(404, "not_found", "There is no session yet.")
        return self.session

    async def new_session(self, mode: str) -> Session:
        if self.session is not None and self.session.status == "in_progress":
            current = self.session.current_round
            if current is not None and current.state in LIVE:
                await self._abort(current, "player_restart")
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

    # Rounds (CTL-04)

    def round(self, round_id: str) -> Round:
        for rnd in self.session.rounds if self.session else ():
            if rnd.id == round_id:
                return rnd
        raise ApiError(404, "not_found", "There is no such round.")

    def _current(self, round_id: str, states: tuple[str, ...]) -> Round:
        rnd = self.round(round_id)
        if rnd is not self.session.current_round or rnd.state not in states:
            raise ApiError(409, "invalid_state", f"That can't be done while the round is {rnd.state}.")
        return rnd

    def _playable(self) -> None:
        if self.locked():
            raise ApiError(423, "locked", "A safety check failed, so the game is locked.")
        if not self.link.up() or self.link.config is None:
            raise ApiError(503, "sim_unavailable", "The link to the simulation is down.")

    async def _send(self, cmd: dict) -> None:
        try:
            await self.link.send(cmd)
        except LinkDown:
            raise ApiError(503, "sim_unavailable", "The link to the simulation is down.") from None

    async def prepare(self) -> Round:
        """POST /api/sessions/current/rounds: the next scenario, or a new attempt after an abort."""
        session = self.current()
        if session.status == "complete" or session.debriefed() == len(session.round_order):
            raise ApiError(409, "session_complete", "All three rounds are done.")
        self._playable()
        current = session.current_round
        if current is None:
            scenario_id, attempt = session.round_order[0], 1
        elif current.state == "DEBRIEF":
            current.debrief_closed_at = utc_now()
            session.current_index += 1
            scenario_id, attempt = session.round_order[session.current_index], 1
        elif current.state == "ABORTED":
            scenario_id, attempt = current.scenario_id, current.attempt + 1
        else:
            raise ApiError(409, "invalid_state", f"The current round is still {current.state}.")
        return self._begin(scenario_id, attempt)

    def _begin(self, scenario_id: str, attempt: int) -> Round:
        session, config = self.session, self.link.config
        rnd = Round(new_id("r"), session.id, scenario_id, secrets.randbelow(2**31), attempt, session.mode,
                    time_limit_s=config["round_time_limit_s"], budget_total=config["budget"],
                    budget_remaining=config["budget"], briefing_opened_at=utc_now())
        session.rounds.append(rnd)
        self.save()
        return rnd

    async def start(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("BRIEFING",))
        if self.locked():
            raise ApiError(423, "locked", "A safety check failed, so the game is locked.")
        await self._send({"type": "cmd.resume"})
        rnd.move("ACTIVE")
        rnd.on_call_at = utc_now()
        self.save()
        return rnd

    async def pause(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("ACTIVE",))
        await self._send({"type": "cmd.pause"})
        rnd.move("PAUSED")
        self._paused_at = time.monotonic()
        self.save()
        return rnd

    async def resume(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("PAUSED",))
        await self._send({"type": "cmd.resume"})
        rnd.move("ACTIVE")
        self._unpause(rnd)
        self.save()
        return rnd

    async def restart(self, round_id: str) -> Round:
        """Abort the attempt (unscored) and prepare the same scenario with a new seed, budget and timer."""
        rnd = self._current(round_id, ("ACTIVE", "PAUSED", "ABORTED"))
        self._playable()
        if rnd.state != "ABORTED":
            await self._abort(rnd, "player_restart")
        return self._begin(rnd.scenario_id, rnd.attempt + 1)

    def _unpause(self, rnd: Round) -> None:
        if self._paused_at is not None:
            rnd.paused_s += time.monotonic() - self._paused_at
            self._paused_at = None

    async def _abort(self, rnd: Round, reason: str) -> None:
        rnd.move("ABORTED", reason)
        self._unpause(rnd)
        self.save()
        try:
            await self.link.send({"type": "cmd.stop"})
        except LinkDown:
            pass  # sim's round ended with the link

    def view(self, rnd: Round) -> dict:
        """GET /api/rounds/{id}: no seed, and no scenario id before the debrief."""
        out = {k: v for k, v in dataclasses.asdict(rnd).items() if k not in ("seed", "scenario_id", "session_id")}
        if rnd.state == "DEBRIEF":
            out["scenario_id"] = rnd.scenario_id
        return out | {"timer_remaining_s": rnd.time_limit_s, "health_checks": [], "alerts": [], "statuses": {}}
