import copy
import io
import json

from isolation import host_verify
from isolation.host_verify import EDGE, INTERNAL, mismatches

NETWORKS = [
    {"Name": EDGE, "Id": "edge-id", "Internal": False},
    {"Name": INTERNAL, "Id": "internal-id", "Internal": True},
]


def container(service, *nets):
    ids = {EDGE: "edge-id", INTERNAL: "internal-id"}
    return {
        "Name": f"/incident-escape-room-{service}-1",
        "Config": {"Labels": {"com.docker.compose.service": service}},
        "NetworkSettings": {"Networks": {n: {"NetworkID": ids.get(n, "other-id")} for n in nets}},
    }


# Shaped like the real `docker inspect` output of a healthy stack.
CONTAINERS = [container("sim", INTERNAL), container("controller", INTERNAL), container("ui", EDGE, INTERNAL)]


def check(networks=NETWORKS, containers=CONTAINERS):
    return mismatches(copy.deepcopy(networks), copy.deepcopy(containers))


def test_running_stack_passes():
    assert check() == []


def test_internal_network_must_be_internal_and_exist():
    assert check(networks=[NETWORKS[0], {**NETWORKS[1], "Internal": False}]) == [
        f"network {INTERNAL} has Internal=False, not true"]
    assert f"network {INTERNAL} does not exist" in check(networks=[NETWORKS[0]])


def test_sim_and_controller_only_on_internal():
    for service in ("sim", "controller"):
        extra = [c if c["Name"] != f"/incident-escape-room-{service}-1" else container(service, INTERNAL, EDGE)
                 for c in CONTAINERS]
        assert check(containers=extra) == [
            f"container incident-escape-room-{service}-1 is attached to {EDGE}; {service} must not be"]
    host = [container("sim", "host"), *CONTAINERS[1:]]
    assert check(containers=host) == [
        "container incident-escape-room-sim-1 is attached to host; sim must not be",
        f"container incident-escape-room-sim-1 is not attached to {INTERNAL}"]


def test_ui_needs_both_networks():
    assert check(containers=[*CONTAINERS[:2], container("ui", EDGE)]) == [
        f"container incident-escape-room-ui-1 is not attached to {INTERNAL}"]


def test_lookalike_network_from_outside_the_project():
    imposter = container("sim", INTERNAL)
    imposter["NetworkSettings"]["Networks"][INTERNAL]["NetworkID"] = "someone-elses-id"
    assert check(containers=[imposter, *CONTAINERS[1:]]) == [
        f"container incident-escape-room-sim-1 is attached to a {INTERNAL} that is not the project's network"]


def test_missing_and_unexpected_containers():
    assert check(containers=CONTAINERS[1:]) == ["no running container for sim"]
    assert check(containers=[*CONTAINERS, container("debug", EDGE)]) == [
        "container incident-escape-room-debug-1 (service 'debug') is not part of the policy"]


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"networks": NETWORKS, "containers": CONTAINERS})))
    assert host_verify.main() == 0
    assert capsys.readouterr().out.strip() == "host isolation: ok"
    for bad in ('{"networks": []}', "not json", "[]", '{"networks": [1], "containers": []}'):
        monkeypatch.setattr("sys.stdin", io.StringIO(bad))
        assert host_verify.main() == 1
