/** Declared operand kinds (policy_format.md, Comparison Operators). */
export class OperatorKindError extends Error {
  constructor(readonly operator: string, readonly field = '<value>', readonly reference?: string, readonly requirement = 'declared kind') {
    super(`Operator \`${operator}\` has an operand of the wrong ${requirement} at field \`${field}\`${reference ? ` and referenced field \`${reference}\`` : ''}. Correct the field value or policy to use the operator’s declared operand kinds.`);
    this.name = 'OperatorKindError';
  }
}

/** Right-side kinds declared independently of the left side. */
export function literalKindOK(operator: string, value: unknown): boolean {
  if (['greater_than', 'greater_than_or_equal', 'less_than', 'less_than_or_equal'].includes(operator)) return typeof value === 'number';
  if (['starts_with', 'ends_with', 'matches'].includes(operator)) return typeof value === 'string';
  if (['in', 'not_in'].includes(operator)) return Array.isArray(value);
  if (operator === 'exists') return typeof value === 'boolean';
  if (operator === 'conforms_to') return value !== null && typeof value === 'object' && !Array.isArray(value);
  return true;
}

export function requireOperandKinds(left: unknown, operator: string, right: unknown): void {
  let valid = literalKindOK(operator, right);
  if (['greater_than', 'greater_than_or_equal', 'less_than', 'less_than_or_equal'].includes(operator)) valid = valid && typeof left === 'number';
  else if (['starts_with', 'ends_with', 'matches'].includes(operator)) valid = valid && typeof left === 'string';
  else if (['contains', 'not_contains'].includes(operator)) valid = Array.isArray(left) || typeof left === 'string' && typeof right === 'string';
  else if (operator === 'conforms_to') valid = valid && left !== null && typeof left === 'object' && !Array.isArray(left);
  if (!valid) throw new OperatorKindError(operator);
}

/** Unicode code-point order, matching Python's authored diagnostic selection without locale normalization. */
export function compareOperatorFailures(a: OperatorKindError, b: OperatorKindError): number {
  const left = Array.from(a.message, c => c.codePointAt(0)!);
  const right = Array.from(b.message, c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    if (left[i] !== right[i]) return left[i] - right[i];
  }
  return left.length - right.length;
}
