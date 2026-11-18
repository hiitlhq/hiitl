# TEST_DESIGN: shipped allowlists end at a boundary (HTL-45, `8613a7bc` item 3)

Read whole 2026-11-17: HTL-45 `8613a7bc` and `7bb83c22`; policy_format.md 2.22 (R-1380).
Box: the customer's system (the templates a customer copies into a policy set) and the
SDK decision plane (proposed).

## The defect and the class

Trevor ruled: "Remove matches in 0.2.0." The one shipped template naming the operator,
`patterns/external/webhook_trigger.yaml`, allowed a webhook destination by an unanchored
pattern, `^https://(hooks\.slack\.com|api\.pagerduty\.com|events\.datadog\.com)`. It
allows `https://hooks.slack.com.attacker.com/` and `https://hooks.slack.com@attacker.com/`
(the second's host is `attacker.com`). The rewrite (`8613a7bc` item 3) allows each
destination by `starts_with` on the destination with its trailing slash, so a prefix ends
at a boundary the host cannot extend.

The class is what hiitl ships, no wider: every template and example in the export
(the export manifest's public paths), read the way E7 reads them (whole policy
files, and fenced `json`/`yaml` blocks in pages), skipping the files the exported tests
read as inputs (E7's `_test_inputs`) and the tests themselves. A case in the conformance
grammar (a mapping carrying an `envelope` beside its `policy` or `policy_set`, or an
`expected_refusal`; tests/conformance/TEST_DESIGN.md) in a data file is the suite's
fixture of what an operator does with a value, not a template: it is read and counted,
never classified. Read 2026-11-17, that grammar occurs only in `tests/conformance` (312
cases), never in a page or a template; a page's block is always an example. A condition
admits when a match lets a call through: inside a rule whose decision
decision_response.md's Core Decisions table answers with `allowed` true (read from the
table: `ALLOW`, `OBSERVE`, `SANDBOX`) and outside `none_of`, or inside `none_of` in a
rule of any other decision. An admitting `starts_with` operand must end, and an admitting
`ends_with` operand must begin, with a character that is not a letter or digit. Read
2026-11-17 before the rewrite: nine prefix conditions across eight shipped files; five
admit (`ends_with "@yourcompany.com"`, `"@company.com"`, `":read"` twice;
`starts_with "feature_flags."`) and each ends at a boundary. The webhook pattern is the
only shipped allowlist that does not. Three onboarding pages also name `matches`, in
performance examples that are not allowlists (`performance.md`, `policy_cookbook.md`,
`troubleshooting.md`); they change with the pages (`8613a7bc` item 5).

## Cells

1. **The rewritten template's decisions, both languages** (`cases.json`;
   `python/hiitl/sdk/tests/test_shipped_templates.py`,
   `typescript/packages/sdk/tests/unit/shipped-templates.test.ts`). The template's
   starter policies are read by each SDK's YAML reader, set in a policy set with the
   table's scope, written as a policy file and loaded by each SDK's `PolicyLoader`; the
   table's call is evaluated with `RESPECT_POLICY`. A URL at each of the three hosts is
   `ALLOW` with the reason code of the table's named rule, read from the template. Each
   lookalike is not allowed. Before the rewrite the allowed cases pass and the
   lookalikes fail; after it, both pass.
2. **The class, in the private release suite** (it reads the export manifest). Every
   admitting prefix condition in a shipped template or example ends at a boundary. Every
   `starts_with` or `ends_with` a shipped file names as an operator is reached by the
   parse, so an unread one fails (the asymmetry: unread is never a pass); a prefix
   condition outside any rule has no polarity to read and fails the same way. That every
   shipped policy still loads once `matches` leaves the models is E7's existing claim,
   not a new cell. E7 does not read a template's `starter_policies` (gap 321), so cell 1
   loads the webhook template itself. No other shipped policy names the operator;
   test_020 names it to be refused.

## Mutations

Drop the trailing slash from one destination in the template: cell 1 fails on its
lookalike in both languages and cell 2 names the condition. Restore the unanchored
`matches` rule: cell 1 fails in both languages, each loader refusing the operator. E7
does not catch it: its reader takes a document whose top level is a policy set, a rule
or a list of rules, so a template's `starter_policies` are never loaded (gap 321).
Read a case as a template: cell 2 fails on test_017's `starts_with
"https://api.internal.company.com"`.

## Not covered

What a destination's path carries after its host is the receiving service's matter. A
destination named by its host alone, without a path (`https://hooks.slack.com`), is not
allowed by the rewrite; every webhook these services issue carries a path.
`require-approval-new-destinations` reads the destination by substring (`not_contains
"slack.com"`), so a lookalike carrying the name skips approval and falls to the default
`BLOCK`; it restricts, so it is outside the class and is reported, not changed.
