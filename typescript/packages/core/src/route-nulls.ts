/** Null-only validation facts generated from routes.md; no non-null type coercion. */
export type NullShape = {
  readonly allows_null: boolean;
  readonly properties?: Readonly<Record<string, NullShape>>;
  readonly items?: NullShape;
  readonly additionalProperties?: NullShape;
};

/** Visit present values only. Omission and untyped data retain their existing behavior. */
export function forbiddenNulls(value: unknown, shape: NullShape, path: (string | number)[] = []): (string | number)[][] {
  if (value === null) return shape.allows_null ? [] : [path];
  if (Array.isArray(value)) {
    return shape.items ? value.flatMap((item, index) => forbiddenNulls(item, shape.items!, [...path, index])) : [];
  }
  if (typeof value !== 'object') return [];
  return Object.entries(value).flatMap(([key, item]) => {
    const child = Object.hasOwn(shape.properties ?? {}, key) ? shape.properties![key] : shape.additionalProperties;
    return child ? forbiddenNulls(item, child, [...path, key]) : [];
  });
}
