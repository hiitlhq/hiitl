# Conformance Test Suite Index

**Total test cases:** 159, in 22 categories (one directory per category).

This index catalogs the conformance test cases for hiitl policy evaluators. Every case is a language-neutral JSON file, and the Python and TypeScript runners load every one.

## Test Categories

### Basic (`basic/`, 10 tests)
Single rules, the default for an action no rule matches, and the envelope's top-level fields.

- `test_001_simple_allow.json` - An `ALLOW` rule that matches
- `test_002_simple_block.json` - A `BLOCK` rule that matches
- `test_003_no_matching_rule.json` - No rule matches: `BLOCK`, `NO_MATCHING_RULE`
- `test_004_disabled_rule.json` - A `disabled` rule is skipped
- `test_005_request_approval.json` - `REQUIRE_APPROVAL` decision type
- `test_006_sandbox.json` - `SANDBOX` decision type (allowed, isolated)
- `test_007_multiple_rules_different_priorities.json` - `ALLOW` (100), `REQUIRE_APPROVAL` (50) and `BLOCK` (10) all match: the `BLOCK` binds
- `test_008_top_level_field.json` - A condition on a top-level envelope field
- `test_009_environment_field.json` - A condition on `environment`
- `test_010_operation_field.json` - A condition on `operation`

### Condition Operators (`conditions/`, 14 tests)
Each atomic condition operator.

- `test_011_equals_operator.json` - `equals`
- `test_012_not_equals_operator.json` - `not_equals`
- `test_013_greater_than_operator.json` - `greater_than`
- `test_014_less_than_operator.json` - `less_than`
- `test_015_in_operator.json` - `in` (value in list)
- `test_016_contains_operator.json` - `contains` (string contains substring)
- `test_017_starts_with_operator.json` - `starts_with`
- `test_018_ends_with_operator.json` - `ends_with`
- `test_019_exists_operator.json` - `exists`
- `test_020_matches_operator.json` - `matches` (regex)
- `test_024_greater_than_or_equal.json` - `greater_than_or_equal`
- `test_025_less_than_or_equal.json` - `less_than_or_equal`
- `test_026_not_in_operator.json` - `not_in` (value not in list)
- `test_027_not_contains_operator.json` - `not_contains`

### Logical Operators (`logical_operators/`, 6 tests)
`all_of`, `any_of` and `none_of`, matching and failing.

- `test_021_all_of_operator.json` - `all_of`: every condition matches
- `test_022_any_of_operator.json` - `any_of`: at least one condition matches
- `test_023_none_of_operator.json` - `none_of`: no condition matches
- `test_028_all_of_fails.json` - `all_of` fails when one condition does not match
- `test_029_any_of_succeeds_with_one.json` - `any_of` succeeds when only one condition matches
- `test_030_none_of_fails.json` - `none_of` fails when one condition matches

### Nested Conditions (`nested/`, 5 tests)
Logical operators inside logical operators.

- `test_041_nested_logical_operators.json` - `all_of` containing `any_of`
- `test_042_deeply_nested_conditions.json` - Conditions nested three levels deep
- `test_043_nested_all_of_and_none_of.json` - `all_of` containing `none_of`
- `test_044_complex_any_of_with_all_of.json` - `any_of` where each option is an `all_of`
- `test_192_a_parameter_named_as_an_inherited_member_is_read_as_the_call_carries_it.json` - A call that names no `constructor` does not carry `parameters.constructor`, though a TypeScript object inherits a member of that name: the guard on its absence binds (2.17)

### Priority and Precedence (`priority/`, 7 tests)
DENY wins: `KILL_SWITCH`, then `BLOCK`, then every other decision. Within a class the higher `priority` binds; at equal priority, the rule defined first.

- `test_031_priority_ordering.json` - `BLOCK` (50) and `ALLOW` (100) both match: the `BLOCK` binds
- `test_032_first_match_wins.json` - `REQUIRE_APPROVAL` (100) and `ALLOW` (90) both match: the higher priority binds
- `test_033_equal_priority_first_defined.json` - `ALLOW` and `BLOCK` at equal priority both match: the `BLOCK` binds, though it is defined second
- `test_124_block_overrides_higher_priority_approval.json` - `REQUIRE_APPROVAL` (200) and `BLOCK` (10) both match: the `BLOCK` binds
- `test_125_kill_switch_overrides_higher_priority_block.json` - `BLOCK` (2000) and `KILL_SWITCH` (5) both match: the `KILL_SWITCH` binds
- `test_126_equal_priority_same_class_first_defined.json` - Two `ALLOW` rules at equal priority: the one defined first binds
- `test_127_priority_orders_within_the_forbid_class.json` - Two `BLOCK` rules (10, 50): the higher priority binds

### Decision Types (`decisions/`, 4 tests)
Decision types and the `allowed` value each one carries.

- `test_061_allow_decision.json` - `ALLOW`, `allowed` true
- `test_062_block_decision.json` - `BLOCK`, `allowed` false
- `test_063_sandbox_decision.json` - `SANDBOX`, `allowed` true
- `test_064_request_approval_decision.json` - `REQUIRE_APPROVAL`, `allowed` false

### Edge Cases (`edge_cases/`, 14 tests)
Special values and data types.

- `test_051_null_field_value.json` - A missing field (`exists: false`)
- `test_052_empty_string.json` - An empty string
- `test_053_zero_value.json` - Zero as a number
- `test_054_negative_numbers.json` - Negative numbers
- `test_055_case_sensitivity.json` - String comparison is case-sensitive
- `test_056_array_in_envelope.json` - `contains` on an array field
- `test_057_nested_field_path.json` - A field path three levels deep
- `test_058_special_characters.json` - Special characters in strings
- `test_059_unicode_strings.json` - Unicode strings
- `test_060_floating_point_numbers.json` - Floating-point numbers
- `test_065_boolean_field.json` - Boolean field values
- `test_066_very_large_number.json` - Very large numbers
- `test_067_empty_array.json` - An empty array
- `test_167_fractional_token_estimate.json` - A fractional `cost_estimate.tokens` (1250.5) is read as written: over a 1250-token budget

### Escalation (`escalation/`, 6 tests)
`REQUIRE_APPROVAL`, `PAUSE` and `ESCALATE` carry the rule's `route` as `route_ref`, and a `resume_token`.

- `test_071_require_approval_with_route.json` - `REQUIRE_APPROVAL` with a `route`: `route_ref` set
- `test_072_pause_with_route.json` - `PAUSE` with a `route`: `route_ref` set
- `test_073_escalate_with_route.json` - `ESCALATE` with a `route`: `route_ref` set
- `test_074_escalation_without_route.json` - `REQUIRE_APPROVAL` with no `route`: `route_ref` null
- `test_075_multiple_rules_different_routes.json` - Two escalation rules with different routes: the higher-priority rule's route is used
- `test_076_non_escalation_no_resume_token.json` - An `ALLOW` carries no `resume_token` and no `route_ref`

### Kill Switch (`kill_switch/`, 3 tests)
`KILL_SWITCH` rules.

- `test_081_kill_switch_basic.json` - `KILL_SWITCH`, `allowed` false
- `test_082_kill_switch_overrides_allow.json` - `KILL_SWITCH` (1000) beats `ALLOW` (50)
- `test_083_disabled_kill_switch.json` - A `disabled` `KILL_SWITCH` is skipped; the `ALLOW` binds

### Remediation (`remediation/`, 7 tests)
A rule's `remediation` on the decision.

- `test_091_block_with_field_restriction_remediation.json` - `BLOCK` carries a `field_restriction` remediation
- `test_092_block_with_threshold_remediation.json` - `BLOCK` carries a `threshold` remediation
- `test_093_block_without_remediation.json` - `BLOCK` with no remediation on the rule: none on the decision
- `test_094_allow_with_remediation_ignored.json` - `ALLOW` rule with a remediation: none on the decision
- `test_158_field_restriction_blocked_fields_computed.json` - `blocked_fields` written `{ref, filter}`: the call's values in the filter, in order, each once; `field_ref` is `ref`
- `test_159_threshold_current_value_computed.json` - A `threshold` remediation naming its `field`: `current_value` is the call's value there
- `test_160_temporal_current_time_computed.json` - A `temporal` remediation: `current_time` is the call's timestamp, UTC to the millisecond

### Observe Mode and Sparse Envelopes (`observe/`, 7 tests)
`OBSERVE_ALL`, and envelopes that carry only `action` and the required identifiers. Under `OBSERVE_ALL`, `ALLOW` and `SANDBOX` come back as themselves; any other decision comes back `OBSERVE`, with `allowed` true and `would_be` set to the rule's decision.

- `test_101_observe_mode_global.json` - `OBSERVE_ALL`: a `BLOCK` comes back `OBSERVE`, `would_be` `BLOCK`
- `test_102_observe_mode_per_rule.json` - `RESPECT_POLICY` with only a `staged` rule matching: `BLOCK`, `NO_MATCHING_RULE`
- `test_103_enforce_rule_in_respect_mode.json` - `RESPECT_POLICY`: an `active` `BLOCK` binds
- `test_104_observe_always_allowed.json` - `OBSERVE_ALL`: a `REQUIRE_APPROVAL` comes back `OBSERVE`, `allowed` true
- `test_105_sparse_envelope_action_only.json` - An envelope with only `action` and the required identifiers
- `test_106_sparse_missing_field_skips_rule.json` - A rule on `parameters.amount` with no `parameters`: no match, `NO_MATCHING_RULE`
- `test_108_observe_allow_passes_through.json` - `OBSERVE_ALL`: an `ALLOW` comes back `ALLOW`

### Lifecycle (`lifecycle/`, 8 tests)
Per-rule `lifecycle_stage`. `active` rules bind. `staged` rules never bind; when they match they are listed in `staged_observations`. `draft`, `disabled` and `archived` rules are skipped.

- `test_109_draft_rule_skipped.json` - A `draft` rule is skipped
- `test_110_disabled_rule_skipped.json` - A `disabled` rule is skipped
- `test_111_archived_rule_skipped.json` - An `archived` rule is skipped
- `test_112_staged_does_not_bind_active_below_does.json` - A `staged` `BLOCK` does not bind; the `active` `ALLOW` below it does
- `test_121_multiple_staged_first_match_marks_binding.json` - Two `staged` rules match: only the higher-priority one is `would_be_binding`
- `test_122_staged_out_of_temporal_window_no_observation.json` - A `staged` rule outside its validity window is skipped and not observed
- `test_123_staged_observation_alongside_active_block.json` - An `active` `BLOCK` binds; the `staged` `ALLOW` below it is observed
- `test_128_staged_would_be_binding_deny_wins.json` - `staged` `ALLOW` and `staged` `BLOCK` both match: the `staged` `BLOCK` is `would_be_binding`

### Scope (`scope/`, 3 tests)
`scope` whitelists. A rule whose whitelist does not include the envelope's value is skipped.

- `test_113_scope_environments_excludes_envelope.json` - `scope.environments` does not include the envelope's environment: skipped
- `test_114_scope_agents_excludes_envelope.json` - `scope.agents` does not include the envelope's `agent_id`: skipped
- `test_115_scope_users_no_user_id_on_envelope.json` - `scope.users` and no `user_id` on the envelope: skipped

### Temporal (`temporal/`, 3 tests)
The `valid_from` / `valid_to` window. Sentinel dates (1970, 2999) keep the cases from going stale.

- `test_116_valid_from_future_skipped.json` - `valid_from` in the future: skipped
- `test_117_valid_to_past_skipped.json` - `valid_to` in the past: skipped
- `test_118_valid_window_includes_now_fires.json` - A window that includes now: the rule applies

### Percentage (`percentage/`, 2 tests)
`scope.percentage` rollouts at 0 and 100, which short-circuit before the SHA-256 bucket. No case covers a percentage between them.

- `test_119_percentage_zero_never_fires.json` - `scope.percentage` 0: the rule never applies
- `test_120_percentage_hundred_always_fires.json` - `scope.percentage` 100: the rule always applies

### Rate Limits (`rate_limit/`, 7 tests)
Windowed `RATE_LIMIT` rules match without binding and are listed in `rate_limit_rules` for the rate limiter; set-level `metadata.rate_limits` compile to such rules.

- `test_129_rate_limit_rule_with_window_meters.json` - A windowed `RATE_LIMIT` rule above an `ALLOW`: the `ALLOW` binds; the rule is listed
- `test_130_rate_limit_rule_below_the_binding_rule_still_meters.json` - A windowed `RATE_LIMIT` rule below the binding `ALLOW` is still listed
- `test_131_rate_limit_rule_without_window_blocks.json` - A `RATE_LIMIT` rule with no window binds; nothing is listed
- `test_132_staged_rate_limit_rule_observed_never_binding.json` - A `staged` windowed `RATE_LIMIT` rule is observed, never binds, and is not listed
- `test_137_set_level_rate_limit_compiles_to_a_rule.json` - A `metadata.rate_limits` entry compiles to the rule `metadata.rate_limits[0]`, priority 0
- `test_138_set_level_user_tool_and_seconds_compile.json` - Two `metadata.rate_limits` entries compile in order, to scopes `user_action` and `action`
- `test_161_rate_limit_rule_listed_with_its_remediation.json` - A windowed rule is listed with its `reason_code` and its `remediation`

### Uncalibrated Bounds (`uncalibrated/`, 2 tests)
A rule whose bound is the `$uncalibrated` placeholder.

- `test_133_uncalibrated_rule_never_matches.json` - A `BLOCK` with an `$uncalibrated` bound never matches; the `ALLOW` binds
- `test_134_uncalibrated_staged_rule_not_observed.json` - A `staged` rule with an `$uncalibrated` bound is not observed

### Verified Principal (`principal/`, 2 tests)
Conditions on the envelope's verified `principal`.

- `test_135_identity_gate_blocks_without_a_verified_principal.json` - A rule on the verified principal blocks an envelope with no `principal`
- `test_136_identity_gate_passes_a_verified_principal.json` - The same rule with a verified `principal`: no match; `principal.scopes` is readable

### Field References and Schemas (`references/`, 10 tests)
A field reference as a condition's value, an array on the left of `in` / `not_in`, and `conforms_to` over a parameter schema.

- `test_140_field_reference_not_in_blocks_scopes_beyond_the_principal.json` - Requested scopes that are not a subset of the principal's match `not_in` a field reference
- `test_141_field_reference_subset_does_not_match.json` - A subset does not match
- `test_142_field_reference_absent_makes_the_condition_false.json` - A reference that resolves to nothing makes the condition false
- `test_143_field_reference_equals_compares_two_fields.json` - `equals` against another field
- `test_144_in_with_an_array_on_the_left_is_a_subset_test.json` - `in` with an array on the left is a subset test
- `test_145_conforms_to_departing_parameters_match_the_negated_test.json` - `conforms_to`: a parameter the schema does not name departs
- `test_146_conforms_to_conforming_parameters_do_not_match.json` - `conforms_to`: conforming parameters
- `test_147_conforms_to_a_property_of_the_wrong_type_departs.json` - `conforms_to`: a property of the wrong type departs
- `test_193_conforms_to_an_undeclared_parameter_named_as_an_inherited_member_departs.json` - `conforms_to`: an undeclared `constructor` departs a closed schema
- `test_194_conforms_to_a_required_name_an_object_inherits_is_absent_unless_carried.json` - `conforms_to`: a required `constructor` the call omits departs

### Enrichment and Routes (`enrichment/`, 10 tests)
A sync route's answer, read as `external.<route>.<field>` from the enrichment context, and `ROUTE` decisions.

- `test_148_enrichment_field_decides.json` - A route's answer, read as `external.<route>.<field>`, decides
- `test_149_enrichment_other_value_does_not_match.json` - Another answer value does not match
- `test_150_enrichment_absent_field_is_false.json` - A field the answer lacks makes the condition false
- `test_151_enrichment_absent_field_exists_false.json` - `exists: false` matches a field the answer lacks
- `test_152_route_decision_carries_route_ref.json` - A `ROUTE` decision carries `route_ref` and is not allowed
- `test_153_answered_route_rule_does_not_match_again.json` - A `ROUTE` rule whose route has answered does not match again
- `test_154_routes_compose_first_answer_routes_on.json` - The first route's answer routes to a second route
- `test_155_routes_compose_both_answers_decide.json` - With both answers, the rule reading the second decides
- `test_156_no_enrichment_reading_rule_never_matches.json` - With no enrichment, a rule on `external.*` never matches
- `test_157_an_answered_route_that_satisfies_no_rule_does_not_route_again.json` - An answered route that no rule reads: the next rule decides

### On Missing (`on_missing/`, 14 tests)
A rule the call cannot read, because an envelope path its conditions name is absent and leaves its outcome open, is read by its set's `on_missing` (policy_format.md **A field the call does not carry**; HTL-22 row 176).

- `test_168_fail_closed_blocks_a_call_missing_a_field_a_rule_reads.json` - `fail_closed`: `BLOCK` / `MISSING_FIELD`, a `custom` remediation naming the field, over a matching `ALLOW` of higher priority
- `test_169_skip_passes_the_call_to_the_next_rule.json` - `skip`: the next rule decides, and `missing_fields` names the rule and the field
- `test_170_skip_a_negated_condition_decides_as_today.json` - `skip`: a `BLOCK` under `none_of` still blocks a call that lacks the field, and is flagged
- `test_171_observe_mode_skips_and_flags.json` - Under `OBSERVE_ALL` a `fail_closed` set skips and flags
- `test_172_a_staged_rule_is_skipped_and_flagged.json` - A staged rule under `fail_closed` skips and flags, with no observation
- `test_173_an_absent_external_field_is_not_counted.json` - An absent `external.*` field is not counted: no `BLOCK`, no flag
- `test_174_fail_closed_a_rule_the_present_fields_decide_reads_as_today.json` - Rules the call's own fields settle, in either condition order, and `exists`, read as before
- `test_175_a_missing_field_block_contends_at_its_rules_priority.json` - A matching `BLOCK` of higher priority binds over the missing-field `BLOCK`
- `test_176_fail_closed_a_windowed_rule_it_cannot_read_blocks.json` - A windowed `RATE_LIMIT` rule the call cannot read blocks under `fail_closed`
- `test_178_fail_closed_a_field_reference_the_call_does_not_carry_blocks.json` - A `{"$field": …}` reference the call does not carry is a read: `BLOCK` / `MISSING_FIELD` naming the referenced field
- `test_179_observe_mode_keeps_the_flag_on_a_decision_it_observes.json` - Under `OBSERVE_ALL` a `BLOCK` comes back `OBSERVE` and keeps the flag
- `test_189_a_condition_on_tool_name_reads_an_absent_field_exists_false_matches.json` - `tool_name` has no alias from 2.0, so no call carries it: an `exists: false` guard on it matches every call
- `test_190_a_none_of_over_tool_name_blocks_every_call.json` - `skip`: a `none_of` allowlist over `tool_name` blocks a call it names, flagged with the rule and `tool_name`
- `test_191_fail_closed_a_rule_open_on_tool_name_blocks.json` - `fail_closed`: a rule open on `tool_name` decides `BLOCK` / `MISSING_FIELD` naming it

### Refusals (`refusals/`, 15 tests)
An artifact naming a field its spec does not define, or missing one it requires, is refused, located at the field and naming it (R-0872: no field is ever silently dropped). A refusal case carries one artifact and `expected_refusal`; nothing is evaluated.

- `test_162_envelope_refuses_an_undefined_field.json` - An envelope with a top-level field the schema does not define (`amount_usd`)
- `test_163_cost_estimate_refuses_an_undefined_key.json` - A `cost_estimate` key other than `tokens`, `dollars` and `api_calls` (`usd_cents`)
- `test_164_rule_refuses_a_decision_only_the_evaluator_produces.json` - A rule writing `OBSERVE`: refused at `rules.0.decision`, naming the rule and the value
- `test_165_scope_refuses_an_environment_no_envelope_carries.json` - A `scope.environments` entry no envelope carries (`staging`), at its index
- `test_166_route_refuses_an_undefined_field_at_depth.json` - A route with an `sla` key `routes.md` does not define (`escalate_after`)
- `test_177_policy_set_refuses_an_on_missing_outside_its_two.json` - An `on_missing` other than `skip` and `fail_closed` (`fail_open`), at `on_missing`
- `test_180_policy_set_refuses_a_set_with_no_scope.json` - A set without its `scope`, at `scope`
- `test_181_policy_set_refuses_a_set_with_no_description.json` - A set without its `description`, at `description`
- `test_182_policy_set_refuses_a_set_with_no_version.json` - A set without its `version`, at `version`
- `test_183_policy_set_refuses_a_version_that_is_not_semver.json` - A `version` without its `v` (`1.0.0`), at `version`
- `test_184_policy_set_scope_needs_its_org.json` - A `scope` without its `org_id`, at `scope.org_id`
- `test_185_policy_set_scope_refuses_an_undefined_key.json` - A `scope` key the format does not define (`region`), at `scope.region`
- `test_186_policy_set_scope_refuses_an_org_in_another_form.json` - A `scope.org_id` not in the envelope's form (`acme-finance`), at `scope.org_id`
- `test_187_envelope_refuses_tool_name_naming_action.json` - A 1.x envelope naming its action `tool_name`, at `action` and `tool_name`, naming `action` (was test_107; the alias leaves at 2.0)
- `test_188_envelope_refuses_tool_name_beside_action.json` - `tool_name` beside `action`, at `tool_name` alone, naming `action`

## Coverage Summary

**Condition operators (15):**
- ✅ equals, not_equals
- ✅ greater_than, greater_than_or_equal
- ✅ less_than, less_than_or_equal
- ✅ in, not_in (including an array on the left)
- ✅ contains, not_contains
- ✅ starts_with, ends_with
- ✅ matches (regex)
- ✅ exists
- ✅ conforms_to (parameter schema)

**Logical operators:**
- ✅ all_of (AND)
- ✅ any_of (OR)
- ✅ none_of (NOT)
- ✅ Nested combinations (2-3 levels deep)

**Decision types in expected results:**
- ✅ BLOCK (72)
- ✅ ALLOW (51)
- ✅ REQUIRE_APPROVAL (7)
- ✅ KILL_SWITCH (3)
- ✅ ESCALATE (2)
- ✅ OBSERVE (3)
- ✅ ROUTE (2)
- ✅ SANDBOX (2)
- ✅ PAUSE (1)
- ✅ RATE_LIMIT (1)

No case expects `SIGNATURE_INVALID` or `CONTROL_PLANE_UNAVAILABLE`. Fifteen cases expect a refusal in place of a decision (`refusals/`).

**Features:**
- ✅ DENY wins: `KILL_SWITCH`, then `BLOCK`, then every other decision; within a class, priority, then definition order
- ✅ Default `BLOCK` when no rule matches (`NO_MATCHING_RULE`)
- ✅ Lifecycle stages (`active`, `staged`, `draft`, `disabled`, `archived`) and `staged_observations`
- ✅ Scope whitelists, percentage rollouts, validity windows
- ✅ `OBSERVE_ALL` mode (`would_be`, `would_be_reason_codes`)
- ✅ Routes on escalation decisions (`route_ref`, `resume_token`)
- ✅ Remediation
- ✅ Windowed rate-limit rules (`rate_limit_rules`)
- ✅ Field references, the verified principal, enrichment from sync routes
- ✅ A field the call does not carry: `on_missing` (`skip`, `fail_closed`) and `missing_fields`
- ✅ Field path resolution (dot notation, read as written), sparse envelopes
- ✅ Edge cases (null, empty, zero, unicode, special characters, a fractional token estimate)
- ✅ Refusals: an envelope, a policy set and a route each refuse a field their spec does not define, naming it (R-0872); a renamed field's refusal names the field it became

## Test File Format

Each test case is a JSON file with this structure:

```jsonc
{
  "test_id": "test_001_simple_allow",
  "description": "Simple ALLOW rule that matches",
  "envelope": { /* Execution envelope */ },
  "policy_set": { /* Policy to evaluate */ },
  "expected_decision": {
    "decision": "ALLOW",
    "allowed": true,
    "reason_codes": ["SMALL_TRANSFER_ALLOWED"]
  }
}
```

`test_id` is the file name without `.json`. A case may also set `mode` (`OBSERVE_ALL` or `RESPECT_POLICY`, the default) and `enrichment`. See `tests/conformance/README.md` for the optional fields of `expected_decision`, and for a refusal case's `expected_refusal`.

## Usage

These test cases validate that every hiitl policy evaluator implementation (Python, TypeScript) produces **identical decisions** for the same inputs.

See `tests/conformance/README.md` for instructions on running conformance tests.
