import asyncio
import shutil
from pathlib import Path

import pytest
import yaml

from sim import server
from sim.scenarios import EFFECT_ROWS, SCENARIO_IDS, PackError, load_pack

PACK_DIR = Path(__file__).parents[1] / "scenarios"


def test_the_shipped_pack_loads_exactly_three_scenarios():
    pack = load_pack(PACK_DIR)
    assert sorted(pack.scenarios) == sorted(SCENARIO_IDS) and pack.version
    for s in pack.scenarios.values():
        assert list(s["effect_matrix"]) == list(EFFECT_ROWS)


def broken(tmp_path, file, change):
    """Copy the pack, apply change(data) to one file, and return the load error."""
    d = tmp_path / "pack"
    shutil.copytree(PACK_DIR, d)
    data = yaml.safe_load((d / file).read_text())
    change(data)
    (d / file).write_text(yaml.safe_dump(data))
    with pytest.raises(PackError) as e:
        load_pack(d)
    return str(e.value)


@pytest.mark.parametrize("file, change, message", [
    ("pool_leak.yaml", lambda d: d.pop("effect_matrix"), "pool_leak.yaml: effect_matrix: missing"),
    ("pool_leak.yaml", lambda d: d["parameters"].update(onset_secs=1), "pool_leak.yaml: parameters.onset_secs: unknown field"),
    ("retry_storm.yaml", lambda d: d["fault_script"].update(multiplier="8x"), "retry_storm.yaml: fault_script.multiplier: wrong type"),
    ("retry_storm.yaml", lambda d: d["parameters"]["overrides"].update(retry_policy={"api": "yolo"}),
     "retry_storm.yaml: parameters.overrides.retry_policy.api: must be one of"),
    ("pool_leak.yaml", lambda d: d["parameters"]["overrides"].update(ledger={"pool_size": 5}),
     "pool_leak.yaml: parameters.overrides.ledger: unknown field"),  # only §7.1 overrides
    ("poison_message.yaml", lambda d: d["fault_script"].update(kind="rm"), "poison_message.yaml: fault_script.kind"),
    ("poison_message.yaml", lambda d: d["parameters"].update(onset_s=700), "poison_message.yaml: parameters.onset_s"),
    ("poison_message.yaml", lambda d: d.update(id="pool_leak"), "pool_leak.yaml: id: pool_leak is defined twice"),
    ("poison_message.yaml", lambda d: d["debrief_copy"].update(clues=["one"]), "debrief_copy.clues"),
    ("pack.yaml", lambda d: d["world"]["flags"].update(receipt_export="on"), "pack.yaml: world.flags.receipt_export: wrong type"),
    ("pack.yaml", lambda d: d["world"]["traffic"]["rates"].update(read=True), "pack.yaml: world.traffic.rates.read: wrong type"),
    ("pack.yaml", lambda d: d["controller"]["score"].update(noeffect="30"), "pack.yaml: controller.score.noeffect: wrong type"),
])
def test_invalid_files_name_the_file_and_field(tmp_path, file, change, message):
    assert message in broken(tmp_path, file, change)


def test_a_missing_scenario_or_bad_yaml_is_rejected(tmp_path):
    d = tmp_path / "pack"
    shutil.copytree(PACK_DIR, d)
    (d / "retry_storm.yaml").unlink()
    with pytest.raises(PackError, match="expected exactly"):
        load_pack(d)
    (d / "retry_storm.yaml").write_text("id: [unclosed")
    with pytest.raises(PackError, match="retry_storm.yaml: not readable YAML"):
        load_pack(d)


def test_sim_refuses_to_start_with_an_invalid_pack(tmp_path, monkeypatch):
    (tmp_path / "pack.yaml").write_text("version: 1\n")
    monkeypatch.setattr(server, "SCENARIO_DIR", tmp_path)
    with pytest.raises(SystemExit, match="invalid scenario pack: pack.yaml: version: wrong type"):
        asyncio.run(server.main())
