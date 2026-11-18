/**
 * Row 195 (HTL-23): each error decision's event type is the table's.
 *
 * Ruled 2026-11-06 as the row reads: "as built, by the table, since no sentence names a type for the other two". The
 * table is event_format.md's "Event types"; the error decisions are decision_response.md's "Error decisions", and the
 * control point's own failures are `BLOCK`s ("Where the error is answered"). Both are read from the specs, never
 * listed here. Design: the HTL-23 test design, row 195. Mirrors python/hiitl/core/tests/test_row195.py.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { eventType } from '../../src/lifecycle.js';
import { requiredMatch } from '../../../../test-support/declarations.js';

const SPECS = join(__dirname, '../../../../../docs/specs');

/** The decisions decision_response.md's "Error decisions" list names, each a bullet under it. */
function errorDecisions(): string[] {
  const text = readFileSync(join(SPECS, 'decision_response.md'), 'utf8');
  const listed = requiredMatch(text, /^\*\*Error decisions\*\*:\n((?:- [^\n]+\n)+)/m,
    'decision_response.md Error decisions bullets')[1];
  return listed.trimEnd().split('\n').map((line) => requiredMatch(line,
    /^- `([A-Z_]+)` - .+$/, 'decision_response.md each Error decisions bullet')[1]);
}

/** event_format.md's table, for a decision record: each decision it names, its type; and the type of any other. */
function table(): [Record<string, string>, string] {
  const text = readFileSync(join(SPECS, 'event_format.md'), 'utf8');
  const named: Record<string, string> = {};
  let other: string | undefined;
  for (const [, event, decision] of text.matchAll(/^\| `([a-z_.]+)` \| a decision record \| ([^|]+?) \| none \|$/gm)) {
    if (decision === 'any other') other = event;
    else named[decision.replace(/`/g, '')] = event;
  }
  expect(other, 'the table names the type of any other decision').toBeDefined();
  return [named, other!];
}

describe('row 195: each error decision takes the type the table states', () => {
  it('test_each_error_decision_takes_the_type_the_table_states', () => {
    const decisions = errorDecisions();
    const [named, other] = table();
    for (const decision of [...decisions, 'BLOCK']) {
      expect(eventType(decision), decision).toBe(named[decision] ?? other);
    }
  });
});
