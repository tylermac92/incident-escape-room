"""CTL-01 readiness and error envelope, plus the link's internal-subnet check (CTL-02)."""

import time

import pytest
from fastapi.testclient import TestClient

from controller import app as app_module
from controller.link import is_internal

ROUTES = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"   # 172.18.0.0/16, on-link
    "eth0\t0000000A\t010012AC\t0003\t0\t0\t0\t000000FF\t0\t0\t0\n"   # 10.0.0.0/8 via gateway
)
PASS = {"status": "pass", "failed": []}


@pytest.fixture
def client():
    # No `with`: the lifespan (real checks, real link) does not run in unit tests.
    app_module.state["isolation"] = {"status": "fail", "failed": ["not_run"]}
    app_module.link.last_heartbeat, app_module.link.address_ok = None, True
    app_module.link.sim_isolation = None
    return TestClient(app_module.app)


def error(response):
    return response.status_code, response.json()["error"]["code"]


def test_live(client):
    assert client.get("/api/health/live").json() == {"status": "live"}


def test_ready_fails_closed_before_first_check(client):
    assert error(client.get("/api/health/ready")) == (503, "locked")


def test_ready_needs_the_sim_link(client):
    app_module.state["isolation"] = PASS
    assert error(client.get("/api/health/ready")) == (503, "sim_unavailable")
    app_module.link.last_heartbeat = time.monotonic()
    assert client.get("/api/health/ready").status_code == 200
    app_module.link.last_heartbeat = time.monotonic() - 4  # heartbeat older than 3 s
    assert error(client.get("/api/health/ready")) == (503, "sim_unavailable")


def test_ready_names_failed_checks(client):
    app_module.state["isolation"] = {"status": "fail", "failed": ["route", "dns"]}
    body = client.get("/api/health/ready").json()["error"]
    assert body["details"]["failed_checks"] == ["route", "dns"]


def test_sim_outside_subnet_locks(client):
    app_module.state["isolation"] = PASS
    app_module.link.last_heartbeat = time.monotonic()
    app_module.link.address_ok = False
    body = client.get("/api/health/ready").json()["error"]
    assert body["code"] == "locked" and body["details"]["failed_checks"] == ["sim_address"]


def test_unknown_path_uses_envelope(client):
    assert error(client.get("/nope")) == (404, "not_found")


def test_unhandled_error_uses_envelope(client):
    @app_module.app.get("/api/test-boom")
    def boom():
        raise RuntimeError("boom")

    try:
        response = TestClient(app_module.app, raise_server_exceptions=False).get("/api/test-boom")
    finally:
        app_module.app.router.routes.pop()
    assert error(response) == (500, "internal_error")


def test_is_internal():
    assert is_internal("172.18.0.3", ROUTES)
    assert not is_internal("10.1.2.3", ROUTES)   # reachable only through a gateway
    assert not is_internal("8.8.8.8", ROUTES)


def test_sim_isolation_failure_locks(client):
    app_module.state["isolation"] = PASS
    app_module.link.record({"type": "evt.heartbeat", "isolation": PASS})
    assert client.get("/api/health/ready").status_code == 200

    app_module.link.record({"type": "evt.heartbeat", "isolation": {"status": "fail", "failed": ["route"]}})
    app_module.link.last_heartbeat = time.monotonic() - 10  # sim then closes the link: still locked
    body = client.get("/api/health/ready").json()["error"]
    assert body["code"] == "locked" and body["details"]["failed_checks"] == ["sim.route"]


@pytest.mark.parametrize("isolation", [None, "pass", {"status": "pass"}, {"status": "fail", "failed": []}])
def test_malformed_or_missing_sim_result_locks(client, isolation):
    app_module.state["isolation"] = PASS
    app_module.link.record({"type": "evt.heartbeat", "isolation": isolation})
    assert error(client.get("/api/health/ready")) == (503, "locked")


def test_host_lock_marker_locks(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "HOST_LOCK", tmp_path / "escape-host-lock")
    app_module.state["isolation"] = PASS
    app_module.link.last_heartbeat = time.monotonic()
    assert client.get("/api/health/ready").status_code == 200
    (tmp_path / "escape-host-lock").touch()
    body = client.get("/api/health/ready").json()["error"]
    assert body["code"] == "locked" and body["details"]["failed_checks"] == ["host_check"]
