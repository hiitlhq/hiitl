import { describe, it, expect } from 'vitest';
import { evaluateOperator } from '../../src/operators.js';

describe('evaluateOperator', () => {
  // ========================================
  // Equality Operators
  // ========================================

  describe('equals operator', () => {
    it('should return true when values are equal', () => {
      expect(evaluateOperator('USD', 'equals', 'USD')).toBe(true);
      expect(evaluateOperator(100, 'equals', 100)).toBe(true);
      expect(evaluateOperator(true, 'equals', true)).toBe(true);
    });

    it('should return false when values are not equal', () => {
      expect(evaluateOperator('USD', 'equals', 'EUR')).toBe(false);
      expect(evaluateOperator(100, 'equals', 200)).toBe(false);
      expect(evaluateOperator(true, 'equals', false)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'equals', 'USD')).toBe(false);
      expect(evaluateOperator(undefined, 'equals', 'USD')).toBe(false);
    });
  });

  describe('not_equals operator', () => {
    it('should return true when values are not equal', () => {
      expect(evaluateOperator('USD', 'not_equals', 'EUR')).toBe(true);
      expect(evaluateOperator(100, 'not_equals', 200)).toBe(true);
      expect(evaluateOperator(true, 'not_equals', false)).toBe(true);
    });

    it('should return false when values are equal', () => {
      expect(evaluateOperator('USD', 'not_equals', 'USD')).toBe(false);
      expect(evaluateOperator(100, 'not_equals', 100)).toBe(false);
      expect(evaluateOperator(false, 'not_equals', false)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'not_equals', 'USD')).toBe(false);
      expect(evaluateOperator(undefined, 'not_equals', 'USD')).toBe(false);
    });
  });

  // ========================================
  // Numeric Comparison Operators
  // ========================================

  describe('greater_than operator', () => {
    it('should return true when field value is greater', () => {
      expect(evaluateOperator(1000, 'greater_than', 500)).toBe(true);
      expect(evaluateOperator(100.5, 'greater_than', 100.4)).toBe(true);
    });

    it('should return false when field value is less than or equal', () => {
      expect(evaluateOperator(500, 'greater_than', 1000)).toBe(false);
      expect(evaluateOperator(100, 'greater_than', 100)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'greater_than', 100)).toBe(false);
      expect(evaluateOperator(undefined, 'greater_than', 100)).toBe(false);
    });
  });

  describe('greater_than_or_equal operator', () => {
    it('should return true when field value is greater or equal', () => {
      expect(evaluateOperator(1000, 'greater_than_or_equal', 500)).toBe(true);
      expect(evaluateOperator(100, 'greater_than_or_equal', 100)).toBe(true);
    });

    it('should return false when field value is less', () => {
      expect(evaluateOperator(500, 'greater_than_or_equal', 1000)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'greater_than_or_equal', 100)).toBe(false);
      expect(evaluateOperator(undefined, 'greater_than_or_equal', 100)).toBe(false);
    });
  });

  describe('less_than operator', () => {
    it('should return true when field value is less', () => {
      expect(evaluateOperator(500, 'less_than', 1000)).toBe(true);
      expect(evaluateOperator(99.9, 'less_than', 100)).toBe(true);
    });

    it('should return false when field value is greater than or equal', () => {
      expect(evaluateOperator(1000, 'less_than', 500)).toBe(false);
      expect(evaluateOperator(100, 'less_than', 100)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'less_than', 100)).toBe(false);
      expect(evaluateOperator(undefined, 'less_than', 100)).toBe(false);
    });
  });

  describe('less_than_or_equal operator', () => {
    it('should return true when field value is less or equal', () => {
      expect(evaluateOperator(500, 'less_than_or_equal', 1000)).toBe(true);
      expect(evaluateOperator(100, 'less_than_or_equal', 100)).toBe(true);
    });

    it('should return false when field value is greater', () => {
      expect(evaluateOperator(1000, 'less_than_or_equal', 500)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'less_than_or_equal', 100)).toBe(false);
      expect(evaluateOperator(undefined, 'less_than_or_equal', 100)).toBe(false);
    });
  });

  // ========================================
  // String/Array Operations
  // ========================================

  describe('contains operator', () => {
    it('should return true when string contains substring', () => {
      expect(evaluateOperator('hello world', 'contains', 'world')).toBe(true);
      expect(evaluateOperator('test@example.com', 'contains', '@')).toBe(true);
    });

    it('should return false when string does not contain substring', () => {
      expect(evaluateOperator('hello world', 'contains', 'foo')).toBe(false);
    });

    it('should return true when array contains element', () => {
      expect(evaluateOperator(['USD', 'EUR', 'GBP'], 'contains', 'EUR')).toBe(true);
      expect(evaluateOperator([1, 2, 3], 'contains', 2)).toBe(true);
    });

    it('should return false when array does not contain element', () => {
      expect(evaluateOperator(['USD', 'EUR'], 'contains', 'GBP')).toBe(false);
    });

    it('should return false for non-string/non-array values', () => {
      expect(evaluateOperator(123, 'contains', '2')).toBe(false);
      expect(evaluateOperator(true, 'contains', 'true')).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'contains', 'test')).toBe(false);
      expect(evaluateOperator(undefined, 'contains', 'test')).toBe(false);
    });
  });

  describe('not_contains operator', () => {
    it('should return false when string contains substring', () => {
      expect(evaluateOperator('hello world', 'not_contains', 'world')).toBe(false);
    });

    it('should return true when string does not contain substring', () => {
      expect(evaluateOperator('hello world', 'not_contains', 'foo')).toBe(true);
    });

    it('should return false when array contains element', () => {
      expect(evaluateOperator(['USD', 'EUR'], 'not_contains', 'EUR')).toBe(false);
    });

    it('should return true when array does not contain element', () => {
      expect(evaluateOperator(['USD', 'EUR'], 'not_contains', 'GBP')).toBe(true);
    });

    it('should return true for non-string/non-array values', () => {
      expect(evaluateOperator(123, 'not_contains', '2')).toBe(true);
      expect(evaluateOperator(true, 'not_contains', 'true')).toBe(true);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'not_contains', 'test')).toBe(false);
      expect(evaluateOperator(undefined, 'not_contains', 'test')).toBe(false);
    });
  });

  describe('starts_with operator', () => {
    it('should return true when string starts with prefix', () => {
      expect(evaluateOperator('hello world', 'starts_with', 'hello')).toBe(true);
      expect(evaluateOperator('transaction_123', 'starts_with', 'transaction_')).toBe(true);
    });

    it('should return false when string does not start with prefix', () => {
      expect(evaluateOperator('hello world', 'starts_with', 'world')).toBe(false);
    });

    it('should return false for non-string values', () => {
      expect(evaluateOperator(123, 'starts_with', '1')).toBe(false);
      expect(evaluateOperator(['hello'], 'starts_with', 'h')).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'starts_with', 'test')).toBe(false);
      expect(evaluateOperator(undefined, 'starts_with', 'test')).toBe(false);
    });
  });

  describe('ends_with operator', () => {
    it('should return true when string ends with suffix', () => {
      expect(evaluateOperator('hello world', 'ends_with', 'world')).toBe(true);
      expect(evaluateOperator('test.json', 'ends_with', '.json')).toBe(true);
    });

    it('should return false when string does not end with suffix', () => {
      expect(evaluateOperator('hello world', 'ends_with', 'hello')).toBe(false);
    });

    it('should return false for non-string values', () => {
      expect(evaluateOperator(123, 'ends_with', '3')).toBe(false);
      expect(evaluateOperator(['world'], 'ends_with', 'd')).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'ends_with', 'test')).toBe(false);
      expect(evaluateOperator(undefined, 'ends_with', 'test')).toBe(false);
    });
  });

  describe('matches operator', () => {
    it('should return true when string matches regex pattern', () => {
      expect(evaluateOperator('user@example.com', 'matches', '^[a-z]+@[a-z]+\\.[a-z]+$')).toBe(true);
      expect(evaluateOperator('12345', 'matches', '^\\d+$')).toBe(true);
      expect(evaluateOperator('test123', 'matches', 'test\\d+')).toBe(true);
    });

    it('should return false when string does not match regex pattern', () => {
      expect(evaluateOperator('invalid-email', 'matches', '^[a-z]+@[a-z]+\\.[a-z]+$')).toBe(false);
      expect(evaluateOperator('abc', 'matches', '^\\d+$')).toBe(false);
    });

    it('should return false for non-string values', () => {
      expect(evaluateOperator(123, 'matches', '^\\d+$')).toBe(false);
      expect(evaluateOperator(['test'], 'matches', 'test')).toBe(false);
    });

    it('should return false for invalid regex patterns', () => {
      expect(evaluateOperator('test', 'matches', '[invalid(regex')).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'matches', '^test$')).toBe(false);
      expect(evaluateOperator(undefined, 'matches', '^test$')).toBe(false);
    });
  });

  // ========================================
  // Set Operations
  // ========================================

  describe('in operator', () => {
    it('should return true when field value is in compare array', () => {
      expect(evaluateOperator('USD', 'in', ['USD', 'EUR', 'GBP'])).toBe(true);
      expect(evaluateOperator(2, 'in', [1, 2, 3])).toBe(true);
    });

    it('should return false when field value is not in compare array', () => {
      expect(evaluateOperator('JPY', 'in', ['USD', 'EUR', 'GBP'])).toBe(false);
      expect(evaluateOperator(4, 'in', [1, 2, 3])).toBe(false);
    });

    it('should return false when compare value is not an array', () => {
      expect(evaluateOperator('USD', 'in', 'USD')).toBe(false);
      expect(evaluateOperator(1, 'in', 123)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'in', ['USD', 'EUR'])).toBe(false);
      expect(evaluateOperator(undefined, 'in', ['USD', 'EUR'])).toBe(false);
    });
  });

  describe('not_in operator', () => {
    it('should return true when field value is not in compare array', () => {
      expect(evaluateOperator('JPY', 'not_in', ['USD', 'EUR', 'GBP'])).toBe(true);
      expect(evaluateOperator(4, 'not_in', [1, 2, 3])).toBe(true);
    });

    it('should return false when field value is in compare array', () => {
      expect(evaluateOperator('USD', 'not_in', ['USD', 'EUR', 'GBP'])).toBe(false);
      expect(evaluateOperator(2, 'not_in', [1, 2, 3])).toBe(false);
    });

    it('should return false when compare value is not an array', () => {
      expect(evaluateOperator('USD', 'not_in', 'USD')).toBe(false);
      expect(evaluateOperator(1, 'not_in', 123)).toBe(false);
    });

    it('should return false when field value is null', () => {
      expect(evaluateOperator(null, 'not_in', ['USD', 'EUR'])).toBe(false);
      expect(evaluateOperator(undefined, 'not_in', ['USD', 'EUR'])).toBe(false);
    });
  });

  // ========================================
  // Existence Operator
  // ========================================

  describe('exists operator', () => {
    it('should return true when field exists and compareValue is true', () => {
      expect(evaluateOperator('value', 'exists', true)).toBe(true);
      expect(evaluateOperator(0, 'exists', true)).toBe(true);
      expect(evaluateOperator(false, 'exists', true)).toBe(true);
      expect(evaluateOperator('', 'exists', true)).toBe(true);
    });

    it('should return false when field does not exist and compareValue is true', () => {
      expect(evaluateOperator(null, 'exists', true)).toBe(false);
      expect(evaluateOperator(undefined, 'exists', true)).toBe(false);
    });

    it('should return true when field does not exist and compareValue is false', () => {
      expect(evaluateOperator(null, 'exists', false)).toBe(true);
      expect(evaluateOperator(undefined, 'exists', false)).toBe(true);
    });

    it('should return false when field exists and compareValue is false', () => {
      expect(evaluateOperator('value', 'exists', false)).toBe(false);
      expect(evaluateOperator(0, 'exists', false)).toBe(false);
      expect(evaluateOperator(false, 'exists', false)).toBe(false);
    });
  });

  // ========================================
  // Edge Cases
  // ========================================

  describe('edge cases', () => {
    it('should handle zero values correctly', () => {
      expect(evaluateOperator(0, 'equals', 0)).toBe(true);
      expect(evaluateOperator(0, 'greater_than', -1)).toBe(true);
      expect(evaluateOperator(0, 'less_than', 1)).toBe(true);
    });

    it('should handle false boolean values correctly', () => {
      expect(evaluateOperator(false, 'equals', false)).toBe(true);
      expect(evaluateOperator(false, 'not_equals', true)).toBe(true);
    });

    it('should handle empty string values correctly', () => {
      expect(evaluateOperator('', 'equals', '')).toBe(true);
      expect(evaluateOperator('', 'contains', '')).toBe(true);
      expect(evaluateOperator('', 'starts_with', '')).toBe(true);
    });

    it('should handle empty array values correctly', () => {
      expect(evaluateOperator([], 'contains', 'anything')).toBe(false);
      expect(evaluateOperator([], 'not_contains', 'anything')).toBe(true);
    });
  });

  // ========================================
  // Unknown Operator
  // ========================================

  describe('unknown operator', () => {
    it('should throw error for unknown operator', () => {
      expect(() => evaluateOperator('value', 'invalid_op' as any, 'compare')).toThrow(
        'Unknown operator: invalid_op'
      );
    });
  });
});
