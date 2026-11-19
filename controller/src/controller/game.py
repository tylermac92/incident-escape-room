"""Sessions (CTL-03), the round lifecycle (CTL-04) and the pre-roll (CTL-05): TDD §4.6, §6, §12.

A session is three rounds, one per scenario, in a random order. It is mirrored to
/data/session.json on every change, so a controller restart keeps completed rounds. The round
order and scenario ids are never sent to the UI before a round's debrief (§9.7).

Every attempt at a scenario is its own Round; restarting aborts the attempt and adds a new one.

Pre-roll (D-05): the controller steps sim one simulated second at a time and runs the per-tick
pipeline after each tick. In the second a page fires it stops: that second is T0, sim stays paused
and the round enters BRIEFING. One task per round is the only reader of link.events.
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

from controller import actions as catalog
from controller.alerts import Alerts
from controller.errors import ApiError
from controller.feed import Feed
from controller.health import Health
from controller.impact import Impact
from controller.link import HEARTBEAT_TIMEOUT_S, LinkDown

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
NUDGE_AFTER_MS = 180_000  # stable this long without a declaration: one nudge (§6.4)
PREROLL_LIMIT_MS = 900_000  # no page this long after onset: preroll_no_alert
STEPS_PER_S = 10
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
    outcome: str | None = None  # recovered, recovered_undeclared, not_recovered (§11.3)
    ttr_s: float | None = None  # healthy_since - T0 for the period that counted (CTL-06)
    premature_declarations: int = 0  # rejected declare-resolved calls (CTL-14)
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
        self._task: asyncio.Task | None = None  # the current round's runner
        self._tick: dict | None = None  # the current round's latest evt.tick (hidden fields included)
        self._alerts: Alerts | None = None
        self.events: list[dict] = []  # the current round's RoundEvent log (CTL-07, §6.3)
        self._health: Health | None = None
        self.checks: list[dict] = []  # the latest health-check results (CTL-08)
        self.impact: Impact | None = None  # the current round's impact accounting (CTL-10)
        self.content: dict | None = None  # feed templates and fictional lists, loaded at startup (CTL-11)
        self.feed: Feed | None = None
        self.actions: list[dict] = []  # the current round's PlayerAction log (CTL-12, CTL-13)
        self._requests: dict = {}  # client_request_id -> the original response or ApiError

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

    def _begin(self, scenario_id: str, attempt: int, retry: bool = True) -> Round:
        session, config = self.session, self.link.config
        rnd = Round(new_id("r"), session.id, scenario_id, secrets.randbelow(2**31), attempt, session.mode,
                    time_limit_s=config["round_time_limit_s"], budget_total=config["budget"],
                    budget_remaining=config["budget"], briefing_opened_at=utc_now())
        session.rounds.append(rnd)
        self.save()
        self._stop_runner()
        self._tick, self._alerts, self.events = None, Alerts(config["alerts"]), []
        self._health, self.checks, self.impact = Health(), [], Impact()
        self.feed = Feed(rnd.seed, self.content, config["feed"])
        self.actions, self._requests = [], {}
        self._log("state_change", **{"from": None, "to": rnd.state})
        self._task = asyncio.get_running_loop().create_task(self._run(rnd, retry))
        return rnd

    def _stop_runner(self) -> None:
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()

    async def _run(self, rnd: Round, retry: bool) -> None:
        reason = await self._preroll(rnd)
        while reason is None and rnd.state in LIVE:
            reason = self._observe(rnd, await self.link.events.get())
        if reason is None:
            await self._stop_sim()  # the round ended (timeout)
        elif rnd.state in LIVE:
            await self._abort(rnd, reason)
            if reason == "preroll_no_alert" and retry:  # once, with a new seed (CTL-05)
                self._begin(rnd.scenario_id, rnd.attempt + 1, retry=False)

    async def _preroll(self, rnd: Round) -> str | None:
        """Step to the page. Returns an abort reason, or None once the round is in BRIEFING."""
        self.link.drain()
        try:
            await self.link.send({"type": "cmd.start_round", "scenario_id": rnd.scenario_id, "seed": rnd.seed})
            t_ms = 0
            while True:
                await self.link.send({"type": "cmd.step", "n": STEPS_PER_S})
                t_ms += 1000
                event = await asyncio.wait_for(self.link.events.get(), HEARTBEAT_TIMEOUT_S)
                while event["type"] == "evt.tick" and event["sim_time_ms"] != t_ms:  # a stopped round's last ticks
                    event = await asyncio.wait_for(self.link.events.get(), HEARTBEAT_TIMEOUT_S)
                if event["type"] != "evt.tick":
                    return "sim_unavailable"  # evt.error or link.down
                if (reason := self._observe(rnd, event)) is not None:
                    return reason
                if self._alerts.page is not None:
                    rnd.t0_ms = t_ms
                    self._move(rnd, "BRIEFING")
                    self.save()
                    return None
                if t_ms > rnd.t_onset_ms + PREROLL_LIMIT_MS:
                    return "preroll_no_alert"
        except (LinkDown, TimeoutError):
            return "sim_unavailable"

    def _observe(self, rnd: Round, event: dict) -> str | None:
        """One link event for a live round. Returns an abort reason, if it ends the round."""
        if event["type"] == "link.down":
            return "sim_unavailable"
        if event["type"] == "evt.error":
            if event.get("code") == "internal_error":  # sim dropped its round
                return "sim_unavailable"
            print(f"controller: sim refused a command: {event}", flush=True)
            return None
        if self.locked():
            return "isolation_check_failed"
        # §6.3 order: health checks (CTL-08), alerts, impact (CTL-10), feed (CTL-11), state, broadcast (CTL-18).
        self._tick, fault, t_ms = event, event["hidden"]["fault"], event["sim_time_ms"]
        rnd.t_onset_ms = fault["onset_ms"]
        since_t0 = None if rnd.t0_ms is None else (t_ms - rnd.t0_ms) // 1000 + 1
        self.checks = self._health.evaluate(event["services"], since_t0)
        for alert in self._alerts.evaluate(event["services"], t_ms, armed=fault["active"]):
            self._log("alert", **{k: alert[k] for k in ("rule_id", "state", "is_page")})
        bad = event["bad_events"]
        self.impact.add(bad["counts"], bad["weights"], after_t0=rnd.t0_ms is not None and t_ms > rnd.t0_ms)
        self.feed.add(t_ms, bad["counts"], all(c["passing"] for c in self.checks), not fault["active"], rnd.t0_ms)
        if rnd.state == "ACTIVE":
            self._update(rnd, t_ms)
        return None

    def _update(self, rnd: Round, t_ms: int) -> None:
        """The state step of a tick while ACTIVE: stability, the nudge, and the timeout (CTL-06, §6.4)."""
        if not all(c["passing"] for c in self.checks):
            rnd.healthy_since_ms = None
        elif rnd.healthy_since_ms is None:
            rnd.healthy_since_ms = t_ms
        stable_ms = -1 if rnd.healthy_since_ms is None else t_ms - rnd.healthy_since_ms
        if stable_ms >= NUDGE_AFTER_MS and not any(e["kind"] == "nudge" for e in self.events):
            self._log("nudge")
        if rnd.mode == "standard" and t_ms - rnd.t0_ms >= rnd.time_limit_s * 1000:
            stable = stable_ms >= self.link.config["stability_window_s"] * 1000
            rnd.outcome = "recovered_undeclared" if stable else "not_recovered"
            rnd.ttr_s = (rnd.healthy_since_ms - rnd.t0_ms) / 1000 if stable else None
            self._move(rnd, "TIMED_OUT")
            self._finish(rnd)

    def _finish(self, rnd: Round) -> None:
        """RESOLVED, TIMED_OUT or ENDED -> DEBRIEF."""
        self._move(rnd, "DEBRIEF")
        self.save()

    async def declare(self, round_id: str) -> Round:
        """POST /api/rounds/{id}/declare-resolved (CTL-14, §6.4)."""
        rnd = self._current(round_id, ("ACTIVE",))
        required_s = self.link.config["stability_window_s"]
        stable = rnd.healthy_since_ms is not None
        green_s = (self._tick["sim_time_ms"] - rnd.healthy_since_ms) // 1000 if stable else 0
        if stable and green_s >= required_s:
            rnd.outcome, rnd.ttr_s = "recovered", (rnd.healthy_since_ms - rnd.t0_ms) / 1000
            self._log("declaration", accepted=True)
            self._move(rnd, "RESOLVED")
            self._finish(rnd)
            self._stop_runner()
            await self._stop_sim()
            return rnd
        weights = self.link.config["score"]
        rnd.premature_declarations += 1
        penalty = weights["premature"] if rnd.premature_declarations <= weights["premature_max_count"] else 0
        failing = [c["id"] for c in self.checks if not c["passing"]]
        self._log("declaration", accepted=False, green_for_s=green_s, failing_checks=failing)
        self.save()
        message = (f"Not yet — {len(failing)} health check{'s are' if len(failing) > 1 else ' is'} failing." if failing
                   else f"Not yet — health checks have been green for {green_s} of the required {required_s} seconds.")
        raise ApiError(409, "not_stable", message, {"green_for_s": green_s, "required_s": required_s,
                                                     "penalty": penalty, "failing_checks": failing})

    async def start(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("BRIEFING",))
        if self.locked():
            raise ApiError(423, "locked", "A safety check failed, so the game is locked.")
        await self._send({"type": "cmd.resume"})
        self._move(rnd, "ACTIVE")
        rnd.on_call_at = utc_now()
        self.save()
        return rnd

    async def pause(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("ACTIVE",))
        await self._send({"type": "cmd.pause"})
        self._move(rnd, "PAUSED")
        self._paused_at = time.monotonic()
        self.save()
        return rnd

    async def resume(self, round_id: str) -> Round:
        rnd = self._current(round_id, ("PAUSED",))
        await self._send({"type": "cmd.resume"})
        self._move(rnd, "ACTIVE")
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

    # Actions (CTL-12, CTL-13)

    async def act(self, round_id: str, request: dict) -> dict:
        """POST /api/rounds/{id}/actions. A repeated client_request_id gets the original answer, uncharged."""
        if (why := catalog.invalid(request["type"], request.get("target"), request.get("params") or {})) is not None:
            raise ApiError(422, "invalid_request", why)  # a schema error: not an attempt, so not logged
        rnd = self.round(round_id)
        prior = self._requests.get(request["client_request_id"]) if rnd is self.session.current_round else None
        if isinstance(prior, ApiError):
            raise prior
        if prior is not None:
            return prior
        try:
            response = await self._accept(rnd, request)
        except ApiError as e:
            if e.code != "sim_unavailable":  # the link may be back on a retry
                self._requests[request["client_request_id"]] = e
            if rnd is self.session.current_round and self._tick is not None:
                self.actions.append(self._new_action(request, None, "rejected") | {"reject_reason": e.code})
            raise
        self._requests[request["client_request_id"]] = response
        return response

    def _new_action(self, request: dict, cost: int | None, status: str) -> dict:
        t_ms = self._tick["sim_time_ms"]
        delay_ms = catalog.CATALOG[request["type"]]["delay_s"] * 1000
        return {"id": f"a_{len(self.actions) + 1:04d}", "client_request_id": request["client_request_id"],
                "type": request["type"], "target": request.get("target"), "params": request.get("params") or {},
                "cost": cost, "status": status, "reject_reason": None, "submitted_at_ms": t_ms,
                "effective_at_ms": t_ms + delay_ms, "effect_class": None}

    def public_action(self, rnd: Round, action: dict) -> dict:
        """effect_class is revealed only in the debrief (QA-07)."""
        return action if rnd.state == "DEBRIEF" else {k: v for k, v in action.items() if k != "effect_class"}

    async def _accept(self, rnd: Round, request: dict) -> dict:
        kind, target, params = request["type"], request.get("target"), request.get("params") or {}
        if rnd is not self.session.current_round or rnd.state != "ACTIVE":
            raise ApiError(409, "invalid_state", f"Actions can only be run while the round is ACTIVE, not {rnd.state}.")
        cost = self.link.config["action_costs"][kind]
        if rnd.budget_remaining < cost:
            raise ApiError(409, "insufficient_budget",
                           f"{catalog.CATALOG[kind]['label']} costs {cost} points; you have {rnd.budget_remaining} left.",
                           {"cost": cost, "budget_remaining": rnd.budget_remaining})
        services, config = self._tick["services"], self._tick["config"]
        if any(services[name]["status"] == "Restarting" for name in catalog.needs_up(kind, target)):
            raise ApiError(409, "target_unavailable", "That service is restarting.")
        if target == "jobs" and services["worker"]["queue_depth"]["jobs"] == 0:
            raise ApiError(409, "target_unavailable", "jobs is empty.")
        pending = [a for a in self.actions if a["status"] == "pending"]
        if any(a["type"] == "restart_all" or a["target"] == target for a in pending) or (kind == "restart_all" and pending):
            raise ApiError(409, "action_in_progress", "An action on that target is still in progress.")
        current = {"set_feature_flag": lambda: config["flags"][target] == params["enabled"],
                   "set_retry_policy": lambda: config["retry_policy"][target] == params["mode"]}.get(kind)
        if current and current():
            raise ApiError(409, "no_change", "That is already the current setting.")
        action = self._new_action(request, cost, "pending")
        action["effect_class"] = catalog.effect_class(self.link.effect_matrices[rnd.scenario_id], kind, target, params)
        try:
            applied = await self.link.action({"action_id": action["id"], "type": kind, "target": target, "params": params})
        except LinkDown:
            raise ApiError(503, "sim_unavailable", "The link to the simulation is down.") from None
        applied.add_done_callback(lambda future: self._applied(action, future))
        rnd.budget_remaining -= cost  # charged on acceptance, before the delay (§10.3)
        self.actions.append(action)
        self._log("action", id=action["id"], type=kind, target=target, status="pending")
        self.save()
        return {"action": self.public_action(rnd, action), "budget_remaining": rnd.budget_remaining,
                "sandbox_target": catalog.sandbox_target(target)}

    def _applied(self, action: dict, future) -> None:
        """evt.action_applied arrived (pending -> completed), or the link dropped first (refunded)."""
        if action["status"] != "pending" or action not in self.actions:
            return
        if future.cancelled():
            self._refund(action)
            return
        action["status"], action["effective_at_ms"] = "completed", future.result()
        self._log("action", action["effective_at_ms"], id=action["id"], type=action["type"], target=action["target"],
                  status="completed")

    def _refund(self, action: dict) -> None:
        """sim never applied it: give the cost back (§10.3). The round is aborted by the link.down (CTL-20)."""
        action["status"] = "refunded"
        self.session.current_round.budget_remaining += action["cost"]
        self._log("action", id=action["id"], type=action["type"], target=action["target"], status="refunded")

    def _log(self, kind: str, t_ms: int | None = None, **payload) -> None:
        """Append to the current round's event log: seq strictly increasing, stamped with sim time
        (the latest tick's, unless sim reported the event's own time)."""
        t_ms = t_ms if t_ms is not None else self._tick["sim_time_ms"] if self._tick else 0
        self.events.append({"seq": len(self.events) + 1, "sim_time_ms": t_ms, "kind": kind, "payload": payload})

    def _move(self, rnd: Round, to: str, abort_reason: str | None = None) -> None:
        old = rnd.state
        rnd.move(to, abort_reason)
        self._log("state_change", **{"from": old, "to": to}, **({"abort_reason": abort_reason} if abort_reason else {}))

    def _unpause(self, rnd: Round) -> None:
        if self._paused_at is not None:
            rnd.paused_s += time.monotonic() - self._paused_at
            self._paused_at = None

    async def _abort(self, rnd: Round, reason: str) -> None:
        self._stop_runner()
        self._move(rnd, "ABORTED", reason)
        for action in self.actions:
            if action["status"] == "pending":
                self._refund(action)
        self._unpause(rnd)
        self.save()
        await self._stop_sim()

    async def _stop_sim(self) -> None:
        try:
            await self.link.send({"type": "cmd.stop"})
        except LinkDown:
            pass  # sim's round ended with the link

    def view(self, rnd: Round) -> dict:
        """GET /api/rounds/{id}: never the seed; the scenario and onset only from the debrief (§3.2)."""
        # healthy_since would let the UI show a countdown, which §6.4 rules out.
        hidden = ("seed", "session_id") + (() if rnd.state == "DEBRIEF" else ("scenario_id", "t_onset_ms", "healthy_since_ms"))
        out = {k: v for k, v in dataclasses.asdict(rnd).items() if k not in hidden}
        live = rnd is self.session.current_round and self._tick is not None
        t_ms = self._tick["sim_time_ms"] if live else None
        elapsed_s = (t_ms - rnd.t0_ms) / 1000 if live and rnd.t0_ms is not None else 0
        return out | {
            "t_ms": t_ms, "timer_remaining_s": max(0, rnd.time_limit_s - elapsed_s),  # from T0 only (§6.2)
            "health_checks": self.checks if live else [],
            "alerts": list(self._alerts.alerts.values()) if live else [],
            "impact": self.impact.counters() if live else None,
            "feed": self.feed.items if live else [],
            "actions": [self.public_action(rnd, a) for a in self.actions] if live else [],
            "statuses": {name: s["status"] for name, s in self._tick["services"].items()} if live else {},
        }
