# HIITL Pattern Repository

A curated library of action patterns for the Execution Control Plane. Each pattern provides copy-paste-ready `evaluate()` calls, starter policies, remediation examples, and compliance notes for real-world scenarios.

## How to Use

1. **Find your use case** in the categories below
2. **Copy the `evaluate()` example** into your code (Python or TypeScript)
3. **Copy the starter policies** into your policy file
4. **Customize** thresholds, conditions, and remediation messages for your environment

## Categories

### Financial Operations (4 patterns)
Actions involving money movement, billing, and financial transactions.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Process Payment | [process_payment.yaml](financial/process_payment.yaml) | Amount thresholds, currency restrictions, kill switch |
| Create Invoice | [create_invoice.yaml](financial/create_invoice.yaml) | Invoice limits, duplicate detection |
| Issue Refund | [issue_refund.yaml](financial/issue_refund.yaml) | Refund caps, approval for large refunds |
| Transfer Funds | [transfer_funds.yaml](financial/transfer_funds.yaml) | Cross-border controls, velocity limits |

### Data Access (3 patterns)
Actions involving database queries, data exports, and record management.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Query Database | [query_database.yaml](data_access/query_database.yaml) | PII access controls, query scope limits |
| Export Data | [export_data.yaml](data_access/export_data.yaml) | Export size limits, format restrictions |
| Delete Records | [delete_records.yaml](data_access/delete_records.yaml) | Irreversible action protection, approval workflows |

### Communication (3 patterns)
Actions involving emails, messages, and notifications.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Send Email | [send_email.yaml](communication/send_email.yaml) | Rate limits, recipient validation |
| Send SMS | [send_sms.yaml](communication/send_sms.yaml) | Cost controls, opt-out compliance |
| Post to Slack | [post_to_slack.yaml](communication/post_to_slack.yaml) | Channel restrictions, content controls |

### Identity & Access Management (3 patterns)
Actions involving user accounts, permissions, and authentication.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Create User | [create_user.yaml](iam/create_user.yaml) | Rate limits, role assignment controls |
| Modify Permissions | [modify_permissions.yaml](iam/modify_permissions.yaml) | Privilege escalation prevention |
| Reset Password | [reset_password.yaml](iam/reset_password.yaml) | Rate limits, identity verification |

### Infrastructure (3 patterns)
Actions involving deployments, configuration changes, and resource management.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Deploy Service | [deploy_service.yaml](infrastructure/deploy_service.yaml) | Environment protection, approval workflows |
| Modify Config | [modify_config.yaml](infrastructure/modify_config.yaml) | Change management, rollback safety |
| Scale Resources | [scale_resources.yaml](infrastructure/scale_resources.yaml) | Cost controls, capacity limits |

### Documents (3 patterns)
Actions involving reports, contracts, and content publishing.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Generate Report | [generate_report.yaml](documents/generate_report.yaml) | Data sensitivity, access controls |
| Sign Document | [sign_document.yaml](documents/sign_document.yaml) | Authority verification, audit trail |
| Publish Content | [publish_content.yaml](documents/publish_content.yaml) | Review workflows, environment gating |

### Classification & Decisions (3 patterns)
Actions where AI makes categorization or approval decisions.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Classify Ticket | [classify_ticket.yaml](classification/classify_ticket.yaml) | Confidence thresholds, escalation |
| Approve Claim | [approve_claim.yaml](classification/approve_claim.yaml) | Amount limits, human review triggers |
| Score Application | [score_application.yaml](classification/score_application.yaml) | Bias monitoring, fairness controls |

### External Services (3 patterns)
Actions involving third-party APIs, webhooks, and integrations.

| Pattern | File | Key Decisions |
|---------|------|---------------|
| Call External API | [call_external_api.yaml](external/call_external_api.yaml) | Rate limits, cost controls |
| Webhook Trigger | [webhook_trigger.yaml](external/webhook_trigger.yaml) | Destination validation, payload controls |
| Third-Party Integration | [third_party_integration.yaml](external/third_party_integration.yaml) | Scope limits, credential protection |

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
starter_policies:        # Ready-to-use policy rules
remediation:             # Messages for blocked/approval decisions
compliance:              # Relevant regulations and risk notes
```

## Related Documentation

- [Policy Cookbook](../docs/onboarding/policy_cookbook.md) — Policy examples with detailed explanations
- [Integration Examples](../docs/onboarding/integration_examples.md) — Framework-specific integration patterns
- [Policy Format Spec](../docs/specs/policy_format.md) — Full policy format reference
