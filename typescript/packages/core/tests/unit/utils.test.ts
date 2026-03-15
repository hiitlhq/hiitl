/**
 * Tests for utility functions.
 */

import { describe, it, expect } from 'vitest';
import { resolveFieldPath } from '../../src/utils.js';

describe('resolveFieldPath', () => {
  it('should resolve top-level fields', () => {
    const envelope = {
      action: 'payment_transfer',
      operation: 'execute',
    };

    expect(resolveFieldPath(envelope, 'action')).toBe('payment_transfer');
    expect(resolveFieldPath(envelope, 'operation')).toBe('execute');
  });

  it('should alias tool_name to action in field paths', () => {
    const envelope = {
      action: 'payment_transfer',
    };

    // tool_name field path resolves to action (backward compat)
    expect(resolveFieldPath(envelope, 'tool_name')).toBe('payment_transfer');
  });

  it('should resolve nested fields (2 levels)', () => {
    const envelope = {
      parameters: {
        amount: 500,
        currency: 'USD',
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.amount')).toBe(500);
    expect(resolveFieldPath(envelope, 'parameters.currency')).toBe('USD');
  });

  it('should resolve deeply nested fields (3 levels)', () => {
    const envelope = {
      target: {
        account: {
          id: 'acct_123',
          type: 'checking',
        },
      },
    };

    expect(resolveFieldPath(envelope, 'target.account.id')).toBe('acct_123');
    expect(resolveFieldPath(envelope, 'target.account.type')).toBe('checking');
  });

  it('should return null for missing fields', () => {
    const envelope = {
      action: 'test',
    };

    expect(resolveFieldPath(envelope, 'missing_field')).toBeNull();
    expect(resolveFieldPath(envelope, 'parameters.amount')).toBeNull();
  });

  it('should return null for missing nested paths', () => {
    const envelope = {
      parameters: {
        amount: 500,
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.missing')).toBeNull();
    expect(resolveFieldPath(envelope, 'parameters.nested.field')).toBeNull();
  });

  it('should handle null values in envelope (short-circuit)', () => {
    const envelope = {
      parameters: null,
    };

    expect(resolveFieldPath(envelope, 'parameters.amount')).toBeNull();
  });

  it('should handle undefined values in envelope (short-circuit)', () => {
    const envelope = {
      parameters: undefined,
    };

    expect(resolveFieldPath(envelope, 'parameters.amount')).toBeNull();
  });

  it('should handle null values mid-path', () => {
    const envelope = {
      target: {
        account: null,
      },
    };

    expect(resolveFieldPath(envelope, 'target.account.id')).toBeNull();
  });

  it('should resolve number fields', () => {
    const envelope = {
      parameters: {
        amount: 0, // Zero value should be returned, not treated as null
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.amount')).toBe(0);
  });

  it('should resolve boolean fields', () => {
    const envelope = {
      parameters: {
        enabled: false, // False value should be returned
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.enabled')).toBe(false);
  });

  it('should resolve empty string fields', () => {
    const envelope = {
      parameters: {
        description: '', // Empty string should be returned
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.description')).toBe('');
  });

  it('should resolve array fields', () => {
    const envelope = {
      parameters: {
        tags: ['a', 'b', 'c'],
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.tags')).toEqual(['a', 'b', 'c']);
  });

  it('should resolve object fields', () => {
    const envelope = {
      parameters: {
        config: { key: 'value' },
      },
    };

    expect(resolveFieldPath(envelope, 'parameters.config')).toEqual({ key: 'value' });
  });
});
