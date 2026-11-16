/** HTL-37, ruling 7baea573: migrate the validator while preserving declared shapes and decisions.
 * Design: .github/public/TEST_DESIGN_dependencies.md, persistent preservation cells.
 * Fixture addresses/answers were generated from f15051b1's Zod3 definitions before migration,
 * with integer declarations from policy_format.md / decision_response.md and route vocabulary
 * refusals from routes.md. Existing cells and conformance fixtures are unchanged.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import * as types from '../../src/types.js';
import * as routes from '../../src/route-types.js';
import { at, bare, unwritten } from '../support/dependency-migration.js';
import { defaults, routeSchema } from '../../../../../tests/conformance/route_defaults/generate.mjs';

type Case = { kind: string; schema?: string; input: unknown; accepted?: boolean; output?: unknown };
const fixture: { before: string; cases: Case[] } = JSON.parse(readFileSync(join(__dirname, '../fixtures/dependency-migration.json'), 'utf8'));
const numericDomain = JSON.parse(readFileSync(join(__dirname, '../../../../../tests/conformance/numeric_domain/cases.json'), 'utf8'));
const modules: Record<string, Record<string, unknown>> = { types, 'route-types': routes };

describe('HTL-37: dependency migration preserves the declared contract', () => {
  it.each(fixture.cases.filter((c) => c.kind === 'integer'))('integer $schema reads $input as before', (row) => {
    const supplied = unwritten(row.input);
    // HTL43 d82fe0f5 supersedes only old out-of-domain numeric admission; fixture bytes remain historical.
    const admitted = row.accepted && (typeof supplied !== 'number' ||
      (Number.isFinite(supplied) && Math.abs(supplied) < numericDomain.bound));
    const parsed = at(modules, row.schema!).safeParse(supplied);
    expect(parsed.success).toBe(admitted);
    if (admitted) expect(parsed.data).toBe(supplied);
  });

  it.each(fixture.cases.filter((c) => c.kind === 'optional-default'))('optional default $schema follows the current declaration for $input', (row) => {
    const [name, key] = row.schema!.split('.');
    const field = bare(routes[name as keyof typeof routes] as z.ZodType).shape[key];
    const parsed = z.object({ [key]: field }).safeParse(unwritten(row.input));
    expect(parsed.success).toBe(row.accepted);
    if (row.accepted) {
      // HTL-39 supersedes only the old omission output. Keep all original inputs and provenance.
      const expected = unwritten(row.output) as Record<string, unknown>;
      const supplied = unwritten(row.input) as Record<string, unknown>;
      if (supplied[key] === undefined) {
        const declarations = defaults(routeSchema).filter(d => d.path.at(-1) === key);
        if (declarations.length !== 1) throw new Error(`ambiguous route default ${row.schema}`);
        expected[key] = structuredClone(declarations[0].value);
      }
      expect(parsed.data).toStrictEqual(expected);
    }
  });

  it.each(fixture.cases.filter((c) => c.kind === 'condition-value'))('the arbitrary condition value keeps its recorded presence for $input', (row) => {
    const parsed = types.ConditionSchema.safeParse(unwritten(row.input));
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data).toStrictEqual(unwritten(row.output));
  });

  it.each(fixture.cases.filter((c) => c.kind === 'enum-refusal'))('a closed vocabulary refuses the supplied value $input', (row) => {
    const input = unwritten(row.input);
    let parsed!: ReturnType<typeof types.DecisionTypeSchema.safeParse>;
    expect(() => { parsed = types.DecisionTypeSchema.safeParse(input); }).not.toThrow();
    expect(parsed.success).toBe(false);
    if (!parsed.success) {
      const message = parsed.error.issues.map((issue) => issue.message).join('\n');
      expect(message).toContain(JSON.stringify(input) ?? 'undefined');
      for (const value of types.DecisionTypeSchema.options) expect(message).toContain(`'${value}'`);
    }
  });
});
