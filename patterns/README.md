# hiitl Pattern Repository

A curated library of action patterns for the Execution Control Plane. Each pattern provides the `evaluate()` call for the action in Python and TypeScript, starter policy rules that load under hiitl 0.2.0, remediation examples, and compliance notes for real-world scenarios.

## How to Use

1. **Find your use case** in the categories below
2. **Copy the `evaluate()` example** into your code (Python or TypeScript). The code after the call stands for your own function.
3. **Copy the starter policies** into the `rules:` list of your policy file. A policy file has `name`, `version` and `rules`.
4. **Customize** thresholds, conditions, and remediation messages for your environment. A rate limit written `{"$uncalibrated": "..."}` never matches until you replace it with a number from your own traffic.
5. **Choose the mode.** Under the SDK's default mode, `OBSERVE_ALL`, an `ALLOW` or `SANDBOX` decision comes back as itself and every other decision comes back `OBSERVE`, with the rule's decision in `would_be`. A windowed rate limit still applies: it counts the calls that come back `ALLOW`, in either mode. To enforce, construct the SDK with `mode="RESPECT_POLICY"`. Under `RESPECT_POLICY` an action no rule matches is blocked with `NO_MATCHING_RULE`, so keep the pattern's `ALLOW` rules.

## Categories

### Financial Operations (4 patterns)
Actions involving money movement, billing, and financial transactions.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Process Payment | [process_payment.yaml](financial/process_payment.yaml) | Amount thresholds, rate limits, kill switch |
| Create Invoice | [create_invoice.yaml](financial/create_invoice.yaml) | Invoice limits, rate limits |
| Issue Refund | [issue_refund.yaml](financial/issue_refund.yaml) | Refund caps, approval for large refunds |
| Transfer Funds | [transfer_funds.yaml](financial/transfer_funds.yaml) | Cross-border controls, velocity limits |

### Data Access (3 patterns)
Actions involving database queries, data exports, and record management.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Query Database | [query_database.yaml](data_access/query_database.yaml) | PII access controls, query scope limits |
| Export Data | [export_data.yaml](data_access/export_data.yaml) | Export size limits, PII controls |
| Delete Records | [delete_records.yaml](data_access/delete_records.yaml) | Irreversible action protection, approval workflows |

### Communication (3 patterns)
Actions involving emails, messages, and notifications.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Send Email | [send_email.yaml](communication/send_email.yaml) | Rate limits, recipient validation |
| Send SMS | [send_sms.yaml](communication/send_sms.yaml) | Cost controls, premium-number blocking |
| Post to Slack | [post_to_slack.yaml](communication/post_to_slack.yaml) | Channel restrictions, content controls |

### Identity & Access Management (3 patterns)
Actions involving user accounts, permissions, and authentication.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Create User | [create_user.yaml](iam/create_user.yaml) | Rate limits, role assignment controls |
| Modify Permissions | [modify_permissions.yaml](iam/modify_permissions.yaml) | Privilege escalation prevention |
| Reset Password | [reset_password.yaml](iam/reset_password.yaml) | Rate limits, approval for admin resets |

### Infrastructure (3 patterns)
Actions involving deployments, configuration changes, and resource management.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Deploy Service | [deploy_service.yaml](infrastructure/deploy_service.yaml) | Environment protection, approval workflows |
| Modify Config | [modify_config.yaml](infrastructure/modify_config.yaml) | Change management, approval for secrets |
| Scale Resources | [scale_resources.yaml](infrastructure/scale_resources.yaml) | Cost controls, capacity limits |

### Documents (3 patterns)
Actions involving reports, contracts, and content publishing.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Generate Report | [generate_report.yaml](documents/generate_report.yaml) | Data sensitivity, access controls |
| Sign Document | [sign_document.yaml](documents/sign_document.yaml) | Value thresholds, legal review |
| Publish Content | [publish_content.yaml](documents/publish_content.yaml) | Review workflows, environment gating |

### Classification & Decisions (3 patterns)
Actions where AI makes categorization or approval decisions.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Classify Ticket | [classify_ticket.yaml](classification/classify_ticket.yaml) | Confidence thresholds, escalation |
| Approve Claim | [approve_claim.yaml](classification/approve_claim.yaml) | Amount limits, human review triggers |
| Score Application | [score_application.yaml](classification/score_application.yaml) | Review zone, no automated adverse action |

### External Services (3 patterns)
Actions involving third-party APIs, webhooks, and integrations.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Call External API | [call_external_api.yaml](external/call_external_api.yaml) | Rate limits, cost controls |
| Webhook Trigger | [webhook_trigger.yaml](external/webhook_trigger.yaml) | Destination validation, payload controls |
| Third-Party Integration | [third_party_integration.yaml](external/third_party_integration.yaml) | Scope limits, PII sharing |

## Pattern Format

Each YAML file follows a consistent structure. See [_schema.yaml](_schema.yaml) for the full format reference.

```yaml
pattern_id: "category/action_name"
category: "category"
name: "Human Readable Name"
description: "What this pattern covers"
tags: ["searchable", "tags"]

evaluate_examples:       # Python and TypeScript evaluate() calls
context_enrichment:      # Fields that improve policy evaluation
starter_policies:        # Policy rules; copy them into a policy file's rules: list
remediation:             # Messages for blocked/approval decisions
compliance:              # Relevant regulations and risk notes
```

## Related Documentation

- [Policy Cookbook](../docs/onboarding/policy_cookbook.md) — Policy examples with detailed explanations
- [Integration Examples](../docs/onboarding/integration_examples.md) — Framework-specific integration patterns
- [Policy Format Spec](../docs/specs/policy_format.md) — Full policy format reference
