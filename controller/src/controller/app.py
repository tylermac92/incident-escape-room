"""Controller service frame (CTL-01): health endpoints, the error envelope, isolation checks.

Readiness returns 503 whenever the game must not be playable (TDD §4.5, §5.6). Its error
code says why: `locked` when an isolation check failed, `sim_unavailable` when the link is down.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Literal

import isolation
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from controller.errors import ApiError
from controller.feed import load_content
from controller.game import Game
from controller.link import Link

CHECK_INTERVAL_S = 60
# Written by `make up KEEP_ON_FAIL=1` when a host-side check failed after start (ENV-09).
HOST_LOCK = Path("/tmp/escape-host-lock")

# Fail closed until the startup check has run.
state = {"isolation": {"status": "fail", "failed": ["not_run"]}}
link = Link()
game = Game(link, locked=lambda: isolation_result()["status"] != "pass")


def envelope(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(status_code=status, content=body)


def isolation_result() -> dict:
    """The controller's own checks plus sim's (prefixed `sim.`), as last reported over the link."""
    failed = state["isolation"]["failed"] + ([] if link.address_ok else ["sim_address"])
    if HOST_LOCK.exists():
        failed = failed + ["host_check"]
    sim = link.sim_isolation
    if sim is not None and sim.get("status") != "pass":
        failed += [f"sim.{check}" for check in sim["failed"] or ["unknown"]]
    return {"status": "fail" if failed else "pass", "failed": failed}


async def recheck_isolation() -> None:
    while True:
        await asyncio.sleep(CHECK_INTERVAL_S)
        state["isolation"] = await asyncio.to_thread(isolation.run)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    game.content = load_content()  # never run without the feed copy: a bad file stops startup
    game.load()
    state["isolation"] = isolation.run()
    print(f"controller: isolation {state['isolation']}", flush=True)
    tasks = [asyncio.create_task(recheck_isolation()), asyncio.create_task(link.run())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Incident Escape Room controller", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(ApiError)
async def api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return envelope(exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "invalid_request"
    return envelope(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return envelope(422, "invalid_request", "The request is not valid.", {"errors": exc.errors()})


@app.exception_handler(Exception)
async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
    # A bug, not a player error: still the envelope, never a stack trace (§12.4).
    print(f"controller: unhandled {exc!r}", flush=True)
    return envelope(500, "internal_error", "Something went wrong in the game controller.")


@app.get("/api/health/live")
def live() -> dict:
    return {"status": "live"}


@app.get("/api/health/ready")
def ready() -> dict:
    result = isolation_result()
    if result["status"] != "pass":
        raise ApiError(503, "locked", "An isolation check failed, so the game is locked.",
                       {"failed_checks": result["failed"]})
    if not link.up():
        raise ApiError(503, "sim_unavailable", "The link to the simulation is down.")
    return {"status": "ready", "isolation": "pass", "sim_link": "up"}


class NewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["standard", "practice"] = "standard"


@app.post("/api/sessions", status_code=201)
async def create_session(body: NewSession | None = None) -> dict:
    async with game.lock:
        return (await game.new_session((body or NewSession()).mode)).summary()


@app.get("/api/sessions/current")
def current_session() -> dict:
    return game.current().summary()


@app.post("/api/sessions/current/complete")
def complete_session() -> dict:
    return game.complete().summary()


@app.post("/api/sessions/current/rounds", status_code=201)
async def prepare_round() -> dict:
    async with game.lock:
        return game.view(await game.prepare())


@app.get("/api/rounds/{round_id}")
def get_round(round_id: str) -> dict:
    return game.view(game.round(round_id))


@app.post("/api/rounds/{round_id}/{verb}")
async def lifecycle(round_id: str, verb: Literal["start", "pause", "resume", "restart"]) -> dict:
    async with game.lock:
        return game.view(await getattr(game, verb)(round_id))
