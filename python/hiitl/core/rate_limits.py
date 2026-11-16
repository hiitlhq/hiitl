"""Rate-limit rules as limiter configs, and the set-level form compiled to rules (policy_format.md "Rate-limit rules";
decision_response.md `rate_limit_rules`; R-0852; T47 — one rate-window representation, the rule's). One definition,
read by the policy-set model, the SDK's in-memory limiter and the hosted service's limiter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from hiitl.core.error_decisions import MESSAGES
from hiitl.core.types import Decision, ErrorDetail, MatchedRule, RateLimit, Remediation

# A rule's scope -> the limiter's scope-key form.
RULE_SCOPE = {"action": "tool", "agent": "agent_id", "user": "user", "org": "org", "user_action": "user:tool"}

# The set-level form (`metadata.rate_limits`) -> the rule's terms (policy_format.md 2.2, the compile table).
SET_SCOPE = {"org": "org", "agent_id": "agent", "agent": "agent", "user": "user", "user_id": "user",
             "tool": "action", "org:tool": "action", "user:tool": "user_action"}
WINDOW_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
# what the limiter applied when an entry left a key out: the same throttle, compiled
SET_DEFAULTS = {"scope": "org", "window": "hour", "limit": 1000}
_ENTRY_KEYS = ("scope", "limit", "window", "window_seconds")


def rule_limit_config(r: Any) -> dict:
    """A matching windowed RATE_LIMIT rule (an entry of Decision.rate_limit_rules) as a limiter config, counted under
    `rule:<name>:<scope key>`; `rule` rides along so an exceeded limit names it."""
    return {"scope": RULE_SCOPE[r.scope], "limit": r.limit, "window_seconds": r.window_seconds,
            "window": f"{r.window_seconds}s", "key_prefix": f"rule:{r.rule_name}:", "rule": r}


def counter_state(rule: Any, current: int, reset_at: datetime) -> RateLimit:
    """A windowed rule's counter state (decision_response.md **Rate Limit Counter State**): the rule's scope, its
    window as `<window_seconds>s`, its limit, the calls the window holds, and when its oldest call leaves it."""
    return RateLimit(scope=rule.scope, window=f"{rule.window_seconds}s", limit=rule.limit, current=current,
                     reset_at=reset_at)


def tightest(states: Iterable[RateLimit]) -> RateLimit:
    """The window with the least headroom left (`limit - current`); on a tie, the first listed (R-0008: "Decisions
    must include current counter state snapshot" — one snapshot, the window nearest its limit)."""
    return min(states, key=lambda s: s.limit - s.current)


def with_counter(rem: Remediation, state: RateLimit) -> Remediation:
    """A `rate_limit` remediation's details are the exceeded window's counter state (policy_format.md **Remediation
    on Rules**); every other type is the rule's as written."""
    if rem.type != "rate_limit":
        return rem
    return rem.model_copy(update={"details": {**(rem.details or {}), **state.model_dump(mode="json")}})


def limit_exceeded(decision: Decision, rule: Any, current: int, reset_at: datetime) -> Decision:
    """The evaluation's decision, refused by `rule`'s window (policy_format.md **Rate-limit rules**): RATE_LIMIT /
    RATE_LIMIT_EXCEEDED, the rule in `matched_rules`, its counter state and its own remediation. A copy, so nothing
    the evaluation recorded (staged observations, the listed windows, the envelope hash) is dropped."""
    state = counter_state(rule, current, reset_at)
    return decision.model_copy(update={
        "decision": "RATE_LIMIT", "allowed": False, "reason_codes": ["RATE_LIMIT_EXCEEDED"],
        "matched_rules": [MatchedRule(rule_name=rule.rule_name, policy_set=rule.policy_set, priority=rule.priority)],
        "rate_limit": state,
        "remediation": with_counter(rule.remediation, state) if rule.remediation else None,
    })


def limiter_failed(decision: Decision) -> Decision:
    """A limiter that failed never lets the call through: an ambiguous failure blocks (safe by default). BLOCK /
    RATE_LIMIT_SERVICE_ERROR with an authored `error`, in the hosted service and the SDK alike; the caller logs the
    cause, which the message never carries (error_decisions.MESSAGES). A copy of the evaluation's ALLOW, as a refusal
    is: no rule decided it, and no window was read."""
    return decision.model_copy(update={
        "decision": "BLOCK", "allowed": False, "reason_codes": ["RATE_LIMIT_SERVICE_ERROR"],
        "matched_rules": None, "rate_limit": None, "remediation": None,
        "error": ErrorDetail(code="RATE_LIMIT_SERVICE_ERROR", message=MESSAGES["RATE_LIMIT_SERVICE_ERROR"]),
    })


def compiled_name(i: int) -> str:
    return f"metadata.rate_limits[{i}]"


def compile_set_limits(data: Any) -> Any:
    """A policy set's `metadata.rate_limits`, compiled to windowed RATE_LIMIT rules (T47). Entry i becomes the active
    rule `metadata.rate_limits[i]` matching every envelope, carrying its entry in `metadata.compiled_from`; the entry
    leaves the set's metadata — nothing is dropped. An entry key, scope or window outside the table is refused with
    the allowed values (the limiter used to fall back to the org scope or an hour without a word)."""
    if not isinstance(data, dict):
        return data
    meta = data.get("metadata")
    if not isinstance(meta, dict) or "rate_limits" not in meta:
        return data
    entries = meta["rate_limits"]
    entries = entries if isinstance(entries, list) else [entries]
    rules = list(data.get("rules") or [])
    how = "write the throttle as a RATE_LIMIT rule with `rate_limit: {limit, window_seconds, scope}` (policy_format.md " \
          "\"Rate-limit rules\")"
    compiled = []
    for i, e in enumerate(entries):
        path = compiled_name(i)
        if not isinstance(e, dict):
            raise ValueError(f"{path}: a set-level rate limit is an object with {', '.join(_ENTRY_KEYS)}; {how}")
        extra = sorted(set(e) - set(_ENTRY_KEYS))
        if extra:
            raise ValueError(f"{path}: {', '.join(map(repr, extra))} is not a set-level rate-limit key (allowed: "
                             f"{', '.join(_ENTRY_KEYS)}); {how}")
        scope = e.get("scope", SET_DEFAULTS["scope"])
        if scope not in SET_SCOPE:
            raise ValueError(f"{path}: scope {scope!r} is not one of {', '.join(SET_SCOPE)}; {how}")
        if "window_seconds" in e:
            window_seconds = e["window_seconds"]
        else:
            window = e.get("window", SET_DEFAULTS["window"])
            if window not in WINDOW_SECONDS:
                raise ValueError(f"{path}: window {window!r} is not one of {', '.join(WINDOW_SECONDS)} (or give "
                                 f"window_seconds); {how}")
            window_seconds = WINDOW_SECONDS[window]
        compiled.append({
            "name": path, "priority": 0, "lifecycle_stage": "active",
            "description": f"the set-level throttle {path}, compiled to a rule on load (T47)",
            "conditions": {"field": "action", "operator": "exists", "value": True},
            "decision": "RATE_LIMIT", "reason_code": "RATE_LIMIT_EXCEEDED",
            "rate_limit": {"limit": e.get("limit", SET_DEFAULTS["limit"]), "window_seconds": window_seconds,
                           "scope": SET_SCOPE[scope]},
            "metadata": {"compiled_from": {"path": path, "entry": e}},
        })
    rest = {k: v for k, v in meta.items() if k != "rate_limits"}
    return {**data, "rules": rules + compiled, "metadata": rest}
