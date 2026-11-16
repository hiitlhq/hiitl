/**
 * Utility functions for policy evaluation.
 */

/**
 * Resolve a field path (dot notation) in an envelope.
 *
 * A path is read as written, at every part (policy_format.md 2.17). Supports nested paths like:
 * - `action` → envelope.action
 * - `parameters.amount` → envelope.parameters.amount
 * - `target.account_id` → envelope.target.account_id
 *
 * **Behavior:**
 * - Short-circuits on null/undefined (matches Python behavior)
 * - Returns `null` (not `undefined`) for missing fields
 * - Reads a part only where the object holds it as data: an own key of a plain object, never an inherited
 *   member (`constructor`, `toString`) or an array's (policy_format.md 2.17)
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
 * resolveFieldPath(envelope, 'parameters.tool_name'); // null: the parameter of that name, never parameters.action
 * ```
 */
export function resolveFieldPath(
  envelope: Record<string, any>,
  fieldPath: string
): any {
  const parts = fieldPath.split('.');
  let current: any = envelope;

  for (const part of parts) {
    // Short-circuit on null/undefined (matches Python `if current is None`)
    if (current == null) {
      return null;
    }

    // A member the object holds as data (policy_format.md 2.17)
    if (typeof current === 'object' && !Array.isArray(current) && Object.hasOwn(current, part)) {
      current = current[part];
    } else {
      return null;
    }
  }

  return current;
}
