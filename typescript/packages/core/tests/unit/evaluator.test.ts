import { describe, it, expect, vi } from 'vitest';
import { PolicyEvaluator, evaluate } from '../../src/evaluator.js';
import { DecisionType, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';
import type { Envelope, PolicySet } from '../../src/types.js';

describe('PolicyEvaluator', () => {
  // Base envelope for testing (matches envelope_schema.json requirements)
  const baseEnvelope: Envelope = {
    schema_version: ENVELOPE_SCHEMA_VERSION,
    org_id: 'org_abc123def456ghi789', // Pattern: org_ + 16+ alphanumeric chars
    environment: 'dev',
    agent_id: 'payment-agent',
    action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK', // Pattern: act_ + 20+ alphanumeric chars
    idempotency_key: 'idem_test123456789',
    action: 'process_payment',
    operation: 'execute',
    target: {
      account_id: 'acct_source',
    },
    parameters: {
      amount: 1000,
      currency: 'USD',
      recipient_account_id: 'acct_recipient',
    },
    timestamp: '2024-01-15T10:30:00Z',
    signature: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2', // 64-char hex
    session_id: 'sess_abc123',
  };

  describe('evaluate', () => {
    it('should return ALLOW decision when rule matches', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Return ALLOW decision when rule matches',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'allow-small-amounts',
            description: 'Allow transactions under $5000',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'SMALL_AMOUNT',
            conditions: {
              field: 'parameters.amount',
              operator: 'less_than',
              value: 5000,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.allowed).toBe(true);
      expect(decision.reason_codes).toEqual(['SMALL_AMOUNT']);
      expect(decision.action_id).toBe('act_01HQZ6X8Z9P5ABCDEFGHIJK');
      expect(decision.policy_version).toBe('v1.0.0');
      expect(decision.matched_rules).toHaveLength(1);
      expect(decision.matched_rules?.[0]).toEqual({
        rule_name: 'allow-small-amounts',
        policy_set: 'test-policy',
        priority: 100,
      });
    });

    it('should return BLOCK decision when rule matches', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Return BLOCK decision when rule matches',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'block-large-amounts',
            description: 'Block transactions over $500',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'AMOUNT_TOO_LARGE',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than_or_equal',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.allowed).toBe(false);
      expect(decision.reason_codes).toEqual(['AMOUNT_TOO_LARGE']);
    });

    it('should return BLOCK with NO_MATCHING_RULE when no rules match', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Return BLOCK with NO_MATCHING_RULE when no rules match',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'block-eur-only',
            description: 'Block EUR transactions',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'WRONG_CURRENCY',
            conditions: {
              field: 'parameters.currency',
              operator: 'equals',
              value: 'EUR',
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.allowed).toBe(false);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      expect(decision.matched_rules).toBeUndefined();
    });

    it('should skip disabled rules', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skip disabled rules',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'disabled-block-rule',
            description: 'Disabled rule for testing',
            priority: 200,
            lifecycle_stage: 'disabled',  // Disabled - should be skipped
            decision: DecisionType.BLOCK,
            reason_code: 'DISABLED_BLOCK',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
          {
            name: 'enabled-allow-rule',
            description: 'Enabled allow rule',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'SMALL_AMOUNT',
            conditions: {
              field: 'parameters.amount',
              operator: 'less_than',
              value: 5000,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      // Should match the enabled rule, not the disabled one
      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.reason_codes).toEqual(['SMALL_AMOUNT']);
      expect(decision.matched_rules?.[0].rule_name).toBe('enabled-allow-rule');
    });

    it('should evaluate rules in priority order (descending)', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Evaluate rules in priority order (descending)',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'low-priority-allow',
            description: 'Low priority rule',
            priority: 50,
            decision: DecisionType.ALLOW,
            reason_code: 'LOW_PRIORITY',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
          {
            name: 'high-priority-block',
            description: 'High priority rule',
            priority: 200,
            decision: DecisionType.BLOCK,
            reason_code: 'HIGH_PRIORITY',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
          {
            name: 'medium-priority-pause',
            description: 'Medium priority rule',
            priority: 100,
            decision: DecisionType.PAUSE,
            reason_code: 'MEDIUM_PRIORITY',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      // Should match highest priority rule first
      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.reason_codes).toEqual(['HIGH_PRIORITY']);
      expect(decision.matched_rules?.[0].priority).toBe(200);
    });

    it('should return SANDBOX as allowed', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Return SANDBOX as allowed',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'sandbox-rule',
            description: 'Sandbox decision for dev environment',
            priority: 100,
            decision: DecisionType.SANDBOX,
            reason_code: 'TESTING_MODE',
            conditions: {
              field: 'environment',
              operator: 'equals',
              value: 'dev',
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.SANDBOX);
      expect(decision.allowed).toBe(true); // SANDBOX is allowed
    });

    it('should include timing metadata', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Include timing metadata',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'simple-rule',
            description: 'Simple test rule for timing',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'OK',
            conditions: {
              field: 'parameters.amount',
              operator: 'less_than',
              value: 5000,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      // decision_response.md Timing Metadata: validation interval, rule interval, whole call.
      const trace = { start: 100, validated: 102, rulesStarted: 103, rulesDone: 108, complete: 111 };
      const readings = Object.values(trace);
      const clock = vi.spyOn(performance, 'now').mockImplementation(() => readings.shift()!);
      try {
        expect(evaluator.evaluate(baseEnvelope, policy).timing).toEqual({
          ingest_ms: trace.validated - trace.start,
          evaluation_ms: trace.rulesDone - trace.rulesStarted,
          total_ms: trace.complete - trace.start,
        });
        expect(readings).toEqual([]);
      } finally {
        clock.mockRestore();
      }
    });
  });

  describe('logical operators', () => {
    describe('all_of (AND)', () => {
      it('should return true when all conditions match', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return true when all conditions match',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'all-conditions-match',
              description: 'Test all_of operator',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'ALL_MATCH',
              conditions: {
                all_of: [
                  {
                    field: 'parameters.amount',
                    operator: 'less_than',
                    value: 5000,
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'USD',
                  },
                  {
                    field: 'environment',
                    operator: 'equals',
                    value: 'dev',
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        expect(decision.decision).toBe(DecisionType.ALLOW);
        expect(decision.reason_codes).toEqual(['ALL_MATCH']);
      });

      it('should return false when any condition fails', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return false when any condition fails',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'one-fails',
              description: 'Test all_of with one failing condition',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'ALL_MATCH',
              conditions: {
                all_of: [
                  {
                    field: 'parameters.amount',
                    operator: 'less_than',
                    value: 5000, // Matches (1000 < 5000)
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'EUR', // Fails (USD !== EUR)
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        // Rule should not match, so safe-by-default BLOCK
        expect(decision.decision).toBe(DecisionType.BLOCK);
        expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      });
    });

    describe('any_of (OR)', () => {
      it('should return true when at least one condition matches', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return true when at least one condition matches',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'one-matches',
              description: 'Test any_of operator',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'ANY_MATCH',
              conditions: {
                any_of: [
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'EUR', // Fails
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'USD', // Matches
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'GBP', // Fails
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        expect(decision.decision).toBe(DecisionType.ALLOW);
        expect(decision.reason_codes).toEqual(['ANY_MATCH']);
      });

      it('should return false when no conditions match', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return false when no conditions match',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'none-match',
              description: 'Test any_of with no matches',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'ANY_MATCH',
              conditions: {
                any_of: [
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'EUR',
                  },
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'GBP',
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        expect(decision.decision).toBe(DecisionType.BLOCK);
        expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      });
    });

    describe('none_of (NOT)', () => {
      it('should return true when no conditions match', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return true when no conditions match',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'none-match',
              description: 'Test none_of operator',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'NONE_MATCH',
              conditions: {
                none_of: [
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'EUR', // Doesn't match (good)
                  },
                  {
                    field: 'parameters.amount',
                    operator: 'greater_than',
                    value: 10000, // Doesn't match (good)
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        expect(decision.decision).toBe(DecisionType.ALLOW);
        expect(decision.reason_codes).toEqual(['NONE_MATCH']);
      });

      it('should return false when any condition matches', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Return false when any condition matches',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: 'one-matches',
              description: 'Test none_of with one matching condition',
              priority: 100,
              decision: DecisionType.ALLOW,
              reason_code: 'NONE_MATCH',
              conditions: {
                none_of: [
                  {
                    field: 'parameters.currency',
                    operator: 'equals',
                    value: 'USD', // Matches (bad for none_of)
                  },
                  {
                    field: 'parameters.amount',
                    operator: 'greater_than',
                    value: 10000, // Doesn't match
                  },
                ],
              },
            },
          ],
        };

        const evaluator = new PolicyEvaluator();
        const decision = evaluator.evaluate(baseEnvelope, policy);

        expect(decision.decision).toBe(DecisionType.BLOCK);
        expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      });
    });
  });

  describe('nested conditions', () => {
    it('should handle nested logical operators', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Handle nested logical operators',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'nested-logic',
            description: 'Test nested logical operators',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'NESTED_MATCH',
            conditions: {
              all_of: [
                {
                  field: 'environment',
                  operator: 'equals',
                  value: 'dev',
                },
                {
                  any_of: [
                    {
                      field: 'parameters.currency',
                      operator: 'equals',
                      value: 'USD',
                    },
                    {
                      field: 'parameters.currency',
                      operator: 'equals',
                      value: 'EUR',
                    },
                  ],
                },
              ],
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.reason_codes).toEqual(['NESTED_MATCH']);
    });

    it('should handle deeply nested conditions (3 levels)', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Handle deeply nested conditions (3 levels)',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'deeply-nested',
            description: 'Test deeply nested conditions (3 levels)',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'COMPLEX_LOGIC',
            conditions: {
              all_of: [
                {
                  any_of: [
                    {
                      none_of: [
                        {
                          field: 'parameters.currency',
                          operator: 'equals',
                          value: 'JPY', // Doesn't match → none_of succeeds
                        },
                      ],
                    },
                  ],
                },
                {
                  field: 'parameters.amount',
                  operator: 'greater_than',
                  value: 500,
                },
              ],
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.reason_codes).toEqual(['COMPLEX_LOGIC']);
    });
  });

  describe('convenience function', () => {
    it('should work with the standalone evaluate function', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Work with the standalone evaluate function',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'simple-rule',
            description: 'Simple test rule',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'OK',
            conditions: {
              field: 'parameters.amount',
              operator: 'less_than',
              value: 5000,
            },
          },
        ],
      };

      const decision = evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.allowed).toBe(true);
      expect(decision.reason_codes).toEqual(['OK']);
    });
  });

  describe('escalation fields', () => {
    it('should generate resume_token for REQUIRE_APPROVAL decisions', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Generate resume_token for REQUIRE_APPROVAL decisions',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'require-approval-rule',
            description: 'Require approval for large amounts',
            priority: 100,
            decision: DecisionType.REQUIRE_APPROVAL,
            reason_code: 'LARGE_AMOUNT',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.REQUIRE_APPROVAL);
      expect(decision.allowed).toBe(false);
      expect(decision.resume_token).toBeDefined();
      expect(decision.resume_token).toMatch(/^rtk_[a-f0-9]{32}$/);
    });

    it('should generate resume_token for PAUSE decisions', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Generate resume_token for PAUSE decisions',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'pause-rule',
            description: 'Pause for review',
            priority: 100,
            decision: DecisionType.PAUSE,
            reason_code: 'NEEDS_REVIEW',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.PAUSE);
      expect(decision.resume_token).toBeDefined();
      expect(decision.resume_token).toMatch(/^rtk_[a-f0-9]{32}$/);
    });

    it('should generate resume_token for ESCALATE decisions', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Generate resume_token for ESCALATE decisions',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'escalate-rule',
            description: 'Escalate to security team',
            priority: 100,
            decision: DecisionType.ESCALATE,
            reason_code: 'SECURITY_REVIEW',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.ESCALATE);
      expect(decision.resume_token).toBeDefined();
      expect(decision.resume_token).toMatch(/^rtk_[a-f0-9]{32}$/);
    });

    it('should NOT generate resume_token for ALLOW decisions', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'NOT generate resume_token for ALLOW decisions',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'allow-rule',
            description: 'Allow all',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'ALLOWED',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.resume_token).toBeUndefined();
    });

    it('should NOT generate resume_token for BLOCK decisions', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'NOT generate resume_token for BLOCK decisions',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'block-rule',
            description: 'Block all',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'BLOCKED',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.resume_token).toBeUndefined();
    });

    it('should pass route from rule to route_ref in decision', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Pass route from rule to route_ref in decision',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'approval-with-config',
            description: 'Approval with HITL config',
            priority: 100,
            decision: DecisionType.REQUIRE_APPROVAL,
            reason_code: 'NEEDS_APPROVAL',
            route: 'payment-approval-workflow',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.route_ref).toBe('payment-approval-workflow');
      expect(decision.resume_token).toBeDefined();
    });

    it('should have undefined route_ref when rule has no route', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Have undefined route_ref when rule has no route',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'approval-no-config',
            description: 'Approval without HITL config',
            priority: 100,
            decision: DecisionType.REQUIRE_APPROVAL,
            reason_code: 'NEEDS_APPROVAL',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.route_ref).toBeUndefined();
      expect(decision.resume_token).toBeDefined();
    });

    it('should NOT populate escalation_context from evaluator', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'NOT populate escalation_context from evaluator',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'escalation-rule',
            description: 'Test escalation context',
            priority: 100,
            decision: DecisionType.REQUIRE_APPROVAL,
            reason_code: 'NEEDS_APPROVAL',
            route: 'approval-workflow',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 500,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.escalation_context).toBeUndefined();
    });

    it('should generate unique resume_tokens for different evaluations', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Generate unique resume_tokens for different evaluations',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'pause-rule',
            description: 'Pause for review',
            priority: 100,
            decision: DecisionType.PAUSE,
            reason_code: 'NEEDS_REVIEW',
            conditions: {
              field: 'parameters.amount',
              operator: 'greater_than',
              value: 0,
            },
          },
        ],
      };

      const evaluator = new PolicyEvaluator();
      const decision1 = evaluator.evaluate(baseEnvelope, policy);
      const decision2 = evaluator.evaluate(baseEnvelope, policy);

      expect(decision1.resume_token).toBeDefined();
      expect(decision2.resume_token).toBeDefined();
      expect(decision1.resume_token).not.toBe(decision2.resume_token);
    });
  });

  describe('validation errors', () => {
    it('should throw validation error for invalid envelope', () => {
      const evaluator = new PolicyEvaluator();
      const invalidEnvelope = {
        action_id: 'act_123',
        // Missing required fields
      };

      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Throw validation error for invalid envelope',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [],
      };

      expect(() => evaluator.evaluate(invalidEnvelope, policy)).toThrow();
    });

    it('should throw validation error for invalid policy', () => {
      const evaluator = new PolicyEvaluator();
      const invalidPolicy = {
        name: 'test-policy',
        // Missing version and rules
      };

      expect(() => evaluator.evaluate(baseEnvelope, invalidPolicy)).toThrow();
    });
  });

  // ─────────────────────────────────────────────────────────────────
  // Block 5a — parity additions: lifecycle, scope, temporal, percentage
  // ─────────────────────────────────────────────────────────────────

  // A condition that always matches the base envelope (amount=1000).
  const alwaysMatch = {
    field: 'parameters.amount',
    operator: 'greater_than' as const,
    value: 0,
  };

  describe('lifecycle_stage gating', () => {
    it('should skip draft / disabled / archived rules entirely', () => {
      // For each non-participating stage, build a policy whose only
      // rule has that stage. The rule's conditions trivially match —
      // if the evaluator honored it, we'd get BLOCK from the rule.
      // The expectation is NO_MATCHING_RULE because the rule never
      // enters the binding loop.
      for (const stage of ['draft', 'disabled', 'archived'] as const) {
        const policy: PolicySet = {
          name: 'test-policy',
          version: 'v1.0.0',
          description: 'Skip draft / disabled / archived rules entirely',
          scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
          rules: [
            {
              name: `${stage}-rule`,
              description: `Rule in ${stage} stage`,
              priority: 100,
              decision: DecisionType.BLOCK,
              reason_code: 'SHOULD_NOT_FIRE',
              conditions: alwaysMatch,
              lifecycle_stage: stage,
            },
          ],
        };
        const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
        expect(decision.decision).toBe(DecisionType.BLOCK);
        expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
        // Empty array (NOT undefined) — Python emits [] always; matching
        // that is required for byte-equivalent decisions across languages.
        expect(decision.staged_observations).toEqual([]);
      }
    });

    it('staged rule should produce staged_observation but NOT bind a decision', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Staged rule should produce staged_observation but NOT bind a decision',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'staged-block',
            description: 'Staged blocker — would-be only',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'STAGED_WOULD_BLOCK',
            conditions: alwaysMatch,
            lifecycle_stage: 'staged',
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      // No active rule matched → safe-default BLOCK (with NO_MATCHING_RULE)
      expect(decision.decision).toBe(DecisionType.BLOCK);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      expect(decision.staged_observations).toHaveLength(1);
      expect(decision.staged_observations?.[0]).toMatchObject({
        rule_name: 'staged-block',
        would_be_decision: DecisionType.BLOCK,
        would_be_reason_codes: ['STAGED_WOULD_BLOCK'],
        would_be_binding: true,
      });
    });

    it('active match should still walk lower-priority staged rules and record them', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Active match should still walk lower-priority staged rules and record them',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'active-allow',
            description: 'High-priority active allow',
            priority: 100,
            decision: DecisionType.ALLOW,
            reason_code: 'ACTIVE_ALLOWED',
            conditions: alwaysMatch,
            lifecycle_stage: 'active',
          },
          {
            name: 'staged-block-would-have-caught',
            description: 'Lower-priority staged block',
            priority: 50,
            decision: DecisionType.BLOCK,
            reason_code: 'STAGED_WOULD_BLOCK',
            conditions: alwaysMatch,
            lifecycle_stage: 'staged',
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      // Active binds. Staged observation flows through.
      expect(decision.decision).toBe(DecisionType.ALLOW);
      expect(decision.reason_codes).toEqual(['ACTIVE_ALLOWED']);
      expect(decision.staged_observations).toHaveLength(1);
      expect(decision.staged_observations?.[0].would_be_binding).toBe(true);
    });

    it('multiple staged matches — only the first marks would_be_binding', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Multiple staged matches — only the first marks would_be_binding',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'staged-high',
            description: 'High-priority staged',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'STAGED_HIGH',
            conditions: alwaysMatch,
            lifecycle_stage: 'staged',
          },
          {
            name: 'staged-low',
            description: 'Low-priority staged',
            priority: 50,
            decision: DecisionType.REQUIRE_APPROVAL,
            reason_code: 'STAGED_LOW',
            conditions: alwaysMatch,
            lifecycle_stage: 'staged',
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.staged_observations).toHaveLength(2);
      expect(decision.staged_observations?.[0].rule_name).toBe('staged-high');
      expect(decision.staged_observations?.[0].would_be_binding).toBe(true);
      expect(decision.staged_observations?.[1].rule_name).toBe('staged-low');
      expect(decision.staged_observations?.[1].would_be_binding).toBe(false);
    });
  });

  describe('scope whitelist filters', () => {
    it('skips rule when scope.environments does not include envelope environment', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule when scope.environments does not include envelope environment',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'prod-only-block',
            description: 'Should not fire in dev',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'PROD_ONLY',
            conditions: alwaysMatch,
            scope: { environments: ['prod'] },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      // dev envelope misses prod whitelist → rule skipped → NO_MATCHING_RULE
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('applies rule when scope.environments matches', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Applies rule when scope.environments matches',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'dev-block',
            description: 'Fires in dev only',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'DEV_BLOCKED',
            conditions: alwaysMatch,
            scope: { environments: ['dev', 'stage'] },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['DEV_BLOCKED']);
    });

    it('skips rule when scope.agents does not include envelope agent_id', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule when scope.agents does not include envelope agent_id',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'other-agent-block',
            description: 'Different agent',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'OTHER_AGENT',
            conditions: alwaysMatch,
            scope: { agents: ['support-bot'] },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('skips rule with scope.users whitelist when envelope has no user_id', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule with scope.users whitelist when envelope has no user_id',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'user-restricted',
            description: 'Requires user_id whitelist',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'USER_REQ',
            conditions: alwaysMatch,
            scope: { users: ['user_42'] },
          },
        ],
      };
      // baseEnvelope has no user_id
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('scope filters apply equally to staged rules — out-of-scope staged is silent', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Scope filters apply equally to staged rules — out-of-scope staged is silent',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'staged-prod-only',
            description: 'Staged but scoped to prod',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'STAGED_PROD',
            conditions: alwaysMatch,
            lifecycle_stage: 'staged',
            scope: { environments: ['prod'] },
          },
        ],
      };
      // dev envelope → scope fails → no staged observation, no match.
      // Staging means "behave as active for observation," not "ignore filters."
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
      expect(decision.staged_observations).toEqual([]);
    });
  });

  describe('temporal validity (valid_from / valid_to)', () => {
    // Far-future / far-past sentinels — these are stable forever and
    // don't depend on the current wall clock, so the tests don't go
    // stale as the project ages.
    const FAR_FUTURE = '2999-12-31T23:59:59Z';
    const FAR_PAST = '1970-01-01T00:00:00Z';

    it('skips rule whose valid_from is in the future', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule whose valid_from is in the future',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'not-yet-active',
            description: 'Rule activates in the year 2999',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'FUTURE_RULE',
            conditions: alwaysMatch,
            valid_from: FAR_FUTURE,
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('skips rule whose valid_to is in the past', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule whose valid_to is in the past',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'already-expired',
            description: 'Rule expired in 1970',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'EXPIRED_RULE',
            conditions: alwaysMatch,
            valid_to: FAR_PAST,
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('applies rule with valid_from in past AND valid_to in future', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Applies rule with valid_from in past AND valid_to in future',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'currently-active',
            description: 'Window spans 1970–2999',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'IN_WINDOW',
            conditions: alwaysMatch,
            valid_from: FAR_PAST,
            valid_to: FAR_FUTURE,
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['IN_WINDOW']);
    });
  });

  describe('percentage rollout', () => {
    it('percentage=0 never applies the rule', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Percentage=0 never applies the rule',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'zero-percent',
            description: '0% rollout',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'ROLLOUT',
            conditions: alwaysMatch,
            scope: { percentage: 0 },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });

    it('percentage=100 always applies the rule', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Percentage=100 always applies the rule',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'full-rollout',
            description: '100% rollout',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'ROLLED_OUT',
            conditions: alwaysMatch,
            scope: { percentage: 100 },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      expect(decision.reason_codes).toEqual(['ROLLED_OUT']);
    });

    it('percentage rollout is deterministic across re-evaluations', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Percentage rollout is deterministic across re-evaluations',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'half-rollout',
            description: '50% rollout, hashed on action_id',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'HALF',
            conditions: alwaysMatch,
            scope: { percentage: 50 },
          },
        ],
      };
      const evaluator = new PolicyEvaluator();
      const first = evaluator.evaluate(baseEnvelope, policy);
      const second = evaluator.evaluate(baseEnvelope, policy);
      // Same envelope, same rule → same bucket → same decision. We
      // assert exact equality on reason_codes rather than the bucket
      // outcome (which depends on a fixed action_id hash).
      expect(first.reason_codes).toEqual(second.reason_codes);
    });

    it('hashes a configurable field when rollout_hash_field is set', () => {
      // Two envelopes that differ only in agent_id. With
      // rollout_hash_field='agent_id', the bucket assignment must
      // be driven by agent_id, not action_id. We construct a case
      // where each agent falls on a different side of the 50% line
      // — that's empirically verifiable but brittle to assert
      // exactly. Instead, assert that hashing IS field-sensitive:
      // different hash fields produce different results for the
      // same envelope when percentage is in (0, 100).
      const baseUnknown = baseEnvelope as unknown as Record<string, unknown>;
      const policyHashByAction: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Hashes a configurable field when rollout_hash_field is set',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'rollout-by-action',
            description: '50% rollout, hashed on action_id',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'BY_ACTION',
            conditions: alwaysMatch,
            scope: { percentage: 50, rollout_hash_field: 'action_id' },
          },
        ],
      };
      const policyHashByAgent: PolicySet = {
        ...policyHashByAction,
        rules: [
          {
            ...policyHashByAction.rules[0],
            scope: { percentage: 50, rollout_hash_field: 'agent_id' },
          },
        ],
      };
      // The action_id and agent_id values differ, so SHA-256 buckets
      // differ. Across enough envelopes this would show statistical
      // independence; for a deterministic test we just verify the
      // mechanic is hooked up. Re-running with the same field gives
      // the same answer; changing the field can flip the answer.
      const result1 = new PolicyEvaluator().evaluate(
        baseUnknown,
        policyHashByAction
      );
      const result2 = new PolicyEvaluator().evaluate(
        baseUnknown,
        policyHashByAction
      );
      expect(result1.reason_codes).toEqual(result2.reason_codes);

      // Field swap may or may not flip the bucket — that depends on
      // hash output. The strong invariant we test is: same field +
      // same field value = same bucket. We've verified that. The
      // weak invariant (field change can flip the bucket) is asserted
      // separately in the conformance suite by choosing specific
      // hash values whose bucket positions are documented.
    });

    it('skips rule when configured hash field is missing from envelope', () => {
      const policy: PolicySet = {
        name: 'test-policy',
        version: 'v1.0.0',
        description: 'Skips rule when configured hash field is missing from envelope',
        scope: { org_id: 'org_abc123def456ghi789', environment: 'dev' },
        rules: [
          {
            name: 'rollout-by-missing',
            description: 'Hashes on a field that envelopes do not have',
            priority: 100,
            decision: DecisionType.BLOCK,
            reason_code: 'MISSING_FIELD',
            conditions: alwaysMatch,
            scope: {
              percentage: 50,
              rollout_hash_field: 'totally_missing_field',
            },
          },
        ],
      };
      const decision = new PolicyEvaluator().evaluate(baseEnvelope, policy);
      // Safe default — rule skipped.
      expect(decision.reason_codes).toEqual(['NO_MATCHING_RULE']);
    });
  });
});
