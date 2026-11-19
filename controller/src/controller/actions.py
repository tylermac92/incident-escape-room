"""The action catalog (CTL-12, TDD §10.1). Every target and param is a closed enumeration (SR-7).

Costs come from the pack (`controller.action_costs`); the delays are the ones sim applies.
"""

SERVICES = ("api", "worker", "ledger")
CATALOG = {
    "restart_service": {
        "label": "Restart a service", "targets": list(SERVICES), "params": {}, "delay_s": 8,
        "description": "Resets that service's in-memory state: in-flight work, retry state, its connections, "
                       "and for worker, the consumer.",
        "side_effects": "The service is unavailable for 8 s: customer requests fail (api), reads stall (ledger), "
                        "or orders wait (worker)."},
    "restart_all": {
        "label": "Restart everything", "targets": [None], "params": {}, "delay_s": 25,
        "description": "Restarts api, worker and ledger, and empties jobs. The simulated queue is not persistent.",
        "side_effects": "Full outage for 25 s. Every queued order is lost."},
    "recycle_pool": {
        "label": "Recycle ledger's database connections", "targets": ["ledger"], "params": {}, "delay_s": 5,
        "description": "Closes and reopens every ledger.db connection, reclaiming any that are stuck.",
        "side_effects": "In-flight ledger queries fail during the recycle."},
    "set_feature_flag": {
        "label": "Set a feature flag", "targets": ["receipt_export", "checkout_banner"],
        "params": {"enabled": [True, False]}, "delay_s": 3,
        "description": "Turns that code path on or off.",
        "side_effects": "receipt_export off: receipt exports return 'temporarily unavailable'. checkout_banner: none."},
    "set_retry_policy": {
        "label": "Set a retry policy", "targets": ["api", "worker"],
        "params": {"mode": ["backoff", "aggressive"]}, "delay_s": 5,
        "description": "Changes how that caller retries ledger calls.",
        "side_effects": "aggressive amplifies load whenever ledger struggles."},
    "quarantine_head_message": {
        "label": "Quarantine the head message", "targets": ["jobs"], "params": {}, "delay_s": 2,
        "description": "Moves the message at the head of jobs to jobs.dlq.",
        "side_effects": "If that message was a healthy order, the order is lost."},
    "purge_queue": {
        "label": "Purge jobs", "targets": ["jobs"], "params": {}, "delay_s": 3,
        "description": "Deletes every message in jobs.",
        "side_effects": "Every queued order is lost."},
}
TARGETS = sorted({t for spec in CATALOG.values() for t in spec["targets"] if t})


def catalog(costs: dict) -> list[dict]:
    """GET /api/actions/catalog: every action with its cost, delay, targets and params."""
    return [{"type": kind, **spec, "cost": costs[kind], "sandbox": "Simulated action: affects only this sandbox."}
            for kind, spec in CATALOG.items()]


def invalid(kind: str, target, params: dict) -> str | None:
    """Why this (type, target, params) is not in the catalog, or None if it is."""
    spec = CATALOG[kind]
    if target not in spec["targets"]:
        return f"{kind} takes no target" if spec["targets"] == [None] else f"{kind} targets are {spec['targets']}"
    if set(params) != set(spec["params"]):
        return f"{kind} params must be exactly {sorted(spec['params'])}"
    for name, allowed in spec["params"].items():
        if params[name] not in allowed or type(params[name]) is not type(allowed[0]):  # True is not 1
            return f"{name} must be one of {allowed}"
    return None


def needs_up(kind: str, target) -> tuple:
    """The simulated services that must not be Restarting for this action to be accepted (§10.3)."""
    return {"restart_service": (target,), "restart_all": SERVICES, "recycle_pool": ("ledger",),
            "set_retry_policy": (target,)}.get(kind, ())


def effect_class(matrix: dict, kind: str, target, params: dict) -> str:
    """This action's row in the scenario's effect matrix (§10.2): exact, then `*` for the value or the target."""
    value = {"set_feature_flag": lambda: "on" if params["enabled"] else "off",
             "set_retry_policy": lambda: params["mode"]}.get(kind)
    if kind == "restart_all":
        keys = ["restart_all"]
    elif value is None:
        keys = [f"{kind}({target})"]
    else:
        keys = [f"{kind}({target}, {value()})", f"{kind}({target}, *)", f"{kind}(*, {value()})"]
    return next(matrix[k] for k in keys if k in matrix)  # the pack loader requires every row (SCN-01)


def sandbox_target(target) -> str:
    return f"sim/{target}" if target else "sim"
