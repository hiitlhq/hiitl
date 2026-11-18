"""A sync route's answer re-entering evaluation (policy_format.md 2.7 "Enrichment context"; routes.md "A sync route's
answer re-enters evaluation"; decision_response.md 1.7; TICKET-046 with TICKET-032's sync half).

Pure: the steps decide which route to ask, what to send, which of the answer's fields re-enter and what a missing
answer does. The asking itself (HTTP from the SDK, a sync job on the hosted service) is the caller's, injected as
`ask(route, payload) -> body`, raising `RouteUnanswered` when there is no answer. Two drivers share the steps: a
synchronous one (the SDK) and an asynchronous one (the hosted service).
"""

from __future__ import annotations

import inspect
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

from .route_types import RouteAuth
from .types import Decision, RouteAsked

UNANSWERED = "ROUTE_UNANSWERED"
SYNC_DIRECTION = "bidirectional"
DEFAULT_TIMEOUT_SECONDS = 30.0
_UNITS = {"s": 1, "m": 60, "h": 3600}
# routes.md Validation Rules, "The party that sends reads the `auth`": the types an SDK sends, and the one form of
# reference it resolves, a variable of its own process written `env:<NAME>`.
SENT_AUTH = ("bearer_token", "api_key")
SECRET_REF_SCHEME = "env"
RECEIVING_DIRECTION = "inbound"


class RouteUnanswered(Exception):
    """The route gave no answer: a timeout, an error response, or a body that is not an object."""


def _get(route: Any, key: str, default: Any = None) -> Any:
    if route is None:
        return default
    if isinstance(route, Mapping):
        return route.get(key, default)
    v = getattr(route, key, default)
    if hasattr(v, "model_dump"):
        return v.model_dump(mode="json")
    return v.value if hasattr(v, "value") else v


def _name(route: Any) -> str:
    return str(_get(route, "name"))


def endpoint(route: Any) -> str:
    return str(_get(route, "endpoint") or "")


def is_sync(route: Any) -> bool:
    d = _get(route, "direction")
    return (d.value if hasattr(d, "value") else d) == SYNC_DIRECTION


def _sensitivity(record: Mapping) -> List[Any]:
    envelope = record.get("envelope")
    held = envelope.get("sensitivity") if isinstance(envelope, Mapping) else None
    return list(held) if isinstance(held, list) else []


# What an outbound route's filter reads of the record it is sent, per key (routes.md "Outbound routes and filters";
# HTL-29 row 131): the record's own values for the key, as stored. The keys are RouteFilters' fields.
FILTER_READS: Dict[str, Callable[[Mapping], List[Any]]] = {
    "decisions": lambda record: [record.get("decision_type")],
    "actions": lambda record: [record.get("action")],
    "agents": lambda record: [record.get("agent_id")],
    "sensitivity": _sensitivity,
}


def receives(route: Any, record: Mapping) -> bool:
    """Whether an outbound route receives the record: each key its `filters` declares lists one of the record's values
    for that key. A route with no filters receives every record."""
    filters = _get(route, "filters") or {}
    return all(any(v in listed for v in FILTER_READS[key](record)) for key, listed in filters.items()
               if listed is not None)


def to_ask(decision: Decision, route_of: Callable[[str], Any], asked: set) -> Optional[tuple]:
    """(route, rule name) when the decision is a ROUTE whose rule names a sync route not yet asked; else None."""
    dt = decision.decision.value if hasattr(decision.decision, "value") else decision.decision
    if dt != "ROUTE" or not decision.route_ref or decision.route_ref in asked:
        return None
    route = route_of(decision.route_ref)
    if not is_sync(route):
        return None
    rule = decision.matched_rules[0].rule_name if decision.matched_rules else ""
    return route, rule


def _at(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def payload(route: Any, rule: str, envelope: Mapping) -> dict:
    """{route, rule, action, fields}: the values at the route's `context.fields` paths, or the whole envelope."""
    ctx = _get(route, "context") or {}
    paths = [f.get("field_path") if isinstance(f, Mapping) else getattr(f, "field_path", None)
             for f in (ctx.get("fields") or [])]
    paths = [p for p in paths if p]
    body = {"route": _name(route)}
    if ctx.get("include_policy_ref", True):
        body["rule"] = rule
    body["action"] = envelope.get("action")
    body["fields"] = {p: _at(envelope, p) for p in paths} if paths else dict(envelope)
    return body


def declared(route: Any) -> tuple[List[str], List[str]]:
    rs = _get(route, "response_schema") or {}
    return list(rs.get("required_fields") or []), list(rs.get("optional_fields") or [])


def answer_fields(route: Any, body: Any) -> Dict[str, Any]:
    """The answer's declared fields; RouteUnanswered when it is not an object or lacks a declared required field."""
    if not isinstance(body, Mapping):
        raise RouteUnanswered("the answer is not a JSON object")
    required, optional = declared(route)
    missing = [f for f in required if body.get(f) is None]
    if missing:
        raise RouteUnanswered("the answer lacks the required field(s) " + ", ".join(f"`{f}`" for f in missing))
    return {f: body[f] for f in required + optional if f in body and body[f] is not None}


def timeout_seconds(route: Any) -> float:
    m = re.fullmatch(r"(\d+)([smh])", str((_get(route, "sla") or {}).get("timeout") or ""))
    return float(int(m.group(1)) * _UNITS[m.group(2)]) if m else DEFAULT_TIMEOUT_SECONDS


def fails_open(route: Any) -> bool:
    """`fail_open` alone; `fail_closed`, and `escalate` / `extend` until escalation ladders exist, fail closed."""
    return (_get(route, "sla") or {}).get("timeout_action") == "fail_open"


def auth_refusal(route: Any, environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Why the SDK cannot send the `auth` a sending route declares, or None when it can or the route declares none
    (routes.md Validation Rules, "The party that sends reads the `auth`"): a type it does not send, a reference that is
    not `env:<NAME>`, or a variable unset or empty in this process. An inbound route's `auth` is what the sender
    presents to hiitl, so it is not read here."""
    auth = _get(route, "auth")
    direction = _get(route, "direction")
    if not auth or (direction.value if hasattr(direction, "value") else direction) == RECEIVING_DIRECTION:
        return None
    environ = os.environ if environ is None else environ
    name, kind, ref = _name(route), auth.get("type"), str(auth.get("secret_ref") or "")
    if kind not in SENT_AUTH:
        return (f"route '{name}' declares auth type {kind!r}, which the SDK does not send. It sends "
                f"{' or '.join(SENT_AUTH)}, read from a variable of its own process (routes.md, \"The party that "
                f"sends reads the `auth`\").")
    scheme, colon, var = ref.partition(":")
    if scheme != SECRET_REF_SCHEME or not colon or not var:
        return (f"route '{name}' reads its secret from {ref!r}. The SDK reads a variable of its own process, written "
                f"'{SECRET_REF_SCHEME}:<NAME>', e.g. secret_ref: \"{SECRET_REF_SCHEME}:ROUTE_TOKEN\".")
    if not environ.get(var):
        return (f"route '{name}' reads its secret from {var}, which is unset or empty in this process. Set {var}, "
                f"or remove the route's auth if its endpoint takes none.")
    return None


def auth_headers(route: Any, environ: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The header carrying the secret the route's `auth` declares, `{}` when it declares none. A request never goes
    without the credential its route declares: when the SDK cannot send it, RouteUnanswered names why, and the
    route's SLA decides."""
    reason = auth_refusal(route, environ)
    if reason:
        raise RouteUnanswered(reason)
    auth = _get(route, "auth")
    if not auth:
        return {}
    environ = os.environ if environ is None else environ
    secret = environ[str(auth["secret_ref"]).partition(":")[2]]
    header = auth.get("header") or RouteAuth.model_fields["header"].default
    return {header: f"Bearer {secret}" if auth.get("type") == "bearer_token" else secret}


class _Loop:
    """The steps' shared state: the enrichment context, the routes asked, and the outcome of one answer."""

    def __init__(self) -> None:
        self.enrichment: Dict[str, Dict[str, Any]] = {}
        self.routes: List[RouteAsked] = []
        self.asked: set = set()
        self.closed = False

    def take(self, route: Any, rule: str, body: Any, error: Optional[str]) -> None:
        name = _name(route)
        if error is None:
            try:
                fields = answer_fields(route, body)
            except RouteUnanswered as e:
                error = str(e)
        if error is None:
            self.enrichment[name] = fields
            self.routes.append(RouteAsked(rule_name=rule, route=name, outcome="answered", fields=list(fields)))
        elif fails_open(route):
            self.enrichment[name] = {}
            self.routes.append(RouteAsked(rule_name=rule, route=name, outcome="failed_open", fields=[], error=error))
        else:
            self.routes.append(RouteAsked(rule_name=rule, route=name, outcome="unanswered", error=error))
            self.closed = True

    def finish(self, decision: Decision) -> Decision:
        if not self.routes:
            return decision
        update: Dict[str, Any] = {"routes": self.routes, "enrichment": self.enrichment or None}
        if self.closed and UNANSWERED not in decision.reason_codes:
            update["reason_codes"] = list(decision.reason_codes) + [UNANSWERED]     # fail closed: ROUTE stays
        return decision.model_copy(update=update)


def evaluate_with_routes(evaluate: Callable[[Optional[dict]], Decision], route_of: Callable[[str], Any],
                         ask: Callable[[Any, dict], Any], envelope: Mapping,
                         first: Optional[Decision] = None) -> Decision:
    """Evaluate (or take `first`, the evaluation already made); while the decision asks a sync route not yet asked, ask
    it and evaluate again (each route once)."""
    loop = _Loop()
    decision = first if first is not None else evaluate(None)
    while not loop.closed:
        nxt = to_ask(decision, route_of, loop.asked)
        if nxt is None:
            break
        route, rule = nxt
        loop.asked.add(_name(route))
        body, error = None, None
        try:
            body = ask(route, payload(route, rule, envelope))
        except RouteUnanswered as e:
            error = str(e) or "no answer"
        loop.take(route, rule, body, error)
        if not loop.closed:
            decision = evaluate(loop.enrichment)
    return loop.finish(decision)


async def evaluate_with_routes_async(evaluate: Callable[[Optional[dict]], Decision], route_of: Callable[[str], Any],
                                     ask: Callable[[Any, dict], Awaitable[Any]], envelope: Mapping,
                                     first: Optional[Decision] = None) -> Decision:
    """`evaluate_with_routes` with an asynchronous ask (the hosted service's sync job); `route_of` may be async."""
    loop = _Loop()
    decision = first if first is not None else evaluate(None)
    while not loop.closed:
        route = route_of(decision.route_ref) if decision.route_ref else None
        if inspect.isawaitable(route):
            route = await route
        nxt = to_ask(decision, lambda _name, _route=route: _route, loop.asked)
        if nxt is None:
            break
        route, rule = nxt
        loop.asked.add(_name(route))
        body, error = None, None
        try:
            body = await ask(route, payload(route, rule, envelope))
        except RouteUnanswered as e:
            error = str(e) or "no answer"
        loop.take(route, rule, body, error)
        if not loop.closed:
            decision = evaluate(loop.enrichment)
    return loop.finish(decision)
