import { describe, it, expect } from 'vitest';
import { PolicyEvaluator, evaluate } from '../../src/evaluator.js';
import { DecisionType } from '../../src/types.js';
import type { Envelope, PolicySet } from '../../src/types.js';

describe('PolicyEvaluator', () => {
  // Base envelope for testing (matches envelope_schema.json requirements)
  const baseEnvelope: Envelope = {
    schema_version: 'v1.0',
    org_id: 'org_abc123def456ghi789', // Pattern: org_ + 16+ alphanumeric chars
    environment: 'dev',
    agent_id: 'payment-agent',
    action_id: 'act_01HQZ6X8Z9P5ABCDEFGHIJK', // Pattern: act_ + 20+ alphanumeric chars
    idempotency_key: 'idem_test123456789',
    tool_name: 'process_payment',
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
        version: '1.0',
        rules: [
          {
            name: 'allow-small-amounts',
            description: 'Allow transactions under $5000',
            priority: 100,
            enabled: true,
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
      expect(decision.policy_version).toBe('1.0');
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
        version: '1.0',
        rules: [
          {
            name: 'block-large-amounts',
            description: 'Block transactions over $500',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'block-eur-only',
            description: 'Block EUR transactions',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'disabled-block-rule',
            description: 'Disabled rule for testing',
            priority: 200,
            enabled: false, // Disabled - should be skipped
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
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'low-priority-allow',
            description: 'Low priority rule',
            priority: 50,
            enabled: true,
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
            enabled: true,
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
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'sandbox-rule',
            description: 'Sandbox decision for dev environment',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'simple-rule',
            description: 'Simple test rule for timing',
            priority: 100,
            enabled: true,
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
      const decision = evaluator.evaluate(baseEnvelope, policy);

      expect(decision.timing).toBeDefined();
      expect(decision.timing.ingest_ms).toBeGreaterThanOrEqual(0);
      expect(decision.timing.evaluation_ms).toBeGreaterThanOrEqual(0);
      expect(decision.timing.total_ms).toBeGreaterThanOrEqual(0);
      expect(decision.timing.total_ms).toBeGreaterThanOrEqual(
        decision.timing.ingest_ms + decision.timing.evaluation_ms
      );
    });
  });

  describe('logical operators', () => {
    describe('all_of (AND)', () => {
      it('should return true when all conditions match', () => {
        const policy: PolicySet = {
          name: 'test-policy',
          version: '1.0',
          rules: [
            {
              name: 'all-conditions-match',
              description: 'Test all_of operator',
              priority: 100,
              enabled: true,
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
          version: '1.0',
          rules: [
            {
              name: 'one-fails',
              description: 'Test all_of with one failing condition',
              priority: 100,
              enabled: true,
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
          version: '1.0',
          rules: [
            {
              name: 'one-matches',
              description: 'Test any_of operator',
              priority: 100,
              enabled: true,
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
          version: '1.0',
          rules: [
            {
              name: 'none-match',
              description: 'Test any_of with no matches',
              priority: 100,
              enabled: true,
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
          version: '1.0',
          rules: [
            {
              name: 'none-match',
              description: 'Test none_of operator',
              priority: 100,
              enabled: true,
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
          version: '1.0',
          rules: [
            {
              name: 'one-matches',
              description: 'Test none_of with one matching condition',
              priority: 100,
              enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'nested-logic',
            description: 'Test nested logical operators',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'deeply-nested',
            description: 'Test deeply nested conditions (3 levels)',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'simple-rule',
            description: 'Simple test rule',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'require-approval-rule',
            description: 'Require approval for large amounts',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'pause-rule',
            description: 'Pause for review',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'escalate-rule',
            description: 'Escalate to security team',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'allow-rule',
            description: 'Allow all',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'block-rule',
            description: 'Block all',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'approval-with-config',
            description: 'Approval with HITL config',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'approval-no-config',
            description: 'Approval without HITL config',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'escalation-rule',
            description: 'Test escalation context',
            priority: 100,
            enabled: true,
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
        version: '1.0',
        rules: [
          {
            name: 'pause-rule',
            description: 'Pause for review',
            priority: 100,
            enabled: true,
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
        version: '1.0',
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
});
