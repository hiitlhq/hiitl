/**
 * Operator evaluation logic for policy conditions.
 */

import type { ConditionOperator } from './types.js';
import { conforms, parameterSchemaValid } from './types.js';
import { jsonEqual } from './json-values.js';
import { requireOperandKinds, OperatorKindError } from './operator-kinds.js';

/**
 * Evaluate a comparison operator.
 *
 * Implements all 14 condition operators matching Python evaluator behavior:
 * - Equality: equals, not_equals
 * - Numeric: greater_than, greater_than_or_equal, less_than, less_than_or_equal
 * - String/Array: contains, not_contains, starts_with, ends_with
 * - Set: in, not_in
 * - Existence: exists
 * - Schema: conforms_to
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
    requireOperandKinds(fieldValue, operator, compareValue);
    return (fieldValue != null) === compareValue;
  }

  // Null handling gate: if field is null/undefined and operator isn't EXISTS, return false
  // This matches Python behavior where most operators fail on None values
  if (fieldValue == null) {
    return false;
  }

  requireOperandKinds(fieldValue, operator, compareValue);
  if (operator === 'conforms_to' && !parameterSchemaValid(compareValue)) {
    throw new OperatorKindError(operator, '<value>', undefined, 'parameter-schema form');
  }

  // === Equality operators ===
  if (operator === 'equals') {
    return jsonEqual(fieldValue, compareValue);
  }

  if (operator === 'not_equals') {
    return !jsonEqual(fieldValue, compareValue);
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
      return fieldValue.some(item => jsonEqual(item, compareValue));
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
      return !fieldValue.some(item => jsonEqual(item, compareValue));
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

  // === Set operations ===
  if (operator === 'in') {
    // Field value is IN the compare value array
    // e.g., field="USD" in ["USD", "EUR", "GBP"]; an array on the left is a subset test (policy_format.md 2.6)
    if (!Array.isArray(compareValue)) {
      return false;
    }
    if (Array.isArray(fieldValue)) return fieldValue.every(x => compareValue.some((item: unknown) => jsonEqual(x, item)));
    return compareValue.some((item: unknown) => jsonEqual(fieldValue, item));
  }

  if (operator === 'not_in') {
    // Field value is NOT IN the compare value array; an array on the left: not every element is (2.6)
    if (!Array.isArray(compareValue)) {
      return false;
    }
    if (Array.isArray(fieldValue)) return !fieldValue.every(x => compareValue.some((item: unknown) => jsonEqual(x, item)));
    return !compareValue.some((item: unknown) => jsonEqual(fieldValue, item));
  }

  if (operator === 'conforms_to') {
    // Schema conformance (policy_format.md 2.6) — never a regex
    return conforms(fieldValue, compareValue);
  }

  // Unknown operator - throw error (should never happen with type safety)
  throw new Error(`Unknown operator: ${operator}`);
}
