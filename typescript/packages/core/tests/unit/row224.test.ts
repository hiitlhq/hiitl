/**
 * Row 224 (HTL-27): the codes under which the service refuses a record for its own content, one table.
 *
 * Ruled 2026-11-08: "a record the service refuses for its own content stays in the local store as written, marked
 * refused with the service's code, logged at error, and not sent again". sync_engine.md §2.1 names the codes and says
 * "These codes are one table, `RECORD_REFUSALS` in `hiitl.core.lifecycle` and `@hiitl/core`". The table is read against
 * that sentence, at its producer. Design: the HTL-27 test design, row 224, behavior 1. Mirrors
 * python/hiitl/core/tests/test_row224.py.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { RECORD_REFUSALS } from '../../src/index.js';
import { requiredMatch } from '../../../../test-support/declarations.js';

const SPEC = readFileSync(join(__dirname, '../../../../../docs/specs/sync_engine.md'), 'utf8');

/** The codes the final bullet names as refusing "a record for what it carries". */
function finalCodes(): string[] {
  const named = requiredMatch(SPEC,
    /^- \*\*A refusal of the record's own content is final\*\*[\s\S]*?\)\.\s+(`\w+`[\s\S]*?) refuse a record for what it carries/m,
    'sync_engine.md final refusal codes')[1];
  return [...named.matchAll(/`([A-Z][A-Z_]+)`/g)].map((m) => m[1]);
}

describe('row 224: a record refused for its own content', () => {
  it("the table is the spec's", () => {
    expect([...RECORD_REFUSALS]).toEqual(finalCodes());
  });
});
