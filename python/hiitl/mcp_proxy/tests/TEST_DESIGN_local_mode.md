# Test Design: the MCP gateway in local mode (HTL-18)

**Created:** 2026-11-03 · **Box:** the system architecture's "MCP proxy", with "SDK" (local) and "Routes" (proposed).
**Spec:** HTL-18. Its sentence: "No new concept: the gateway is the SDK's caller; it exposes the SDK's own
configuration". Its rule: "with a policy file and no API key the client runs `RESPECT_POLICY`".
`routes.md` "A sync route's answer re-enters evaluation" (the SDK asks the route in local mode). `sdk/config.py` names
the key's variable, `HIITL_SIGNATURE_KEY`.

**Ruled 2026-11-04 (Trevor, HTL-18 review):**
- Row 126: `evaluate()` runs off the event loop (`asyncio.to_thread`), by the third core design principle: "ECP must never become
  the bottleneck."
- Row 128: the gateway reads `HIITL_API_KEY` when the YAML sets no key, by the same "by environment" the signature key
  takes. The recipes drop the `${HIITL_API_KEY}` literal, which loads as that string and starts hybrid mode with a fake
  key. The read sits in `load_config`, where "the YAML sets no key" is known, so the SDK client and the review flow read
  one key. The config module's own sentence (Block 3a, a6f5565): "A config file declares the hiitl API key (optional —
  defaults to env HIITL_API_KEY / local-mode when absent)".

## Purpose

Until now, the gateway built its SDK client from an API key or from nothing. So a deployment with no hosted service had
a gateway that observed every call and enforced none.

These cells prove four things about a gateway started from a YAML config with a policy file, route files and no API key:
- It enforces: a `BLOCK` rule returns the structured error, and the upstream is never called.
- A `ROUTE` rule's sync route is asked, and its answer decides.
- The record lands where the config says.
- The hybrid path is what it was.

The cells build a real `HIITL` from `load_config` through `hiitl_kwargs`, the path `run_proxy` takes. The fake parts
are these:
- The upstream is an in-memory MCP server.
- The route is a real HTTP endpoint on 127.0.0.1, served from its own thread. The SDK asks it synchronously, so a
  server on the gateway's event loop could never answer.

## Critical behaviours (each a cell, `test_local_mode.py`)

| # | Behaviour | Success |
|---|---|---|
| G1 | A `BLOCK` rule in the policy file binds at the gateway | `isError`, "blocked by hiitl policy" and the rule's reason code; the upstream not called; the BLOCK row in the configured audit file |
| G2 | A `ROUTE` rule's sync route is asked; its answer decides | the route receives `{route, rule, action, fields}` with its declared field; `deny` → BLOCK with the deny rule's reason, upstream not called; `approve` → forwarded with the arguments; the record carries the route `answered` |
| G3 | A route that does not answer fails closed at the gateway | 503 → the ROUTE text with `ROUTE_UNANSWERED`; upstream not called |
| G4 | The kwargs pass the SDK's own configuration | policy file, no key → `RESPECT_POLICY` and the three paths; `mode: OBSERVE_ALL` set → it wins (a policy file observed); no policy file → zero-config, no `mode`, no paths |
| G5 | The signature key comes from the environment, never the file | `HIITL_SIGNATURE_KEY` → the recorded envelope verifies under it through the one signed form, not zeros; `signature_key:` in the YAML is rejected |
| G6 | Hybrid is unchanged | with an api_key and no local field, the kwargs equal the pre-HTL-18 dict exactly (the T-134 cell in `test_config.py` and the in-memory suite are the rest) |
| G7 | A mode that is not one of the two is a config error | `mode: observe` → the error names `OBSERVE_ALL` and `RESPECT_POLICY` (the evaluator reads any other string as enforce) |
| G8 | A route's wait does not stall the gateway (row 126) | while a route takes 1.5 s, `list_tools` answers before the route does, and the call the route approved still runs (the strict xfail of #4's first head, removed) |
| G9 | The gateway reads `HIITL_API_KEY` when the file sets none (row 128) | no key in the file, the variable set → the config's key is the variable's (the review flow reads that field) and the kwargs are hybrid; a key in the file wins; the variable unset or empty → no key, local |
| G10 | Every gateway config a text carries loads to the mode it names (row 128's class) | the members are read by what they are: every YAML file or fenced YAML block in the repository whose top-level `servers` is a map of upstreams. Each carries no `${…}` value, which the loader would read as written; each loads local without `HIITL_API_KEY` and hybrid with it. The package's own README and recipes must be among the members, so a broken walk fails |

Each rule's mutation row (`g18-*`, and `r126-*` / `r128-*` for the rulings) is in the contract's mutation record. Each targets
the cell above that names the rule.

## Gaps (not tested here)

- PAUSE / REQUIRE_APPROVAL / ESCALATE without a server stay the structured block of
  `test_proxy_integration.py::test_call_tool_pause_maps_to_block_with_future_update_text`, unchanged.
- The real-stdio form (the CLI as a subprocess) runs in the PR's behavioural trace, not as a default cell, because
  `test_real_stdio.py` is gated on `npx`.
- Relative paths resolve against the process's working directory (the SDK's semantics), and the README shows absolute
  paths. No cell pins the working directory an MCP client chooses.
- G5 re-derives the signature from the record alone through `hiitl.core.canonical.envelope_verifies`, the one signed
  form (row 127, ruled 2026-11-04, built in HTL-20 under row 134). Before it, the SDK signed the timestamp's
  `isoformat()` and recorded it with `Z`, and G5 re-derived the form by hand.
- An upstream's `env` is read as written. The upstream gets that `env`, each `secret_refs` variable read from the
  gateway's environment at start, and the MCP client library's safe defaults (PATH, HOME and the like), never the
  rest of the gateway's environment. Row 157 (ruled 2026-11-05) is the reference: its cells are `test_row157.py`, and
  its text cell reads G10's walk.
