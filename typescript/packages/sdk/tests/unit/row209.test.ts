/**
 * Row 209 (HTL-23): one timeout range, and the hosted client's settings table swept.
 *
 * Ruled 2026-11-06: "One timeout range in both SDKs, 0.1 to 30 seconds, declared in the spec; Python takes it. The
 * bound is Trevor's declaration (the TypeScript SDK's declared range is adopted, not chosen anew)." The row found the
 * timeout; the class is every row of decision_response.md's hosted settings table (item 13), read at its producer:
 * each bound or member, given as an option or by its variable, constructs and is held; a value past a bound, or not a
 * member, fails construction naming the range. No name, bound or member is listed here. Design:
 * the HTL-23 test design, row 209. Mirrors python/hiitl/sdk/tests/test_row209.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { HIITL } from '../../src/client.js';
import { ConfigurationError } from '../../src/exceptions.js';
import { HOSTED, code } from './settings-tables.js';

const BOUNDS = /^(-?\d+(?:\.\d+)?)–(-?\d+(?:\.\d+)?)/;
const ORG_ID = 'org_r209settings000000';

/** One unit of a bound's last digit, past it on either side, as text. */
function past(bound: string, by: -1 | 1): string {
  const places = bound.split('.')[1]?.length ?? 0;
  return (Number(bound) + by * 10 ** -places).toFixed(places);
}

/** [the bounds or members, values past a bound or not a member, the words a refusal names], from the range cell. */
function kind(row: string[]): [string[], string[], string[]] {
  const range = row[4];
  const members = [...range.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  if (members.length) return [members, ['r209-outside'], members];
  const [, low, high] = BOUNDS.exec(range)!;
  return [[low, high], [past(low, -1), past(high, 1)], [low, high]];
}

const ROWS = HOSTED.map((row) => [code(row[1]), code(row[2]), ...kind(row)] as const);
const HOW = ['option', 'variable'] as const;

let dir: string;
let ambient: Record<string, string | undefined>;

beforeEach(() => {
  // no ambient setting reaches a cell
  ambient = {};
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    ambient[name] = process.env[name];
    delete process.env[name];
  }
  dir = mkdtempSync(path.join(tmpdir(), 'hiitl-row209-'));
});

afterEach(() => {
  for (const name of Object.keys(process.env).filter((n) => n.toUpperCase().startsWith('HIITL_'))) {
    delete process.env[name];
  }
  Object.assign(process.env, ambient);
  rmSync(dir, { recursive: true, force: true });
});

/** A value as an option takes it: a number as a number, a member as its text. */
function typed(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function hosted(given: Record<string, unknown>): HIITL {
  return new HIITL({
    environment: 'dev', agent_id: 'r209-agent', org_id: ORG_ID, api_key: 'sk_test_row209',
    server_url: 'https://ecp.r209.example.com', evaluation: 'remote', signature_key: 'r209-signing-secret',
    audit_db_path: path.join(dir, 'audit.db'), ...given,
  } as ConstructorParameters<typeof HIITL>[0]);
}

function given(option: string, variable: string, value: string, how: (typeof HOW)[number]): Record<string, unknown> {
  if (how === 'option') return { [option]: typed(value) };
  process.env[variable] = value;
  return {};
}

const whole = (word: string, text: string) =>
  new RegExp(`(?<![\\w.])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w.])`).test(text);

describe('row 209: the hosted client\'s settings table', () => {
  for (const [option, variable, inside, outside, words] of ROWS) {
    for (const how of HOW) {
      it(`test_each_bound_or_member_is_taken[${option}-${how}]`, () => {
        for (const value of inside) {
          const h = hosted(given(option, variable, value, how));
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const held = (h as any).hostedConfig?.[option];
          h.close();
          expect(held, `${option} given ${value} by ${how}`).toEqual(typed(value));
        }
      });

      it(`test_a_value_outside_the_range_is_refused_naming_it[${option}-${how}]`, () => {
        for (const value of outside) {
          let refused: unknown;
          try {
            hosted(given(option, variable, value, how)).close();
          } catch (e) {
            refused = e;
          }
          expect(refused, `${option} given ${value} by ${how} was not refused`).toBeInstanceOf(ConfigurationError);
          const message = (refused as Error).message;
          expect(words.filter((w) => !whole(w, message)), `${option} given ${value} by ${how}: ${message}`)
            .toEqual([]);
        }
      });
    }
  }
});
