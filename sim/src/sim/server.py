"""sim's only network endpoint, on port 9000 (SIM-10, TDD §3.2, §12.2): /healthz and the controller link.

The link carries the controller's commands and sim's events as JSON. A 1 Hz wall-clock heartbeat
carries the isolation result; a failing one is sent once, then the link closes, so the controller
can lock. sim never opens outbound connections; this module only serves.
"""

import asyncio
import http
import json
import os
import sys
from pathlib import Path

import isolation
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from sim.engine import PLAY_STEPS_PER_S, play
from sim.scenarios import SCENARIO_IDS, PackError, load_pack
from sim.world import ACTIONS, World

PORT = 9000
CHECK_INTERVAL_S = 60
HEARTBEAT_INTERVAL_S = 1
MAX_STEPS = 600  # per cmd.step: about 40 ms of work, so heartbeats keep flowing
PLAY_RATE = PLAY_STEPS_PER_S
SCENARIO_DIR = Path("/app/scenarios")  # baked into the image (TDD §4.3)

# Fail closed until the startup check has run.
state = {"isolation": {"status": "fail", "failed": ["not_run"]}, "pack": None}


def healthy() -> bool:
    return state["isolation"]["status"] == "pass"


def process_request(connection: ServerConnection, request):
    if request.path == "/healthz":
        status = http.HTTPStatus.OK if healthy() else http.HTTPStatus.SERVICE_UNAVAILABLE
        return connection.respond(status, json.dumps(state["isolation"]) + "\n")
    if request.path != "/link":
        return connection.respond(http.HTTPStatus.NOT_FOUND, "not found\n")
    return None  # continue the WebSocket handshake; link() reports a failing check and closes


class CommandError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def field(cmd: dict, name: str, kind, allowed=None):
    value = cmd.get(name)
    # bool is an int in Python; never accept true as a seed or step count.
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise CommandError("invalid_request", f"{name} must be {getattr(kind, '__name__', kind)}")
    if allowed is not None and value not in allowed:
        raise CommandError("invalid_request", f"{name} {value!r} is not allowed")
    return value


class Session:
    """One controller link: at most one round. Phases: None, "preroll", "playing", "paused".

    A command that is malformed or not allowed is answered with evt.error and changes nothing.
    """

    def __init__(self, emit, test_mode: bool, pack):
        self.emit, self.test_mode, self.pack = emit, test_mode, pack
        self.world: World | None = None
        self.phase: str | None = None
        self._play: asyncio.Task | None = None

    def handle(self, raw) -> None:
        kind = None
        try:
            try:
                cmd = json.loads(raw)
            except ValueError:
                raise CommandError("invalid_request", "not JSON") from None
            if not isinstance(cmd, dict):
                raise CommandError("invalid_request", "a command is a JSON object")
            kind = cmd.get("type")
            handler = self.COMMANDS.get(kind) if isinstance(kind, str) else None
            if handler is None:
                raise CommandError("unknown_command", f"unknown command {kind!r}")
            handler(self, cmd)
        except CommandError as e:
            self.emit({"type": "evt.error", "code": e.code, "message": e.message, "command": kind})
        except Exception as e:  # a bug in the model: report it and drop the round rather than run on broken state
            self.stop()
            self.emit({"type": "evt.error", "code": "internal_error", "message": repr(e), "command": kind})

    def _round(self) -> World:
        if self.world is None:
            raise CommandError("invalid_state", "no round")
        return self.world

    def start_round(self, cmd):
        scenario_id = field(cmd, "scenario_id", str, SCENARIO_IDS)
        seed = field(cmd, "seed", int)
        self.stop()
        self.world, self.phase = World(scenario_id, seed, self.emit, self.pack), "preroll"

    def step(self, cmd):
        n = field(cmd, "n", int, range(1, MAX_STEPS + 1))
        world = self._round()
        if not self.test_mode and self.phase != "preroll":
            raise CommandError("not_allowed", "cmd.step is accepted only during pre-roll")
        for _ in range(n):
            world.engine.step()

    def resume(self, cmd):
        world = self._round()
        if self.phase not in ("preroll", "paused"):
            raise CommandError("invalid_state", f"cannot resume while {self.phase}")
        self._play = asyncio.get_running_loop().create_task(play(world.engine, PLAY_RATE))
        self._play.add_done_callback(self._play_ended)
        self.phase = "playing"

    def _play_ended(self, task):
        if not task.cancelled() and task.exception():
            self.stop()
            self.emit({"type": "evt.error", "code": "internal_error", "message": repr(task.exception()), "command": None})

    def pause(self, cmd):
        self._round()
        if self.phase != "playing":
            raise CommandError("invalid_state", f"cannot pause while {self.phase}")
        self._play.cancel()
        self.phase = "paused"

    def action(self, cmd):
        # {"type": "cmd.action", "action": {action_id, type, target, params}}: nested, since the
        # envelope's own "type" is taken.
        world = self._round()
        action = field(cmd, "action", dict)
        field(action, "action_id", str)
        kind = field(action, "type", str, ACTIONS)
        field(action, "target", (str, type(None)), ACTIONS[kind][1])
        if not isinstance(action.get("params", {}), dict):
            raise CommandError("invalid_request", "params must be an object")
        world.submit_action(action)

    def stop(self, cmd=None):
        if self._play:
            self._play.cancel()
        self.world = self.phase = self._play = None

    def test_inject(self, cmd):
        if not self.test_mode:
            raise CommandError("not_allowed", "cmd.test_inject is test mode only")
        world = self._round()
        field(cmd, "kind", str, ("ledger_slowdown",))
        world.inject_slowdown(field(cmd, "duration_s", int, (10, 20)))

    COMMANDS = {"cmd.start_round": start_round, "cmd.step": step, "cmd.resume": resume, "cmd.pause": pause,
                "cmd.action": action, "cmd.stop": stop, "cmd.test_inject": test_inject}


def test_mode() -> bool:
    return os.environ.get("ESCAPE_TEST_MODE") == "1"


async def link(ws: ServerConnection) -> None:
    out: asyncio.Queue = asyncio.Queue()
    session = Session(out.put_nowait, test_mode(), state["pack"])

    async def heartbeats():
        while True:
            out.put_nowait({"type": "evt.heartbeat", "isolation": state["isolation"],
                            "pack_version": state["pack"] and state["pack"].version})
            if not healthy():
                return
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)

    async def send() -> bool:  # True after sending a failing heartbeat, False if the peer left
        try:
            while True:
                event = await out.get()
                await ws.send(json.dumps(event))
                if event["type"] == "evt.heartbeat" and event["isolation"]["status"] != "pass":
                    return True
        except ConnectionClosed:
            return False

    async def receive():
        try:
            async for raw in ws:
                session.handle(raw)
        except ConnectionClosed:
            pass

    beat, sender, receiver = (asyncio.create_task(c) for c in (heartbeats(), send(), receive()))
    try:
        done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (beat, sender, receiver):
            task.cancel()
        session.stop()
    if sender in done and sender.result():
        await ws.close(1011, "isolation check failed")


def server(port: int = PORT):
    return serve(link, "0.0.0.0", port, process_request=process_request)


async def main() -> None:
    try:
        state["pack"] = load_pack(SCENARIO_DIR)
    except PackError as e:  # never serve with a broken pack: /healthz stays down and the log names the field
        sys.exit(f"sim: invalid scenario pack: {e}")
    print(f"sim: scenario pack {state['pack'].version}", flush=True)
    state["isolation"] = isolation.run()
    print(f"sim: isolation {state['isolation']}", flush=True)
    async with server():
        while True:
            await asyncio.sleep(CHECK_INTERVAL_S)
            state["isolation"] = await asyncio.to_thread(isolation.run)
            if not healthy():
                print(f"sim: isolation {state['isolation']}", flush=True)
