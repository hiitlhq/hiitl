"""Policy lint — deterministic analysis of a policy set before it is deployed: every generated set is linted for
always-allow, always-block, unreachable and priority-shadowed rules, and the loader validates a generated rule's
field paths.

Conservative by construction: a finding is reported only where it is provable over the fragment this analysis decides —
atomic conditions with `equals`, `not_equals`, `in`, `not_in`, the four comparisons and `exists`, combined by `all_of`,
`any_of` and `none_of`, read with the evaluator's own semantics (a field that is absent fails every operator but
`exists`). Any other operator is opaque: it may match or not, and nothing is claimed that depends on it. Pure: no I/O.

Codes (each finding carries a message that says what is wrong and what to do):
  UNREACHABLE           error    the rule can never match
  PRIORITY_SHADOWED     warning  an active rule never binds: a rule ranked above it matches whatever it matches
  ALWAYS_ALLOW          warning  the set allows every envelope
  ALWAYS_BLOCK          warning  the set allows no envelope
  UNDEFINED_FIELD       error    a condition reads (or a value references) a field the envelope does not define
  RATE_LIMIT_NO_WINDOW  warning  a RATE_LIMIT rule without a window blocks every call it matches
  RATE_LIMIT_BOTH_FORMS warning  the set carries metadata.rate_limits (compiled to rules on load, T47) and windowed
                                 RATE_LIMIT rules of its own — one representation, the rule's
  UNCALIBRATED          info     a bound is the typed placeholder — the rule cannot match or be promoted until set
  UNDECLARED            info     a value is the DECLARED placeholder — staff set it; until then no match, no promotion
  TEST_FAILED           error    a test the rule ships with does not hold
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from hiitl.core.json_values import json_equal
from hiitl.core.precedence import ALLOW_CLASS, FORBID_CLASS, decision_value, precedence_key
from hiitl.core.types import (  # noqa: F401
    DECLARED_KEY, ENVELOPE_RENAMED, ENVELOPE_SCHEMA_VERSION, PLACEHOLDER_KEY, field_ref, has_placeholder, placeholders)

_DNF_CAP = 64
_OPAQUE_OPS = {"contains", "not_contains", "starts_with", "ends_with", "matches", "conforms_to"}
_NEGATE = {"equals": "not_equals", "not_equals": "equals", "in": "not_in", "not_in": "in",
           "greater_than": "less_than_or_equal", "less_than_or_equal": "greater_than",
           "greater_than_or_equal": "less_than", "less_than": "greater_than_or_equal"}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str                       # error | warning | info
    message: str
    rule: Optional[str] = None
    related: Tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "rule": self.rule, "message": self.message,
                "related": list(self.related)}


# ── the envelope's fields (the model is the code's copy of envelope_schema.json) ─────────────────────────────

def _envelope_fields() -> tuple[set, set, dict]:
    from hiitl.core.types import Envelope
    names = set(Envelope.model_fields)
    required = {n for n, f in Envelope.model_fields.items() if f.is_required()}
    # fields that are objects with free keys, or typed objects with known keys (None = any key)
    nested: Dict[str, Optional[set]] = {"target": None, "parameters": None, "metadata": None}
    for name in ("cost_estimate", "principal"):
        f = Envelope.model_fields.get(name)
        if f is None:
            continue
        ann = f.annotation
        sub = getattr(ann, "model_fields", None)
        if sub is None:
            for arg in getattr(ann, "__args__", ()) or ():
                sub = getattr(arg, "model_fields", None) or sub
        nested[name] = set(sub) if sub else None
    # fields that always carry a value: the required ones, and those with a non-null default
    always = required | {"operation", "target", "parameters"}
    return names, always, nested


_ENUMS = {"environment": frozenset({"dev", "stage", "prod"}),
          "operation": frozenset({"read", "write", "create", "delete", "execute", "update"})}


# ── one field's domain: ABSENT ∪ {present values satisfying the constraints} ─────────────────────────────────

@dataclass(frozen=True)
class _Dom:
    absent: bool = True
    present: bool = True
    points: Optional[Tuple[Any, ...]] = None
    excl: Tuple[Any, ...] = ()
    lo: Optional[float] = None
    lo_inc: bool = True
    hi: Optional[float] = None
    hi_inc: bool = True
    opaque: Tuple[tuple, ...] = ()

    def meet(self, o: "_Dom") -> "_Dom":
        pts = self.points if o.points is None else (o.points if self.points is None else tuple(p for p in self.points if _member(p, o.points)))
        lo, lo_inc = self.lo, self.lo_inc
        if o.lo is not None and (lo is None or o.lo > lo or (o.lo == lo and not o.lo_inc)):
            lo, lo_inc = o.lo, o.lo_inc
        hi, hi_inc = self.hi, self.hi_inc
        if o.hi is not None and (hi is None or o.hi < hi or (o.hi == hi and not o.hi_inc)):
            hi, hi_inc = o.hi, o.hi_inc
        return _Dom(self.absent and o.absent, self.present and o.present, pts, _unique(self.excl + o.excl), lo, lo_inc,
                    hi, hi_inc, self.opaque + tuple(x for x in o.opaque if x not in self.opaque))


def _member(value: Any, points: Iterable[Any]) -> bool:
    return any(json_equal(value, point) for point in points)


def _unique(points: Iterable[Any]) -> Tuple[Any, ...]:
    kept: List[Any] = []
    for point in points:
        if not _member(point, kept):
            kept.append(point)
    return tuple(kept)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def _hashable(v: Any) -> bool:
    try:
        hash(v)
        return True
    except TypeError:
        return False


def _in_bounds(d: _Dom, v: Any) -> bool:
    if d.lo is None and d.hi is None:
        return True
    if not _num(v):
        return False
    if d.lo is not None and (v < d.lo or (v == d.lo and not d.lo_inc)):
        return False
    if d.hi is not None and (v > d.hi or (v == d.hi and not d.hi_inc)):
        return False
    return True


def _effective_points(d: _Dom, fld: str) -> Optional[Tuple[Any, ...]]:
    pts = d.points if d.points is not None else _ENUMS.get(fld)
    if pts is None:
        return None
    return tuple(p for p in pts if not _member(p, d.excl) and _in_bounds(d, p))


def _present_nonempty(d: _Dom, fld: str) -> bool:
    """False only when provably empty; opaque atoms are never counted as emptying."""
    if not d.present:
        return False
    pts = _effective_points(d, fld)
    if pts is not None:
        return bool(pts)
    if d.lo is not None and d.hi is not None:
        if d.lo > d.hi:
            return False
        if d.lo == d.hi:
            return d.lo_inc and d.hi_inc and not _member(d.lo, d.excl)
    return True


def _sat(d: _Dom, fld: str, always: set) -> bool:
    return (d.absent and fld not in always) or _present_nonempty(d, fld)


def _atom_dom(op: str, v: Any, negated: bool) -> Optional[_Dom]:
    """The domain of one atomic condition (or of its negation); None when the value has a shape the analysis does not
    read (it is then opaque)."""
    if op == "exists":
        want = bool(v) != negated
        return _Dom(absent=not want, present=want)
    if op in _OPAQUE_OPS or op not in _NEGATE or field_ref(v) is not None:   # a reference is not a constant (2.6)
        return _Dom(absent=negated, present=True, opaque=((op, repr(v), negated),))
    if negated:
        op = _NEGATE[op]
    base = _Dom(absent=negated)
    if op in ("equals", "not_equals"):
        if not _hashable(v):
            return None
        return replace(base, points=(v,)) if op == "equals" else replace(base, excl=(v,))
    if op in ("in", "not_in"):
        if not isinstance(v, (list, tuple, set, frozenset)) or not all(_hashable(x) for x in v):
            return None
        return replace(base, points=_unique(v)) if op == "in" else replace(base, excl=_unique(v))
    if not _num(v):
        return None
    return {"greater_than": replace(base, lo=v, lo_inc=False), "greater_than_or_equal": replace(base, lo=v),
            "less_than": replace(base, hi=v, hi_inc=False), "less_than_or_equal": replace(base, hi=v)}[op]


# ── conditions → disjunctive normal form over field domains ───────────────────────────────────────────────────

Conj = Dict[str, _Dom]


def _get(c: Any, k: str) -> Any:
    return c.get(k) if isinstance(c, dict) else getattr(c, k, None)


def _op(c: Any) -> str:
    o = _get(c, "operator")
    return o.value if hasattr(o, "value") else o


def _field(c: Any) -> str:
    return _get(c, "field")


def _and(a: Conj, b: Conj) -> Conj:
    out = dict(a)
    for k, d in b.items():
        out[k] = out[k].meet(d) if k in out else d
    return out


def dnf(cond: Any, negated: bool = False) -> Optional[List[Conj]]:
    """The condition as a list of conjunctions (OR of ANDs), or None where it exceeds what is decided."""
    if cond is None:
        return [{}] if not negated else []
    all_of, any_of, none_of = _get(cond, "all_of"), _get(cond, "any_of"), _get(cond, "none_of")
    if all_of is None and any_of is None and none_of is None:
        d = _atom_dom(_op(cond), _get(cond, "value"), negated)
        if d is None:
            return None
        return [{_field(cond): d}]
    if none_of is not None:                               # NOT(c1 OR …) = AND(NOT c1, …)
        kids, conj = none_of, not negated
    elif all_of is not None:
        kids, conj = all_of, not negated                  # NOT(AND) = OR(NOT …)
    else:
        kids, conj = any_of, negated
    child_neg = negated if none_of is None else not negated
    parts = [dnf(k, child_neg) for k in kids]
    if any(p is None for p in parts):
        return None
    if conj:
        out: List[Conj] = [{}]
        for p in parts:
            out = [_and(a, b) for a in out for b in p]
            if len(out) > _DNF_CAP:
                return None
        return out
    out = [c for p in parts for c in p]
    return out if len(out) <= _DNF_CAP else None


def satisfiable(conj: Conj, always: set) -> bool:
    return all(_sat(d, f, always) for f, d in conj.items())


def _dom_universal(d: _Dom, fld: str, always: set) -> bool:
    if d.opaque or d.excl or d.lo is not None or d.hi is not None or not d.present:
        return False
    if not d.absent and fld not in always:
        return False
    return d.points is None or (fld in _ENUMS and all(_member(p, d.points) for p in _ENUMS[fld]))


def universal(conjs: Optional[List[Conj]], always: set) -> bool:
    return conjs is not None and any(all(_dom_universal(d, f, always) for f, d in c.items()) for c in conjs)


def _dom_within(a: _Dom, b: _Dom, fld: str, always: set) -> bool:
    """Every value `a` admits, `b` admits (False when not provable)."""
    if a.absent and not b.absent and fld not in always:
        return False
    if not _present_nonempty(a, fld):
        return True
    if not b.present:
        return False
    if any(x not in a.opaque for x in b.opaque):
        return False
    pts = _effective_points(a, fld)
    if pts is not None:
        bp = _effective_points(b, fld)
        return all(_member(p, bp) if bp is not None else (not _member(p, b.excl) and _in_bounds(b, p)) for p in pts)
    if b.points is not None:
        return False
    if any(_in_bounds(a, x) and not _member(x, a.excl) for x in b.excl):
        return False
    if b.lo is not None:
        if a.lo is None or a.lo < b.lo or (a.lo == b.lo and a.lo_inc and not b.lo_inc):
            return False
    if b.hi is not None:
        if a.hi is None or a.hi > b.hi or (a.hi == b.hi and a.hi_inc and not b.hi_inc):
            return False
    return True


def _conj_within(a: Conj, b: Conj, always: set) -> bool:
    return all(_dom_within(a.get(f, _Dom()), d, f, always) for f, d in b.items())


def implies(a: Optional[List[Conj]], b: Optional[List[Conj]], always: set) -> bool:
    """Every envelope `a` matches, `b` matches (sound: False whenever not provable)."""
    if a is None or b is None:
        return False
    return all(any(_conj_within(x, y, always) for y in b) for x in a if satisfiable(x, always))


def can_comatch(a: Optional[List[Conj]], b: Optional[List[Conj]], always: set) -> bool:
    """Some envelope may match both (True whenever not provably disjoint)."""
    if a is None or b is None:
        return True
    return any(satisfiable(_and(x, y), always) for x, y in itertools.product(a, b))


# ── rule-level facts ─────────────────────────────────────────────────────────────────────────────────────────

def _stage(r: Any) -> str:
    s = getattr(r, "lifecycle_stage", "active")
    return s.value if hasattr(s, "value") else (s or "active")


def uncalibrated(rule: Any) -> bool:
    return bool(getattr(rule, "uncalibrated", False))


def binds(rule: Any) -> bool:
    """A rule that can bind a decision: not a windowed RATE_LIMIT rule (it meters; R-0852), not uncalibrated (it
    never matches)."""
    return not getattr(rule, "meters", False) and not uncalibrated(rule)


def _scope_within(a: Any, b: Any) -> bool:
    """Every envelope rule-scope `a` admits, `b` admits."""
    if b is None:
        return True
    for k in ("agents", "users", "environments"):
        bv = getattr(b, k, None)
        if bv is None:
            continue
        av = getattr(a, k, None) if a is not None else None
        if av is None or not set(av) <= set(bv):
            return False
    pb = getattr(b, "percentage", None)
    return pb is None or pb >= 100


def _scope_meets(a: Any, b: Any) -> bool:
    for k in ("agents", "users", "environments"):
        av, bv = (getattr(a, k, None) if a else None), (getattr(b, k, None) if b else None)
        if av is not None and bv is not None and not set(av) & set(bv):
            return False
    return True


def _timeless(r: Any) -> bool:
    return getattr(r, "valid_from", None) is None and getattr(r, "valid_to", None) is None


def _unscoped(r: Any) -> bool:
    s = getattr(r, "scope", None)
    return s is None or (all(getattr(s, k, None) is None for k in ("agents", "users", "environments"))
                         and (getattr(s, "percentage", None) in (None, 100)))


# the enrichment namespace the format defines beside the envelope's own fields, with how many names follow the prefix:
# enrichment context `external.<source>[.<field>]` (policy_format.md "Signal Reference Syntax"; a sync route's answer or
# hiitl's own record, `external.hiitl.*`; `session.*` was removed in 2.5)
_ENRICHMENT = {"external": (1, 2)}


def _field_problem(path: str, names: set, nested: dict, parameters: Optional[Iterable[str]]) -> Optional[str]:
    parts = path.split(".")
    if parts[0] in _ENRICHMENT:
        lo, hi = _ENRICHMENT[parts[0]]
        return None if lo <= len(parts) - 1 <= hi else \
            f"`{path}`: `{parts[0]}` paths take {lo}{'' if lo == hi else f' to {hi}'} name(s) after the prefix"
    head = parts[0]
    if head in ENVELOPE_RENAMED:                          # no alias from 2.0 (policy_format.md 2.17)
        return f"`{path}`: the envelope has no field `{head}` (the schema renamed it `{ENVELOPE_RENAMED[head]}`)"
    if head not in names:
        return f"`{path}`: the envelope has no field `{head}`"
    if len(parts) == 1:
        return None
    if head not in nested:
        return f"`{path}`: `{head}` is not an object, so it has no `{parts[1]}`"
    keys = nested[head]
    if head == "parameters" and parameters is not None:
        keys = set(parameters)
    if keys is not None and parts[1] not in keys:
        allowed = ", ".join(sorted(keys)) or "none"
        return f"`{path}`: `{head}` carries no `{parts[1]}` (it carries: {allowed})"
    return None


def _refs(cond: Any) -> List[str]:
    """The envelope paths a condition's field-reference values name (policy_format.md 2.6)."""
    if cond is None:
        return []
    out: List[str] = []
    for k in ("all_of", "any_of", "none_of"):
        kids = _get(cond, k)
        if kids is not None:
            for c in kids:
                out += _refs(c)
            return out
    ref = field_ref(_get(cond, "value"))
    return [ref] if isinstance(ref, str) else []


def _fields(cond: Any) -> List[str]:
    if cond is None:
        return []
    out: List[str] = []
    for k in ("all_of", "any_of", "none_of"):
        kids = _get(cond, k)
        if kids is not None:
            for c in kids:
                out += _fields(c)
            return out
    f = _get(cond, "field")
    return [f] if f else []


# ── the lint ────────────────────────────────────────────────────────────────────────────────────────────────

def rule_alone(rule: Any) -> Any:
    """A rule checked by itself (a generated card's gate, an edit's refusals), active, in a set of its own. The rule
    loads as a Rule, or this raises. The set holding it is written nowhere and applies to no org, so it names no scope:
    policy_format.md's Policy Set Fields are the fields of a set the repository writes (HTL-22 row 165), and the checks
    here read only its rules. Its version is the zero-config set's, `v0.0.0`, the version of a set no one wrote."""
    from hiitl.core.types import PolicySet, Rule
    loaded = Rule.model_validate({**(rule if isinstance(rule, dict) else rule.model_dump(exclude_unset=True)), "lifecycle_stage": "active"})
    return PolicySet.model_construct(name=f"alone:{loaded.name}", version="v0.0.0",
                                     description="A rule checked by itself", rules=[loaded])


def lint(policy: Any, *, parameters: Optional[Iterable[str]] = None, evaluator: Any = None) -> List[Finding]:
    """Lint one policy set (a PolicySet or its dict). `parameters`: the action's informed-envelope parameter names,
    when the rules are about one action (the generate path) — a `parameters.<name>` outside it is undefined."""
    from hiitl.core.types import PolicySet
    if not isinstance(policy, PolicySet):
        policy = PolicySet(**policy)
    names, always, nested = _envelope_fields()
    out: List[Finding] = []
    rules = list(policy.rules)
    live = [(i, r) for i, r in enumerate(rules) if _stage(r) in ("active", "staged")]
    forms = {id(r): dnf(r.conditions) for _, r in live}

    for i, r in live:
        f = forms[id(r)]
        for path in _fields(r.conditions):
            prob = _field_problem(path, names, nested, parameters)
            if prob:
                out.append(Finding("UNDEFINED_FIELD", "error", f"{prob} — the condition can never read a value. "
                                   "Use a field the envelope defines (docs/specs/envelope_schema.json), or add the "
                                   "field to the instrumented call's parameters first.", r.name))
        for path in _refs(r.conditions):                  # a field reference must be addressable (2.6)
            prob = _field_problem(path, names, nested, parameters)
            if prob:
                out.append(Finding("UNDEFINED_FIELD", "error", f"the reference {prob} — it can never resolve to a "
                                   "value. Reference a field the envelope defines (docs/specs/envelope_schema.json).",
                                   r.name))
        reason = None
        if f is not None and not any(satisfiable(c, always) for c in f):
            reason = "its conditions contradict each other"
        elif r.scope is not None and r.scope.percentage == 0:
            reason = "scope.percentage is 0"
        elif r.scope is not None and any(getattr(r.scope, k, None) == [] for k in ("agents", "users",
                                                                                     "environments")):
            reason = "a scope whitelist is empty"
        elif r.valid_from is not None and r.valid_to is not None and r.valid_from > r.valid_to:
            reason = "valid_from is after valid_to"
        if reason:
            out.append(Finding("UNREACHABLE", "error", f"rule `{r.name}` can never match: {reason}. Fix the "
                               "condition, or remove the rule.", r.name))
        if decision_value(r.decision) == "RATE_LIMIT" and getattr(r, "rate_limit", None) is None:
            out.append(Finding("RATE_LIMIT_NO_WINDOW", "warning", f"rule `{r.name}` is RATE_LIMIT with no window, so "
                               "it blocks every call it matches. Give it `rate_limit: {limit, window_seconds}`.",
                               r.name))
        held = placeholders(r.conditions) + placeholders(r.rate_limit)
        if any(k == PLACEHOLDER_KEY for k, _ in held):
            out.append(Finding("UNCALIBRATED", "info", f"rule `{r.name}` carries an uncalibrated bound: it cannot "
                               "match, and cannot be promoted, until the bound is set from a record (the code's own "
                               "constant or observed traffic).", r.name))
        declared = [w for k, w in held if k == DECLARED_KEY]
        if declared:
            out.append(Finding("UNDECLARED", "info", f"rule `{r.name}` waits on staff to declare "
                               f"{'; '.join(declared)}: it cannot match, and cannot be promoted, until they do.",
                               r.name))

    compiled = [r.name for r in policy.rules if ((r.metadata or {}).get("compiled_from"))]
    authored = [r.name for r in policy.rules if getattr(r, "rate_limit", None) is not None
                and not (r.metadata or {}).get("compiled_from")]
    if compiled and authored:
        out.append(Finding("RATE_LIMIT_BOTH_FORMS", "warning", f"the set carries `metadata.rate_limits` (compiled on "
                           f"load to {', '.join(compiled)}) and windowed RATE_LIMIT rules of its own "
                           f"({', '.join(authored)}): one representation, the rule's — write each set-level throttle "
                           "as a RATE_LIMIT rule (policy_format.md \"Rate-limit rules\").", None, tuple(compiled + authored)))

    active = [(i, r) for i, r in live if _stage(r) == "active" and binds(r)]
    ranked = sorted(active, key=lambda p: precedence_key(p[1], p[0]))
    for k, (i, r) in enumerate(ranked):
        fr = forms[id(r)]
        if fr is None or not any(satisfiable(c, always) for c in fr):
            continue
        for j, h in ranked[:k]:
            if (_timeless(h) or (h.valid_from == r.valid_from and h.valid_to == r.valid_to)) and \
                    _scope_within(r.scope, h.scope) and implies(fr, forms[id(h)], always):
                same = decision_value(h.decision) == decision_value(r.decision)
                out.append(Finding(
                    "PRIORITY_SHADOWED", "warning",
                    f"rule `{r.name}` never binds: `{h.name}` ({decision_value(h.decision)}) ranks above it and "
                    f"matches every envelope it matches" + (" — same decision, so it is redundant" if same else
                    f" — `{r.name}`'s {decision_value(r.decision)} never applies") + ". Narrow the rule above, or "
                    "remove this one.", r.name, (h.name,)))
                break

    tautologies = [(i, r) for i, r in ranked if _unscoped(r) and _timeless(r) and universal(forms[id(r)], always)]
    for i, t in tautologies:
        if decision_value(t.decision) in ALLOW_CLASS:
            above = [h for j, h in ranked if precedence_key(h, j) < precedence_key(t, i)]
            if all(decision_value(h.decision) in ALLOW_CLASS or
                   (forms[id(h)] is not None and not any(satisfiable(c, always) for c in forms[id(h)]))
                   for h in above):
                out.append(Finding("ALWAYS_ALLOW", "warning", f"the set allows every envelope: `{t.name}` matches "
                                   "everything and nothing that blocks or escalates ranks above it. If that is "
                                   "intended, ignore this; otherwise add the rules that should constrain it.",
                                   t.name))
            break
        if decision_value(t.decision) in FORBID_CLASS:
            out.append(Finding("ALWAYS_BLOCK", "warning", f"the set allows no envelope: `{t.name}` "
                               f"({decision_value(t.decision)}) matches everything and DENY wins. Narrow its "
                               "condition, or set it `disabled` until it should fire.", t.name))
            break
    else:
        allowing = [r for _, r in active if decision_value(r.decision) in ALLOW_CLASS and
                    (forms[id(r)] is None or any(satisfiable(c, always) for c in forms[id(r)]))]
        if not allowing:
            out.append(Finding("ALWAYS_BLOCK", "warning", "the set allows no envelope: no active rule allows "
                               "anything, so every call ends in a block (NO_MATCHING_RULE) or awaits a review. Add "
                               "the ALLOW rules for what the system may do.", None))

    if evaluator is not None:
        out += run_tests(policy, evaluator)
    return out


def run_tests(policy: Any, evaluator: Any) -> List[Finding]:
    """C7: each rule's shipped tests, evaluated against the rule alone, as active."""
    out: List[Finding] = []
    for r in policy.rules:
        for n, t in enumerate(getattr(r, "tests", None) or []):
            # the set with this rule alone, active: its version, description, scope and reading of an absent field kept
            alone = policy.model_copy(update={"name": f"test:{r.name}",
                                              "rules": [r.model_copy(update={"lifecycle_stage": "active"})]})
            env = t.envelope if isinstance(t.envelope, dict) else dict(t.envelope)
            got = evaluator.evaluate(_test_envelope(env), alone)
            matched = bool(got.matched_rules)
            want = t.expect
            ok = (not matched) if want == "NOT_MATCHED" else (matched and decision_value(got.decision) == want)
            if not ok:
                saw = decision_value(got.decision) if matched else "NOT_MATCHED"
                out.append(Finding("TEST_FAILED", "error", f"rule `{r.name}` test {n + 1}: expected {want}, got "
                                   f"{saw}. The rule does not do what its test says; fix the rule or the test.",
                                   r.name))
    return out


_TEST_DEFAULTS = {"schema_version": ENVELOPE_SCHEMA_VERSION, "org_id": "org_lint000000000000", "environment": "dev",
                  "agent_id": "lint", "action_id": "act_lint0000000000000000", "idempotency_key": "lint",
                  "timestamp": "2026-01-01T00:00:00Z", "signature": "0" * 64}


def _test_envelope(partial: dict) -> dict:
    return {**_TEST_DEFAULTS, **partial}


# ── the promotion gate ─────────────────────────────────────────────────────────────────────────────────────

_ERRORS = ("UNDEFINED_FIELD", "UNREACHABLE", "TEST_FAILED")


def promotion_refusal(policy: Any, rule_name: str, evaluator: Any = None,
                      met: Any = frozenset()) -> Optional[Tuple[str, str]]:
    """Why `rule_name` may not be promoted to active in `policy`, or None, in order: an unmet dependency
    (`RULE_DEPENDENCY_UNMET` — `met` holds the `(kind, target)` dependencies the caller has observed met), a value
    staff have not declared (`RULE_UNDECLARED`, naming it), an uncalibrated bound
    (`RULE_UNCALIBRATED`), a shipped test that does not hold (`RULE_TESTS_FAILED`), an
    error-level lint finding on the rule (`RULE_LINT_ERROR`). Each with a message saying what would let it promote."""
    from hiitl.core.evaluator import PolicyEvaluator
    from hiitl.core.types import PolicySet
    if not isinstance(policy, PolicySet):
        policy = PolicySet(**policy)
    rule = next((r for r in policy.rules if r.name == rule_name), None)
    if rule is None:
        return None
    w = rule.waits_on
    # hiitl's own record (external.hiitl.*) has no writer yet: never met. A route's answer is met when a record of an
    # action the rule binds carries the path the rule reads in its enrichment (policy format 2.7; TICKET-046).
    if w is not None and (w.kind == "hiitl_record" or (w.kind, w.target) not in met):
        if w.kind == "hiitl_record":
            return ("RULE_DEPENDENCY_UNMET", f"rule `{rule_name}` reads hiitl's own record (`external.hiitl.*`), "
                    f"which nothing writes yet ({w.target}); the rule cannot be promoted until it does.")
        how = {"verifier": "a verified `principal` on an envelope it binds — configure the SDK's principal_verifier and "
                           "pass the caller's token to evaluate(principal_token=…)",
               "route": f"the route's answer carrying `{w.target}` on a decision for an action it binds — connect the "
                        "sync route the policy's ROUTE rule names, so its answer re-enters"}.get(
            w.kind, f"`{w.target}` on an envelope it binds — pass it where the action is wrapped")
        return ("RULE_DEPENDENCY_UNMET", f"rule `{rule_name}` waits on the {w.kind.replace('_', ' ')} `{w.target}`; it "
                f"can be promoted once the instrument's record shows {how}.")
    held = placeholders(rule.conditions) + placeholders(rule.rate_limit)
    declared = [w for k, w in held if k == DECLARED_KEY]
    if declared:
        return ("RULE_UNDECLARED", f"rule `{rule_name}` waits on staff to declare {'; '.join(declared)}; it can be "
                "promoted once a kept edit sets it (a declared value, T49).")
    # an uncalibrated bound is checked after the dependency: the value it reads must arrive before it can be set
    if any(k == PLACEHOLDER_KEY for k, _ in held):
        return ("RULE_UNCALIBRATED", f"rule `{rule_name}` carries an uncalibrated bound; it can be promoted once the "
                "bound is set from a record — the code's own constant reaching the action, or observed traffic — as "
                "a new policy version.")
    alone = policy.model_copy(update={"rules": [rule]})
    failed = run_tests(alone, evaluator or PolicyEvaluator())
    if failed:
        return ("RULE_TESTS_FAILED", "; ".join(f.message for f in failed))
    errs = [f for f in lint(policy) if f.rule == rule_name and f.code in _ERRORS]
    if errs:
        return ("RULE_LINT_ERROR", "; ".join(f"{f.code}: {f.message}" for f in errs))
    return None
