# Test Design: a sync route's answer re-enters evaluation (TICKET-046 with TICKET-032's sync half)

**Created:** 2026-10-11 · **Spec:** `policy_format.md` 2.7 "Enrichment context"; `decision_response.md` 1.7
(`route_ref` on ROUTE, `enrichment`, `routes`); `routes.md` "A sync route's answer re-enters evaluation". A ROUTE
becomes an external decision once its answer is read, the answer meets the rule's route dependency, and the dependency
names the path. Ruled: Trevor, 2026-10-11 (R-0905: the answer re-enters as `external.<source>.<field>`; a ROUTE
enforces once the answer is read).

## Purpose

Until now a `ROUTE` decision was terminal. Every rule reading `external.*` was hollow: a condition the evaluator could
never satisfy, gated so it could never be promoted. These cells prove five things:
- A sync route's answer reaches the rules that read it, and nothing else does: no caller-supplied value, and no
  undeclared field.
- The decision is deterministic: each route is asked once, then the envelope is evaluated again.
- An unanswered route fails closed unless its SLA says otherwise.
- The record shows which external decision the action read.
- The record is what lets a ROUTE enforce (the instrument) and what meets a rule's route dependency (promotion).

## Critical behaviours (each a cell)

| # | Behaviour | Where | Success |
|---|---|---|---|
| E1 | `external.<source>.<field>` resolves against the enrichment context beside the envelope, both evaluators | conformance `enrichment/` | an answered field decides; another value does not |
| E2 | An absent field is false (`exists = false` excepted) | conformance | `{content-check: {}}` → the reading rule does not match; `exists false` matches |
| E3 | A ROUTE decision carries its rule's `route` as `route_ref`, not allowed | conformance | `route_ref = content-check` |
| E4 | A ROUTE rule whose route has answered does not match again | conformance | with the answer, the next rule decides |
| E5 | Routes compose by data flow | conformance | answer a → ROUTE to b; answers a, b → the rule reading both decides |
| E6 | The envelope cannot carry `external` | core unit | a caller's `external` key is refused by the envelope model, naming it (R-0872, row 147); no rule reads it |
| E7 | The loop asks each route once and evaluates again; the last decision is the decision | core routing unit (Python, TS) | one ask per route; an answer that satisfies nothing does not re-ask |
| E8 | Only declared fields re-enter; a missing required field is no answer | core routing unit | an undeclared field is absent; a missing required field → unanswered |
| E9 | No answer: `fail_closed` (default, also `escalate` / `extend`) keeps ROUTE with `ROUTE_UNANSWERED`; `fail_open` evaluates again with nothing, other rules still bind | core routing unit | `routes[].outcome` unanswered / failed_open |
| E10 | The payload is the route's context: the `context.fields` paths (or the envelope), `rule` unless `include_policy_ref` is false, auth from `secret_ref` | core routing unit + SDK cells | the body and header the route receives |
| E11 | The SDK (local and hybrid) asks the route over HTTP, records the enriched decision | Python SDK, TS SDK | a mock transport answers; the audit record's decision carries `enrichment` and `routes` |
| E12 | The hosted service asks through a `sync` job and waits | backend | the worker POSTs to `endpoint`; the response body re-enters; the audit record carries it |
| E13 | A ROUTE enforces once its answer is read | instrument | `routes` answered + rule active → `enforced` on external_decision; unanswered / failed_open → nothing |
| E14 | The route dependency names the path and is met by a record carrying it in its enrichment | generate, instrument `met`, lint | `{route, external.x.y}`; met → promotable; an envelope carrying `external` meets nothing |
| E15 | No regression on the hot path | benchmark | `evaluate()` without enrichment as before |

## Gaps (not tested here)

- Async routes filtering against the enriched state (TICKET-046's second criterion): no async route execution exists
  yet. This is Door B, with outbound routes.
- `escalate` / `extend` timeout actions read as `fail_closed` until escalation ladders are built (Door B).
- `external.hiitl.*` (hiitl's own record): nothing writes that source yet.
- The MCP proxy still maps a ROUTE that reaches it to its placeholder BLOCK. The SDK it calls has already asked the
  route, so a ROUTE reaches the proxy only unanswered.
