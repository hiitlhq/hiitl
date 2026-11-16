# HTL-43: declared input classes

Design before cells, 2026-11-14, following HTL-43 `dfbf6f10` and the full
`d82fe0f5` ruling. Searched and loaded: Envelope JSON Schema, Routes Full Schema,
policy-format tables and named forms, decision-response remediation tables,
the project workflow and conformance ontology. Proposed architecture §2: SDK ingestion,
decision and audit. No model seat is added.

The owning sentence is “Language implementations follow the spec. If two
implementations disagree, the spec decides.” Types come from those sources;
“No field is dropped” owns closed policy objects. A supplied null follows the
source type. Sparse rule-test envelopes inherit supplied Envelope member types
while their missing root-required members remain filled by the existing lint.

## Independent expected answers

The existing schema reader supplies Envelope/Routes declarations, refs, array
items, typed maps, unions and conditionals. Policy tables are read by type
column and source address, with explicit adapters for source-owned recursive
conditions, scope, rate windows, placeholders, parameter-schema forms and
subtype-owned remediation. Valid controls witness each declaration and context.
Missing/unread source constructs or missing witnesses fail generation; the
reader never silently filters them. Current model inventories may help find a
missing witness, but never decide its expected answer.

Generate null, wrong JSON type, unknown-field and out-of-range cases from each
source declaration. Keep valid controls and restoration positives. Test all
source-decided locations, including those where both SDKs previously agreed on
a wrong answer. Add recursive/nested witnesses and map keys independently of
the measured failure list. Open data, custom remediation and nullable literals
keep their positive cases. No arbitrary depth limit becomes a product rule.

The common corpus `cases.json` has `source_hashes`, `declarations`, and `cases`.
Each case carries `format` (envelope/policy/routes), `id`, `declaration`, concrete
`path`, accepted `control`, one-changed `input`, `expected_accept`, `kind`, and
optional `subtype`. Source freshness and every declaration's witnessed context
are assertions. Accepted data preservation is checked at the owned open-data
projection, not by comparing model output wholesale with input: declared
defaulting/rate compilation remain permitted.

The reserved-policy corpus is another complete executable case form: exactly
`id`, `input`, `control`, `accept`, `path` and `cause`, with mapping input/control,
text id/cause, a concrete path and a boolean answer. Its paired real-loader cells
own a refused input just as the input-contract runner owns `expected_accept: false`.
The carried-artifact reader recognizes this whole form, never a filename or a
loose refusal flag. Controls and every accepted input remain in its walk.
Cells cover the full reserved corpus, every missing case member and extra-member
impostors; a mutation must restore the mistaken treatment of negative inputs as
loadable examples. No input or expected answer changes for this reader correction.

Both core model readers and real policy/route file loaders consume these fixed
answers. A refusal names the changed instance path. Separate cells preserve
Python own-argument None semantics, TypeScript's currently defaulted native
options, all own data keys without prototype changes, numeric boundaries and
YAML scalar classes; their lane designs enumerate real-path assertions.

## Mutation and evidence

Hold generation with changes to a source declaration, removal of a witness,
array/map/reference traversal, subtype context and closed-object rule. Hold
each production validation attachment with a mutation that makes the fixed
answer fail as an assertion. Loader wrappers must preserve named validation
errors. The three HTL-41 metadata-acceptance cells are explicitly inverted by
CC finding (a), not silently weakened. Retain baseline assertion reds and final
commands/counts. Root runs full suites and the complete mutation registry once
on the integrated finished tree; CC reviews independently.

Gap 251 stays HTL-33; YAML gap 263 is here. The deferred computed-filter,
reserved-form/literal and wrapper grammars (286–288) are reported as open, not
silently promoted to a guessed acceptance rule. Source-decided siblings still
get cells. This design promises coverage of declared null/type/closure/numeric
rules, not a new policy grammar or a deployment against stored production data.

## Positive alternatives retain their declared syntax

The field-reference operand accepts a string path or a declared placeholder.
Policy format 2.6 says the lint refuses an unaddressable reference. Replacing
the placeholder with the generic numeric-text wrong-type sample therefore
cannot be called an accepted string alternative. Its positive string witness
names a string member read from the Envelope declaration; other wrong-type
probes retain numeric text, so coercion remains challenged. A reader cell holds
both obligations and a mutation restores the invalid generic string witness.
