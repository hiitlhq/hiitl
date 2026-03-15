/**
 * Unit tests for Route model types (Zod schemas).
 *
 * Mirrors python/hiitl/core/tests/test_route_types.py.
 * Validates that the TypeScript Route schemas enforce the same
 * constraints as the Python Pydantic models.
 */

import { describe, it, expect } from 'vitest';
import { RouteSchema } from '../../src/route-types.js';

// ============================================================================
// Fixtures — reusable route data
// ============================================================================

function bidirectionalRoute(overrides: Record<string, unknown> = {}) {
  return {
    name: 'finance-review',
    version: 'v1.0.0',
    direction: 'bidirectional',
    timing: 'sync',
    description: 'Route for finance review',
    purpose: ['review'],
    endpoint: 'https://review.example.com/api/v1/review',
    protocol: 'webhook',
    auth: {
      type: 'api_key',
      secret_ref: 'env:REVIEW_API_KEY',
    },
    context: {
      fields: [
        { field_path: 'parameters.amount', label: 'Amount', format: 'currency' },
        { field_path: 'target.account_id', label: 'Account' },
      ],
      include_policy_ref: true,
      risk_framing: {
        severity: 'high',
        summary: 'Large payment requires approval',
        consequences: {
          if_approved: 'Payment will be processed immediately',
          if_denied: 'Payment will be rejected',
        },
      },
    },
    response_schema: {
      decision_options: ['approve', 'deny', 'modify'],
      required_fields: ['decision', 'reason'],
      reason_required_for: ['deny'],
    },
    sla: {
      timeout: '4h',
      timeout_action: 'escalate',
    },
    ...overrides,
  };
}

function outboundRoute(overrides: Record<string, unknown> = {}) {
  return {
    name: 'audit-webhook',
    version: 'v1.0.0',
    direction: 'outbound',
    timing: 'async',
    endpoint: 'https://audit.example.com/events',
    protocol: 'webhook',
    context: {
      fields: [
        { field_path: 'tool_name', label: 'Tool' },
      ],
    },
    ...overrides,
  };
}

function inboundRoute(overrides: Record<string, unknown> = {}) {
  return {
    name: 'crowdstrike-signals',
    version: 'v1.0.0',
    direction: 'inbound',
    timing: 'async',
    inbound: {
      permissions: {
        can_signal: true,
      },
    },
    ...overrides,
  };
}

// ============================================================================
// Tests — Valid Construction
// ============================================================================

describe('Route Schema — Valid Construction', () => {
  it('parses a valid bidirectional route', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe('finance-review');
      expect(result.data.direction).toBe('bidirectional');
      expect(result.data.timing).toBe('sync');
      expect(result.data.endpoint).toBe('https://review.example.com/api/v1/review');
    }
  });

  it('parses a valid outbound route', () => {
    const result = RouteSchema.safeParse(outboundRoute());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe('audit-webhook');
      expect(result.data.direction).toBe('outbound');
      expect(result.data.timing).toBe('async');
    }
  });

  it('parses a valid inbound route', () => {
    const result = RouteSchema.safeParse(inboundRoute());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe('crowdstrike-signals');
      expect(result.data.direction).toBe('inbound');
    }
  });

  it('parses a minimal bidirectional route', () => {
    const result = RouteSchema.safeParse({
      name: 'minimal-review',
      version: 'v1.0.0',
      direction: 'bidirectional',
      timing: 'sync',
      endpoint: 'https://example.com/review',
      response_schema: {
        decision_options: ['approve', 'deny'],
      },
      sla: {
        timeout: '1h',
        timeout_action: 'fail_closed',
      },
    });
    expect(result.success).toBe(true);
  });

  it('parses a minimal outbound route', () => {
    const result = RouteSchema.safeParse({
      name: 'minimal-webhook',
      version: 'v1.0.0',
      direction: 'outbound',
      timing: 'async',
      endpoint: 'https://example.com/events',
    });
    expect(result.success).toBe(true);
  });
});

// ============================================================================
// Tests — Outbound Direction Validation
// ============================================================================

describe('Route Schema — Outbound Validation', () => {
  it('rejects outbound without endpoint', () => {
    const result = RouteSchema.safeParse(outboundRoute({ endpoint: undefined }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('endpoint');
    }
  });

  it('rejects outbound with response_schema', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      response_schema: { decision_options: ['approve', 'deny'] },
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('response_schema');
    }
  });

  it('rejects outbound with sla', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      sla: { timeout: '1h', timeout_action: 'fail_closed' },
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('sla');
    }
  });

  it('rejects outbound with inbound', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      inbound: { permissions: { can_signal: true } },
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('inbound');
    }
  });

  it('rejects outbound with escalation_ladder', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      escalation_ladder: { levels: [] },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects outbound with correlation', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      correlation: { token_field: 'resume_token' },
    }));
    expect(result.success).toBe(false);
  });
});

// ============================================================================
// Tests — Bidirectional Direction Validation
// ============================================================================

describe('Route Schema — Bidirectional Validation', () => {
  it('rejects bidirectional without endpoint', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({ endpoint: undefined }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('endpoint');
    }
  });

  it('rejects bidirectional without response_schema', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({ response_schema: undefined }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('response_schema');
    }
  });

  it('rejects bidirectional without sla', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({ sla: undefined }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('sla');
    }
  });

  it('rejects bidirectional with async timing', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({ timing: 'async' }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('sync');
    }
  });

  it('rejects bidirectional with inbound', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      inbound: { permissions: { can_signal: true } },
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('inbound');
    }
  });
});

// ============================================================================
// Tests — Inbound Direction Validation
// ============================================================================

describe('Route Schema — Inbound Validation', () => {
  it('rejects inbound without inbound config', () => {
    const result = RouteSchema.safeParse(inboundRoute({ inbound: undefined }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('inbound');
    }
  });

  it('rejects inbound with endpoint', () => {
    const result = RouteSchema.safeParse(inboundRoute({
      endpoint: 'https://example.com',
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('endpoint');
    }
  });

  it('rejects inbound with context', () => {
    const result = RouteSchema.safeParse(inboundRoute({
      context: { fields: [{ field_path: 'tool_name' }] },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects inbound with response_schema', () => {
    const result = RouteSchema.safeParse(inboundRoute({
      response_schema: { decision_options: ['approve', 'deny'] },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects inbound with sla', () => {
    const result = RouteSchema.safeParse(inboundRoute({
      sla: { timeout: '1h', timeout_action: 'fail_closed' },
    }));
    expect(result.success).toBe(false);
  });
});

// ============================================================================
// Tests — Timing Constraints
// ============================================================================

describe('Route Schema — Timing Constraints', () => {
  it('rejects sync route with queue', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      queue: { batch_size: 50, flush_interval: '30s' },
    }));
    expect(result.success).toBe(false);
    if (!result.success) {
      const messages = result.error.issues.map((i) => i.message).join(' ');
      expect(messages).toContain('queue');
    }
  });

  it('allows async route with queue', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      queue: { batch_size: 50, flush_interval: '30s' },
    }));
    expect(result.success).toBe(true);
  });
});

// ============================================================================
// Tests — Pattern Validation
// ============================================================================

describe('Route Schema — Pattern Validation', () => {
  it('rejects invalid name pattern (uppercase)', () => {
    const result = RouteSchema.safeParse(outboundRoute({ name: 'InvalidName' }));
    expect(result.success).toBe(false);
  });

  it('rejects name that is too short', () => {
    const result = RouteSchema.safeParse(outboundRoute({ name: 'ab' }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid version format', () => {
    const result = RouteSchema.safeParse(outboundRoute({ version: '1.0.0' }));
    expect(result.success).toBe(false);
  });

  it('accepts valid version format', () => {
    const result = RouteSchema.safeParse(outboundRoute({ version: 'v2.1.3' }));
    expect(result.success).toBe(true);
  });

  it('rejects invalid SLA timeout format', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      sla: { timeout: '4 hours', timeout_action: 'escalate' },
    }));
    expect(result.success).toBe(false);
  });

  it('accepts valid SLA timeout formats', () => {
    for (const timeout of ['30s', '15m', '4h']) {
      const result = RouteSchema.safeParse(bidirectionalRoute({
        sla: { timeout, timeout_action: 'escalate' },
      }));
      expect(result.success).toBe(true);
    }
  });
});

// ============================================================================
// Tests — Enum Validation
// ============================================================================

describe('Route Schema — Enum Validation', () => {
  it('rejects invalid direction', () => {
    const result = RouteSchema.safeParse(outboundRoute({ direction: 'upstream' }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid timing', () => {
    const result = RouteSchema.safeParse(outboundRoute({ timing: 'realtime' }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid purpose', () => {
    const result = RouteSchema.safeParse(outboundRoute({ purpose: ['invalid'] }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid protocol', () => {
    const result = RouteSchema.safeParse(outboundRoute({ protocol: 'ftp' }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid timeout_action', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      sla: { timeout: '4h', timeout_action: 'retry' },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects invalid decision_option', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      response_schema: { decision_options: ['approve', 'reject'] },
    }));
    expect(result.success).toBe(false);
  });
});

// ============================================================================
// Tests — Sub-Model Validation
// ============================================================================

describe('Route Schema — Sub-Model Validation', () => {
  it('rejects fewer than 2 decision_options', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      response_schema: { decision_options: ['approve'] },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects retry max_attempts > 10', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      retry: { max_attempts: 15 },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects retry initial_delay_ms < 100', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      retry: { initial_delay_ms: 50 },
    }));
    expect(result.success).toBe(false);
  });

  it('rejects escalation level < 1', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute({
      escalation_ladder: {
        levels: [{ level: 0, route: 'ciso-review', after: '30m' }],
      },
    }));
    expect(result.success).toBe(false);
  });

  it('validates auth requires secret_ref', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      auth: { type: 'api_key' },
    }));
    expect(result.success).toBe(false);
  });

  it('validates context field requires field_path', () => {
    const result = RouteSchema.safeParse(outboundRoute({
      context: {
        fields: [{ label: 'Amount' }],
      },
    }));
    expect(result.success).toBe(false);
  });
});

// ============================================================================
// Tests — Serialization
// ============================================================================

describe('Route Schema — Serialization', () => {
  it('round-trips bidirectional route through parse', () => {
    const input = bidirectionalRoute();
    const result = RouteSchema.safeParse(input);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe(input.name);
      expect(result.data.version).toBe(input.version);
      expect(result.data.direction).toBe(input.direction);
      expect(result.data.timing).toBe(input.timing);
      expect(result.data.endpoint).toBe(input.endpoint);
    }
  });

  it('round-trips outbound route through parse', () => {
    const input = outboundRoute();
    const result = RouteSchema.safeParse(input);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe(input.name);
      expect(result.data.direction).toBe('outbound');
      expect(result.data.timing).toBe('async');
    }
  });

  it('preserves nested context fields', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.context?.fields).toHaveLength(2);
      expect(result.data.context?.fields?.[0].field_path).toBe('parameters.amount');
      expect(result.data.context?.fields?.[0].format).toBe('currency');
    }
  });

  it('preserves risk_framing fields', () => {
    const result = RouteSchema.safeParse(bidirectionalRoute());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.context?.risk_framing?.severity).toBe('high');
      expect(result.data.context?.risk_framing?.summary).toBe('Large payment requires approval');
      expect(result.data.context?.risk_framing?.consequences?.if_approved).toBe(
        'Payment will be processed immediately'
      );
    }
  });
});
