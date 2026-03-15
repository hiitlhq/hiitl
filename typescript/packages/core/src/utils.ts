/**
 * Utility functions for policy evaluation.
 */

/**
 * Resolve a field path (dot notation) in an envelope.
 *
 * Supports nested paths like:
 * - `tool_name` → envelope.tool_name
 * - `parameters.amount` → envelope.parameters.amount
 * - `target.account_id` → envelope.target.account_id
 *
 * **Behavior:**
 * - Short-circuits on null/undefined (matches Python behavior)
 * - Returns `null` (not `undefined`) for missing fields
 * - Handles both object properties and dict-like access
 *
 * @param envelope - Envelope object to resolve field in
 * @param fieldPath - Dot-notation field path (e.g., "parameters.amount")
 * @returns Field value, or `null` if field doesn't exist
 *
 * @example
 * ```typescript
 * const envelope = { parameters: { amount: 500 } };
 * resolveFieldPath(envelope, 'parameters.amount'); // 500
 * resolveFieldPath(envelope, 'parameters.missing'); // null
 * resolveFieldPath(envelope, 'tool_name'); // null
 * ```
 */
export function resolveFieldPath(
  envelope: Record<string, any>,
  fieldPath: string
): any {
  const parts = fieldPath.split('.');
  let current: any = envelope;

  for (let part of parts) {
    // Backward compat: tool_name → action
    if (part === 'tool_name') {
      part = 'action';
    }

    // Short-circuit on null/undefined (matches Python `if current is None`)
    if (current == null) {
      return null;
    }

    // Handle object property access
    if (typeof current === 'object' && part in current) {
      current = current[part];
    } else {
      return null;
    }
  }

  return current;
}
