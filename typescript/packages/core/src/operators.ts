/**
 * Operator evaluation logic for policy conditions.
 */

import type { ConditionOperator } from './types.js';

/**
 * Evaluate a comparison operator.
 *
 * Implements all 14 condition operators matching Python evaluator behavior:
 * - Equality: equals, not_equals
 * - Numeric: greater_than, greater_than_or_equal, less_than, less_than_or_equal
 * - String/Array: contains, not_contains, starts_with, ends_with, matches
 * - Set: in, not_in
 * - Existence: exists
 *
 * **Null handling:**
 * - `exists` operator: Returns `(fieldValue != null) === compareValue`
 * - All other operators: Return `false` if fieldValue is null/undefined (null gate)
 *
 * @param fieldValue - Value from envelope (resolved via field path)
 * @param operator - Comparison operator
 * @param compareValue - Value to compare against
 * @returns True if comparison matches, false otherwise
 *
 * @example
 * ```typescript
 * evaluateOperator(500, 'less_than', 1000);  // true
 * evaluateOperator('USD', 'equals', 'USD');  // true
 * evaluateOperator(null, 'exists', false);   // true
 * evaluateOperator(null, 'equals', 'USD');   // false (null gate)
 * ```
 */
export function evaluateOperator(
  fieldValue: any,
  operator: ConditionOperator,
  compareValue: any
): boolean {
  // Special case: exists operator
  // Returns true if field exists (not null/undefined) when compareValue is true
  // Returns true if field doesn't exist (null/undefined) when compareValue is false
  if (operator === 'exists') {
    return (fieldValue != null) === compareValue;
  }

  // Null handling gate: if field is null/undefined and operator isn't EXISTS, return false
  // This matches Python behavior where most operators fail on None values
  if (fieldValue == null) {
    return false;
  }

  // === Equality operators ===
  if (operator === 'equals') {
    // Deep equality for arrays and objects
    if (Array.isArray(fieldValue) && Array.isArray(compareValue)) {
      return (
        fieldValue.length === compareValue.length &&
        fieldValue.every((val, idx) => val === compareValue[idx])
      );
    }
    // Primitive equality
    return fieldValue === compareValue;
  }

  if (operator === 'not_equals') {
    // Deep equality for arrays and objects
    if (Array.isArray(fieldValue) && Array.isArray(compareValue)) {
      return !(
        fieldValue.length === compareValue.length &&
        fieldValue.every((val, idx) => val === compareValue[idx])
      );
    }
    // Primitive inequality
    return fieldValue !== compareValue;
  }

  // === Numeric comparison operators ===
  if (operator === 'greater_than') {
    return fieldValue > compareValue;
  }

  if (operator === 'greater_than_or_equal') {
    return fieldValue >= compareValue;
  }

  if (operator === 'less_than') {
    return fieldValue < compareValue;
  }

  if (operator === 'less_than_or_equal') {
    return fieldValue <= compareValue;
  }

  // === String/Array operations ===
  if (operator === 'contains') {
    // Works on both strings and arrays
    if (typeof fieldValue === 'string') {
      return fieldValue.includes(compareValue);
    }
    if (Array.isArray(fieldValue)) {
      return fieldValue.includes(compareValue);
    }
    // If field is neither string nor array, return false
    return false;
  }

  if (operator === 'not_contains') {
    // Inverse of contains
    if (typeof fieldValue === 'string') {
      return !fieldValue.includes(compareValue);
    }
    if (Array.isArray(fieldValue)) {
      return !fieldValue.includes(compareValue);
    }
    // If field is neither string nor array, return true (can't contain if not iterable)
    return true;
  }

  if (operator === 'starts_with') {
    // String-only operation
    if (typeof fieldValue === 'string') {
      return fieldValue.startsWith(compareValue);
    }
    return false;
  }

  if (operator === 'ends_with') {
    // String-only operation
    if (typeof fieldValue === 'string') {
      return fieldValue.endsWith(compareValue);
    }
    return false;
  }

  if (operator === 'matches') {
    // Regex pattern matching (use sparingly - can be slow)
    if (typeof fieldValue !== 'string') {
      return false;
    }
    try {
      const pattern = new RegExp(compareValue);
      return pattern.test(fieldValue);
    } catch {
      // Invalid regex pattern - return false
      return false;
    }
  }

  // === Set operations ===
  if (operator === 'in') {
    // Field value is IN the compare value array
    // e.g., field="USD" in ["USD", "EUR", "GBP"]
    if (!Array.isArray(compareValue)) {
      return false;
    }
    return compareValue.includes(fieldValue);
  }

  if (operator === 'not_in') {
    // Field value is NOT IN the compare value array
    if (!Array.isArray(compareValue)) {
      return false;
    }
    return !compareValue.includes(fieldValue);
  }

  // Unknown operator - throw error (should never happen with type safety)
  throw new Error(`Unknown operator: ${operator}`);
}
