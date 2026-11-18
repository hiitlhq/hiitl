import { z } from 'zod';

/** JSON fixture notation preserves explicit undefined separately from an absent property. */
export function unwritten(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(unwritten);
  if (value && typeof value === 'object') {
    if (Object.keys(value).length === 1 && (value as Record<string, unknown>)['$probe.undefined'] === true) return undefined;
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, unwritten(item)]));
  }
  return value;
}

/** Read a recorded schema address through the producer's actual wrappers/shape, never copied schemas. */
export function bare(schema: z.ZodType): any {
  let current: any = schema;
  while (current instanceof z.ZodOptional || current instanceof z.ZodNullable || current instanceof z.ZodDefault || current instanceof z.ZodPrefault || current instanceof z.ZodPipe) {
    current = current instanceof z.ZodPipe ? current.out : current._def.innerType;
  }
  return current;
}

export function at(modules: Record<string, Record<string, unknown>>, address: string): z.ZodType {
  const [module, name, ...fields] = address.split('.');
  let current: any = modules[module][name];
  for (const field of fields) {
    for (const match of field.matchAll(/([^\[|{]+)|(\[\])|(\{\})|\|(\d+)/g)) {
      current = bare(current);
      if (match[1]) current = current.shape[match[1]];
      else if (match[2]) current = current.element;
      else if (match[3]) current = current.valueType;
      else current = current.options[Number(match[4])];
    }
  }
  return current;
}
