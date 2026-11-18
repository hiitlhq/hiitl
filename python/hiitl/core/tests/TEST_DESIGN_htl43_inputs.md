# HTL-43 — Python supplied input types and owned writers

Design before cells, 2026-11-14. This lane starts at `f3da88dd`, after the
reviewed HTL-41 route-null merge. No production change or passing result is
claimed by this design. The parent owns the canonical declarations, independent
input corpus, register, mutation registry, full-suite run and final handoff.

## Sentence, source and box

Read today: the project workflow and conformance ontology §§1–6;
HTL-41 `13d5d855` and CC's full PR19 verdict `783ba4a0`; HTL-43's full rulings
`04ee6245`, `1c1611da`, and the superseding number read `d82fe0f5`.
The boxes are the customer's SDK assembly/validation and hosted SDK input and
owned writers in the system architecture §2 (**proposed**).

- `policy_format.md`, **No field is dropped**: a rule, set, condition, scope,
  remediation, rate window, shipped test and lineage object carry exactly the
  defined fields; an unknown field is refused with its name. “Free-form data
  goes in `metadata`.” The Envelope JSON Schema and Routes schema separately
  declare their object closure, typed children, arrays, maps and bounds.
- `routes.md`, **Explicit null and omission**: “A field supplied as `null` is
  not omitted.” The rule reaches typed array items, map values and typed
  children in open objects; untyped free-form values are not made non-null.
  HTL-41 `13d5d855` and HTL-43 extend this declared-type reading to all three
  formats, with the lineage tables already written from both SDKs' declarations.
- `policy_format.md`, **Tests shipped with a rule**: required envelope fields
  “are filled with fixed test values.” The nested envelope therefore has the
  same supplied-member types, closure and bounds, while omitted test defaults
  remain omitted until the existing lint evaluation supplies them.
- `policy_format.md`, **One representation: the rule's**: set-level rate limits
  are compiled when loaded, leaving the original entry in `compiled_from`.
  Validate the original declared list and its entries before preprocessing can
  erase or coerce their shape. Compilation still preserves the original data.
- `decision_response.md`, **Remediation Types**: the remediation type determines
  the details schema. Its custom type explicitly permits any valid JSON object.
  `policy_format.md`, **Remediation on Rules**, separately permits the computed
  `{ref, filter}` form for `field_restriction.blocked_fields` and copies a list
  as written. A field in one subtype never constrains custom data with that name.
- `ecp_evaluate_spec.md`: the SDK builds the envelope; only action is required;
  everything else is optional. HTL-43 `04ee6245`: “None stays 'not given'”,
  limited to the SDK's own optional arguments. Files, bodies and mappings retain
  their explicit null; null inside caller parameters remains data.
- HTL-43 `1c1611da`: “Keep every supplied key.” Open data's `__proto__`,
  `constructor` and `toString` are ordinary Python dictionary keys and must
  survive the Python half of the shared validation/evaluation/record proof.
- HTL-43 `d82fe0f5`: “Flat limit; tiny fractions read as zero.” The sibling
  numeric lane owns the single recursive held-value guard and declaration.
  This lane calls that guard before coercion or filtering, without copying its
  numeric bound or implementing a raw-token rule.

The original sparse-call design and internal-writer read are preserved in the
HTL-43 measurement evidence. The current producers read here are
`core/types.py`, `core/route_types.py`, `core/route_nulls.py`, `core/date_time.py`,
`core/lint.py`, `core/routing.py`, `sdk/client.py`, and the synthetic envelope
factory, executor and CLI. Their existing Python date-time representation
accepts an offset-aware `datetime`; its grammar/normalization is unchanged.
Pydantic's [strict-mode documentation](https://docs.pydantic.dev/latest/concepts/strict_mode/)
was read today: blanket strict mode has different native/JSON behavior and is
not itself the JSON type contract. Valid enum strings and integral JSON numbers
must continue to load.

## Implementation boundary

Use the existing model declarations and their nested structure to enforce
declared supplied types before Pydantic coercion. A common supplied-input
visitor may provide omission/null/type traversal where needed; it is not a new
schema authority. Independent cells derive expected answers from the parent's
canonical schema/table reader, never from these models or from TypeScript's
answer. Requiredness, defaults, direction/timing rules, enum membership and the
existing date-time reader remain the current model producers.

Booleans and numeric strings are not JSON integers or numbers. An integral JSON
number remains valid where the source declares integer. Present typed optional
members are not nullable merely because the Python model uses `Optional` to
represent omission. An existing nested model is read using its explicitly set
members, without mutating its field-set state; an explicitly set null remains
visible. Untyped JSON is retained recursively, subject only to the separately
ruled whole-tree number domain.

Add the source-declared types currently hidden by broad dictionary annotations:
typed metadata children, subtype-owned remediation details, the declared
placeholder string, and the legacy rate-limit list/entry form. Resolve a
shipped-test envelope through the Envelope member rules without moving test
execution into a loader. The recursive condition class and nested typed maps
must not be limited to the depth of the original measurement fixtures.

The numeric sibling supplies
`hiitl.core.numeric_domain.validate_numeric_domain(value, path=())`, with a
named error carrying its tuple path. This lane owns calls in `types.py`,
`route_types.py` and `sdk/client.py`; the sibling owns canonical/audit/HTTP/cache
number boundaries and YAML parsing. Model projections must preserve every
explicit field before the guard sees them.

Only owned construction/serialization is adapted for omission: the public SDK
builder leaves its optional None arguments out; absent optional verifier claims
are not manufactured as null; `rule_alone` and other owned model re-reads keep
unset fields unset; valid synthetic generation emits a valid sparse envelope.
Caller dictionaries and explicit nested data are never recursively cleaned.
The explicit mapping members in a synthetic scenario remain supplied data, not
SDK keyword defaults. Existing accepted date-time values, defaults and empty
open containers keep their declared meanings.

## Cells, expected answers and mutation obligations

| Cell class | Expected answer read from source | Mutation obligation |
|---|---|---|
| Canonical corpus, Envelope / PolicySet / Route | Each control loads. Each changed input agrees with its declaration's type/null/bound/closure result and exact instance path. Cover all generated declarations, refs, arrays, typed maps and recursive/subtype contexts. | Disable one boundary; permit coercion or typed null; skip a referenced/array/map context. The independently generated expected answer stays fixed. |
| Real policy and route JSON/YAML loaders | Same acceptance/refusal as the model; wrong fields yield the existing named loader exception, not an unrelated `TypeError`. | Bypass supplied validation or let malformed placeholder data reach lint. |
| Positive type representations | Valid enum strings, declared integral JSON numbers, date-time forms and existing native model/date-time representations remain accepted. | Make native strictness reject a valid declared representation. |
| Open values and own keys | Complete supplied open values, including null, false, zero, empty containers and own special-name keys survive. Closed parents still refuse extras. Custom remediation is not typed by another subtype's field names. | Drop/filter a data key, apply a subtype table globally, or blanket-refuse null. |
| Rate-limit input before compilation | Declared list/entry inputs load and preserve the original entry in `compiled_from`; wrong types are named at their original path before compilation. | Validate after compilation or accept the older object form as a declared list. |
| Nested shipped-test envelopes | Omitted required test defaults remain valid; supplied Envelope fields obey their canonical type/closure/bounds. Existing evaluator-backed lint behavior stays separate. | Treat nested envelopes as untyped, or require the complete runtime envelope in a sparse test. |
| SDK optional None versus caller data | Omitted and explicit None optional SDK arguments build equivalent sparse envelopes; caller typed-null mappings refuse; nested open null remains unchanged. | Materialize an owned None field, or erase a supplied open null. |
| Owned model and synthetic writers | Re-reading an existing valid model preserves its explicit field set and open data; generated envelope wire output reloads through the strict model. | Dump unset None defaults into a re-read, or scrub explicitly supplied null. |
| Shared numeric boundary integration | The sibling guard's exact error path/message survives each owned boundary; no local numeric constant or alternative canonicalization. | Bypass the shared guard at an owned pre-coercion boundary. Numeric domain algorithm mutations belong to its lane. |

The parent's shared corpus interface should carry format, source declaration
address, concrete path, control, input, expected acceptance, and a source-owned
projection for accepted data. Counts come from that corpus at execution time;
this design does not freeze a count from an earlier measurement.

### Explicitly changed old cells

CC's PR19 verdict finding (a), confirmed by `d82fe0f5`, requires inverting:

1. `core/tests/test_route_null_cases.py::test_null_change_does_not_tighten_non_null_metadata_types`;
2. `sdk/tests/test_route_null_cases.py::test_loader_null_fix_preserves_non_null_metadata_values`.

Their former acceptance intentionally scoped HTL-41 to null only. HTL-43 now
holds the declared non-null metadata types too. Replace the acceptance with
source-derived named refusals and retain a separately valid open-data control.
The TypeScript counterpart is the other lane's. No other old assertion is
weakened to accommodate implementation behavior; a newly discovered contrary
assertion is identified against its source before it changes.

## Exclusions and verification order

Gap 251's malformed route producers/sinks stay in HTL-33 under `d82fe0f5`.
The undeclared computed-filter element grammar, reserved-form extra-key grammar
and outer-wrapper closure stay open; no stricter grammar is invented. YAML 1.2
and numeric/canonical/audit plumbing are separate sibling work. Historical
stored-data migration and deployment are not exercised by these unit cells.

After the parent's canonical spec/design ready marker: add cells; retain their
initial expected assertion failures; implement; run focused model/loader/writer
cells and affected preexisting defaults/null/evaluation tests in this owned
checkout. Supply exact mutation tuples and raw evidence to the parent without
editing the central registry. The parent runs the integrated full suites and
mutation selection. CC remains the independent reviewer; this lane cannot
self-certify the block.

### Carried-policy reader integration

The existing row-165 source rule excludes conformance refusal cases while
reading their positive controls. Its older implementation recognizes only the
single-case `expected_refusal` document form. The new canonical corpus carries
structured cases with `format`, `id`, `declaration`, `path`, `control`, `input`,
`expected_accept`, `kind`, and optional `subtype`. Recognize that complete
declared case structure, and only when `expected_accept is False` leave its
`input` to the actual conformance consumer. Still walk its control and every
positive input. An arbitrary `expected_accept` metadata member, incomplete
case, or mapping carrying additional artifact members is not an exclusion.
Cells precede this reader correction; a mutation dropping the structure check
or excluding a control/positive input must fail. Row 225 consumes the same
carried-policy list and needs no separate exception.

### Former singleton rate-limit coercion

`policy_format.md` Metadata Fields declares `rate_limits` a list, and the
compilation table addresses entry `i`. HTL-43's canonical measurement therefore
classified the old singleton-object coercion as both implementations wrong.
`test_t130_followup.py::test_a_single_entry_dict_compiles_like_a_list_of_one`
formerly asserted that coercion. Invert that old acceptance to a named refusal,
retaining its same entry inside the declared list as the positive compilation
control. Keep all other old assertions, including retired-field guidance and
the bracketed compiled-entry path; admission must preserve those diagnostics.

### Date-time format on typed children of open objects

The same date-time reader also reaches `metadata.created_at` and `updated_at`
(policy_format.md Metadata Fields, datetime), Route `metadata.created_at`
(routes.md JSON Schema, format date-time), rate-limit remediation `reset_at`,
and temporal `next_allowed_at` (decision_response.md subtype tables, string
(date-time)). Read these through the existing `date_time.refusal` grammar;
retain their original string in open data. `temporal.current_time` remains the
table's plain string. Cells hold valid offset spelling, invalid grammar and a
calendar-range refusal for each declared context, plus custom-subtype data.

### Decision numeric members (numeric-only scope)

`sync_engine.md` Numeric domain, confirmed by d82's reading of 611ea883, also
states that booleans and numeric text are not coerced into typed numeric
members. Decision's schema supplies the numeric-member taxonomy, including
its child objects/arrays; remediation subtype tables supply typed detail
numbers. Hold those members to JsonInteger/JsonNumber and the same numeric
admission visitor while preserving other existing Decision types and nulls.
A large numeric-text post-conversion check alone would not satisfy the sentence;
small text and bool must also refuse. All earlier post-conversion receipts stay
historical, with actual numeric values retained as the positive controls.
