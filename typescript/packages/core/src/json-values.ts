/** policy_format.md: one value comparison for the six JSON kinds. */
export function jsonEqual(left: unknown, right: unknown): boolean {
  if (left === null || right === null) return left === null && right === null;
  if (typeof left !== typeof right) return false;
  if (typeof left === 'boolean' || typeof left === 'number' || typeof left === 'string') return left === right;
  if (Array.isArray(left)) {
    return Array.isArray(right) && left.length === right.length && left.every((value, index) => jsonEqual(value, right[index]));
  }
  if (typeof left === 'object' && typeof right === 'object' && !Array.isArray(right)) {
    const a = left as Record<string, unknown>, b = right as Record<string, unknown>;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && jsonEqual(a[key], b[key]));
  }
  return false;
}
