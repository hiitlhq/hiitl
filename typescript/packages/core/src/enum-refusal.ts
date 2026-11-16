import { z } from 'zod';

function written(value: unknown): string {
  if (typeof value === 'string') return `'${value}'`;
  // A refused JSON object can itself hold a `toString` key; formatting it must not invoke that key.
  try { return JSON.stringify(value) ?? String(value); }
  catch { return `<${typeof value}>`; }
}

/**
 * A closed vocabulary refuses the value supplied, naming it and what the field takes
 * (policy_format.md 2.10, Policy Set Fields; routes.md Outbound routes and filters).
 * Zod 4's default enum message no longer names the supplied value.
 */
export const enumRefusal: z.core.$ZodErrorMap = (issue) => issue.code === 'invalid_value'
  ? { message: `Invalid value ${written(issue.input)}. Must be one of: ${issue.values.map(written).join(', ')}` }
  : undefined;
