/**
 * Row 163(c) (HTL-22): the gateway's value hash is HMAC-SHA256 under the store's key.
 *
 * Mirrors python/hiitl/core/tests/test_row163.py, and restates its literal. These are the row's
 * test design cells 8-9.
 */

import { describe, it, expect } from 'vitest';
import { createHash } from 'node:crypto';
import { canonicalJson } from '../../src/canonical.js';
import { HASH_PREFIX, KEY_BYTES, MARKER, Redaction, valueHash } from '../../src/redaction.js';

const KEY = Uint8Array.from({ length: KEY_BYTES }, (_, i) => i);
const OTHER_KEY = Uint8Array.from(KEY).reverse();
// A value with a float, a non-ASCII character and keys out of order: what canonical form has to settle
const VALUE = { iban: 'GB29NWBK60161331926819', amount: 1250.5, memo: 'Café №7' };
const LITERAL = 'hmac-sha256:bf5639138d2279700db8d774d7155aa3a0202b1eaefd1a5203b57f30d713682e';

const GATEWAY = Redaction.declared(['parameters.card'], { approve_refund: ['order_id'] });
const CALL = {
  action: 'approve_refund',
  parameters: { order_id: 'ord_8812', amount: 120, approved: true, card: '4111 1111 1111 1111' },
};

describe('row 163(c): the value hash is keyed', () => {
  it('test_the_value_hash_is_keyed', () => {
    const [stored] = GATEWAY.keyed(KEY).record(CALL, {});
    const [again] = GATEWAY.keyed(KEY).record(CALL, {});
    const [other] = GATEWAY.keyed(OTHER_KEY).record(CALL, {});
    const p = (stored as any).parameters;
    expect([p.order_id, p.card]).toEqual(['ord_8812', MARKER]);
    expect(p.amount).toBe(valueHash(120, KEY));
    expect(p.amount.startsWith(HASH_PREFIX)).toBe(true);
    expect(again).toEqual(stored);
    expect((other as any).parameters.amount).not.toBe(p.amount);

    // The guess a reader without the key would make: hash each candidate of a small set, unkeyed
    const unkeyed = (c: unknown) => createHash('sha256').update(canonicalJson(c), 'utf8').digest('hex');
    for (let c = 0; c < 1000; c++) expect(p.amount.includes(unkeyed(c))).toBe(false);
    for (const c of [true, false]) expect(p.approved.includes(unkeyed(c))).toBe(false);
  });

  it('test_one_literal_in_both_languages', () => {
    expect(valueHash(VALUE, KEY)).toBe(LITERAL);
  });

  it('test_a_hash_without_the_stores_key_is_refused', () => {
    expect(() => GATEWAY.record(CALL, {})).toThrow(/key/);
    for (const short of [new Uint8Array(0), KEY.slice(0, -1)]) {
      expect(() => GATEWAY.keyed(short)).toThrow(String(KEY_BYTES));
    }
    expect((Redaction.declared(['parameters.card']).record(CALL, {})[0] as any).parameters.card).toBe(MARKER);
  });

  it('test_a_joined_declaration_redacts_each_path_either_declares', () => {
    const sdk = Redaction.declared(['parameters.card']);
    const joined = sdk.joined(['target.email', 'parameters.card'], 'manual_redact_fields');
    const [env] = joined.record({ ...CALL, target: { email: 'dana@example.com' } }, {});
    expect([(env as any).parameters.card, (env as any).target.email]).toEqual([MARKER, MARKER]);
    expect(sdk.joined([], 'manual_redact_fields')).toBe(sdk);
    expect(() => sdk.joined(['org_id'], 'manual_redact_fields')).toThrow(/manual_redact_fields/);
  });
});
