"""Scenario pack: schema, loader and version (SCN-01, TDD §12.1, §8.7, OR-4).

A pack is a directory: `pack.yaml` (version, baseline world, decoy changes, controller tuning)
plus one YAML file per scenario. Everything is validated on load; any problem raises PackError
naming the file and the field, and sim refuses to start (so /healthz never turns healthy).
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

SCENARIO_IDS = ("pool_leak", "poison_message", "retry_storm")
POLICY = ("backoff", "aggressive")
PAGE_RULES = ("api_error_rate_high", "api_latency_high", "orders_backlog_high")
OPS = (">=", "<=", "==")
EFFECTS = ("fix", "partial_fix", "mitigates", "restores", "no_effect", "unhelpful", "no_change")
# §10.2, plus the two rows it leaves implicit (turning exports back on; worker to backoff).
EFFECT_ROWS = (
    "restart_service(api)", "restart_service(worker)", "restart_service(ledger)", "restart_all",
    "recycle_pool(ledger)", "set_feature_flag(receipt_export, off)", "set_feature_flag(receipt_export, on)",
    "set_feature_flag(checkout_banner, *)", "set_retry_policy(api, backoff)", "set_retry_policy(worker, backoff)",
    "set_retry_policy(*, aggressive)", "quarantine_head_message(jobs)", "purge_queue(jobs)",
)
NUM = (int, float)
NUMBER_TREE = object()  # a mapping whose leaves are all numbers (controller-side tuning)

WORLD = {
    "baseline_s": NUM,
    "traffic": {"rates": {"read": NUM, "receipt_export": NUM, "order": NUM}, "amplitude": NUM, "noise": NUM},
    "ledger": {"pool_size": int, "hold_mean_ms": {"read": NUM, "write": NUM, "receipt_export": NUM}},
    "worker": {"restart_backoff_ms": int},
    "retry_policy": {"api": POLICY, "worker": POLICY},
    "flags": {"receipt_export": bool, "checkout_banner": bool},
}
PACK = {"version": str, "world": WORLD, "decoy_changes": [{"text": str, "yesterday?": bool}],
        "controller": NUMBER_TREE}
FAULT_SCRIPTS = {
    "export_leak": {"kind": str, "leak_probability": NUM},
    "poison_batch": {"kind": str, "batch_size": int},
    "ledger_slowdown": {"kind": str, "multiplier": NUM, "duration_s": NUM},
}
SCENARIO = {
    "id": SCENARIO_IDS,
    "title": str,
    # §7.1 / SCN-02: a scenario may override only the api retry policy and the receipt_export flag.
    "parameters": {"onset_s": NUM, "overrides?": {"retry_policy?": {"api": POLICY}, "flags?": {"receipt_export": bool}}},
    "fault_script": None,  # checked against FAULT_SCRIPTS by its kind
    "recent_change": str,
    # page: the rules that may page; pool_leak and retry_storm list both api rules (D-22).
    "signature": {"page": [PAGE_RULES],
                  "leading_signal": {"signal": str, "direction": ("up", "down"), "floor": NUM},
                  "cells": [{"signal": str, "op": OPS, "value": (int, float, str), "text": str}]},
    "effect_matrix": dict.fromkeys(EFFECT_ROWS, EFFECTS),
    "debrief_copy": {"explanation": str, "clues": [str], "takeaway": str, "held": str, "not_held": str},
}


class PackError(Exception):
    pass


@dataclass
class Pack:
    version: str
    world: dict
    decoy_changes: list
    controller: dict
    scenarios: dict  # id -> scenario mapping


def _at(where, key):
    return f"{where}.{key}" if where else str(key)


def check(value, spec, where: str = "") -> None:
    """Raise PackError naming the dotted field path (empty at the top of a file)."""
    if spec is NUMBER_TREE:
        if not isinstance(value, dict) or not value:
            raise PackError(f"{where or 'file'}: must be a mapping")
        for k, v in value.items():
            check(v, NUMBER_TREE if isinstance(v, dict) else NUM, _at(where, k))
    elif isinstance(spec, dict):
        if not isinstance(value, dict):
            raise PackError(f"{where or 'file'}: must be a mapping")
        fields = {k.rstrip("?"): k for k in spec}
        for k in value:
            if k not in fields:
                raise PackError(f"{_at(where, k)}: unknown field")
        for name, key in fields.items():
            if name in value:
                check(value[name], spec[key], _at(where, name))
            elif not key.endswith("?"):
                raise PackError(f"{_at(where, name)}: missing")
    elif isinstance(spec, list):
        if not isinstance(value, list) or not value:
            raise PackError(f"{where}: must be a non-empty list")
        for i, item in enumerate(value):
            check(item, spec[0], f"{where}[{i}]")
    elif isinstance(spec, tuple) and all(isinstance(s, str) for s in spec):
        if value not in spec:
            raise PackError(f"{where}: must be one of {', '.join(spec)}")
    else:  # a type or a tuple of types; YAML true is never a number
        if not isinstance(value, spec) or (isinstance(value, bool) and spec is not bool):
            raise PackError(f"{where}: wrong type ({type(value).__name__})")


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise PackError(f"{path.name}: not readable YAML: {e}") from None


def _check_file(value, spec, file: str) -> None:
    try:
        check(value, spec)
    except PackError as e:
        raise PackError(f"{file}: {e}") from None


def load_pack(directory: Path) -> Pack:
    directory = Path(directory)
    raw = _read(directory / "pack.yaml")
    _check_file(raw, PACK, "pack.yaml")
    scenarios = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "pack.yaml":
            continue
        s, f = _read(path), path.name
        script = s.get("fault_script") if isinstance(s, dict) else None
        kind = script.get("kind") if isinstance(script, dict) else None
        if kind not in FAULT_SCRIPTS:
            raise PackError(f"{f}: fault_script.kind: must be one of {', '.join(FAULT_SCRIPTS)}")
        _check_file(s, {**SCENARIO, "fault_script": FAULT_SCRIPTS[kind]}, f)
        if s["id"] in scenarios:
            raise PackError(f"{f}: id: {s['id']} is defined twice")
        if s["parameters"]["onset_s"] * 0.8 < raw["world"]["baseline_s"]:  # onset jitter is ±20% (SCN-03)
            raise PackError(f"{f}: parameters.onset_s: earliest onset is before the {raw['world']['baseline_s']} s baseline")
        if not 2 <= len(s["debrief_copy"]["clues"]) <= 3:
            raise PackError(f"{f}: debrief_copy.clues: must have 2 or 3 clues")
        if kind == "export_leak" and not 0 <= script["leak_probability"] <= 1:
            raise PackError(f"{f}: fault_script.leak_probability: must be within 0 and 1")
        scenarios[s["id"]] = s
    if set(scenarios) != set(SCENARIO_IDS):
        raise PackError(f"pack: scenarios: found {sorted(scenarios)}, expected exactly {list(SCENARIO_IDS)}")
    return Pack(raw["version"], raw["world"], raw["decoy_changes"], raw["controller"], scenarios)
