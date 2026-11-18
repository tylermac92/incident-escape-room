import copy
import io
import json

import pytest

from isolation import compose_policy
from isolation.compose_policy import violations

ROOT = "/home/p/incident-escape-room"
L = {"com.incident-escape-room.managed": "true"}


def svc(networks, **extra):
    return {"labels": dict(L), "networks": {n: None for n in networks}, **extra}


# Shaped like `docker compose config --format json` of the shipped compose.yaml.
GOOD = {
    "name": "incident-escape-room",
    "services": {
        "sim": svc(["escape_internal"], tmpfs=["/tmp:size=16m"]),
        "controller": svc(["escape_internal"], volumes=[
            {"type": "volume", "source": "escape_results", "target": "/data", "volume": {}}]),
        "ui": svc(["escape_edge", "escape_internal"], ports=[
            {"mode": "ingress", "host_ip": "127.0.0.1", "target": 8080, "published": "8080", "protocol": "tcp"}]),
    },
    "networks": {
        "escape_internal": {"name": "x_internal", "internal": True, "labels": dict(L)},
        "escape_edge": {"name": "x_edge", "driver": "bridge", "labels": dict(L)},
    },
    "volumes": {"escape_results": {"name": "x_results", "labels": dict(L)}},
}


def rules(config, profile="player"):
    return {rule for rule, _ in violations(config, profile, ROOT)}


def mutate(fn):
    config = copy.deepcopy(GOOD)
    fn(config)
    return config


def dev_mount(source, read_only=True):
    return {"type": "bind", "source": source, "target": "/app/src", "read_only": read_only}


@pytest.mark.parametrize("profile", ["player", "dev", "test"])
def test_shipped_shape_passes(profile):
    assert violations(GOOD, profile, ROOT) == []


@pytest.mark.parametrize("change, rule", [
    (lambda c: c["networks"]["escape_internal"].pop("internal"), "internal-network"),
    (lambda c: c["services"]["sim"]["networks"].update(escape_edge=None), "internal-network"),
    (lambda c: c["services"]["controller"].pop("networks"), "internal-network"),
    (lambda c: c["services"]["ui"].update(network_mode="host"), "forbidden-option"),
    (lambda c: c["services"]["sim"].update(privileged=True), "forbidden-option"),
    (lambda c: c["services"]["sim"].update(cap_add=["NET_ADMIN"]), "forbidden-option"),
    (lambda c: c["services"]["sim"].update(devices=[{"source": "/dev/kvm", "target": "/dev/kvm"}]), "forbidden-option"),
    (lambda c: c["services"]["controller"].update(pid="host"), "forbidden-option"),
    (lambda c: c["services"]["controller"].update(ipc="host"), "forbidden-option"),
    (lambda c: c["services"]["controller"]["volumes"].append(
        {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}), "docker-socket"),
    (lambda c: c["services"]["sim"].update(volumes=[{"type": "bind", "source": "/home/p", "target": "/x"}]), "host-mount"),
    (lambda c: c["services"]["sim"].update(volumes=[dev_mount(f"{ROOT}/sim")]), "host-mount"),
    (lambda c: c["volumes"]["escape_results"].update(driver_opts={"o": "bind", "device": "/"}), "host-mount"),
    (lambda c: c.update(secrets={"s": {"file": "/etc/shadow"}}), "host-mount"),
    (lambda c: c["services"]["ui"]["ports"][0].update(host_ip=""), "ports"),
    (lambda c: c["services"]["ui"]["ports"][0].update(host_ip="0.0.0.0"), "ports"),
    (lambda c: c["services"]["ui"]["ports"][0].update(published="8080-8090"), "ports"),
    (lambda c: c["services"]["ui"]["ports"].append(dict(c["services"]["ui"]["ports"][0], published="8001")), "ports"),
    (lambda c: c["services"]["ui"].pop("ports"), "ports"),
    (lambda c: c["services"]["controller"].update(ports=c["services"]["ui"].pop("ports")), "ports"),
    (lambda c: c["services"]["sim"].update(environment={"AWS_ACCESS_KEY_ID": "x"}), "environment"),
    (lambda c: c["services"]["sim"].update(environment={"HTTP_PROXY": "http://p"}), "environment"),
    (lambda c: c["services"]["sim"].update(environment={"ESCAPE_DEV": "1"}), "environment"),
    (lambda c: c["services"]["ui"]["labels"].clear(), "label"),
    (lambda c: c["networks"]["escape_edge"].pop("labels"), "label"),
    (lambda c: c["volumes"]["escape_results"]["labels"].update({"com.incident-escape-room.managed": "false"}), "label"),
    (lambda c: c.update(name="other"), "label"),
])
def test_player_profile_rejects(change, rule):
    assert rule in rules(mutate(change))


def test_allowlisted_environment_passes():
    config = mutate(lambda c: c["services"]["sim"].update(environment={"TZ": "UTC", "ESCAPE_PORT": "8080"}))
    assert violations(config) == []


def test_dev_profile_allows_only_its_relaxations():
    def dev(c):
        for name in ("ui", "controller", "sim"):
            c["services"][name].setdefault("volumes", []).append(dev_mount(f"{ROOT}/{name}"))
            c["services"][name]["environment"] = {"ESCAPE_DEV": "1"}
    assert rules(mutate(dev), "dev") == set()
    assert rules(mutate(dev), "player") == {"host-mount", "environment"}  # a dev override under make up

    writable = mutate(lambda c: c["services"]["sim"].update(volumes=[dev_mount(f"{ROOT}/sim", read_only=False)]))
    other_dir = mutate(lambda c: c["services"]["sim"].update(volumes=[dev_mount(f"{ROOT}/docs")]))
    dev_value = mutate(lambda c: c["services"]["sim"].update(environment={"ESCAPE_DEV": "true"}))
    second_port = mutate(lambda c: c["services"]["ui"]["ports"].append(
        dict(c["services"]["ui"]["ports"][0], published="8001")))
    assert rules(writable, "dev") == {"host-mount"}
    assert rules(other_dir, "dev") == {"host-mount"}
    assert rules(dev_value, "dev") == {"environment"}
    assert rules(second_port, "dev") == {"ports"}


def test_main_reports_and_exits(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(GOOD)))
    assert compose_policy.main(["--profile", "player"]) == 0
    assert capsys.readouterr().out.strip() == "compose policy (player): ok"

    bad = mutate(lambda c: c["services"]["ui"].update(privileged=True))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(bad)))
    assert compose_policy.main([]) == 1
    assert "FAIL forbidden-option: ui sets privileged" in capsys.readouterr().out

    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert compose_policy.main([]) == 1


def test_test_mode_flag_only_in_the_test_profile():
    def test_mode(c):
        for name in ("sim", "controller"):
            c["services"][name]["environment"] = {"ESCAPE_TEST_MODE": "1"}
    assert rules(mutate(test_mode), "test") == set()
    assert rules(mutate(test_mode), "player") == {"environment"}  # the test override under make up
    assert rules(mutate(test_mode), "dev") == {"environment"}
    other_value = mutate(lambda c: c["services"]["sim"].update(environment={"ESCAPE_TEST_MODE": "yes"}))
    assert rules(other_value, "test") == {"environment"}
    dev_in_test = mutate(lambda c: c["services"]["sim"].update(environment={"ESCAPE_DEV": "1"}))
    assert rules(dev_in_test, "test") == {"environment"}
