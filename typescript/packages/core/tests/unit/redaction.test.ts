/**
 * Row 139 (HTL-20): what a store writes, the record with each declared field's value replaced.
 *
 * Mirrors python/hiitl/core/tests/test_redaction.py (row 139 test design cells 1-6). The
 * contract is docs/specs/event_format.md §Redaction.
 */

import { describe, it, expect } from 'vitest';
import { KEY_BYTES, MARKER, Redaction, valueHash } from '../../src/redaction.js';

// The store's value-hash key (row 163(c)): a fixed one, so a hash can be restated
const KEY = Uint8Array.from({ length: KEY_BYTES }, (_, i) => i);

// A payout agent's call: the account it pays into, the payee's email, the amount, and the invoice lines it settles
const ENVELOPE = {
  org_id: 'org_test0123456789ab',
  environment: 'prod',
  action_id: 'act_0123456789abcdefghij',
  agent_id: 'payout-agent',
  action: 'pay',
  target: { email: 'dana@example.com', vendor_id: 'vnd_42' },
  parameters: {
    account_number: 'GB29NWBK60161331926819',
    amount: 1250,
    currency: 'gbp',
    lines: [
      { invoice: 'INV-7', card: '4111 1111 1111 1111' },
      { invoice: 'INV-8', card: '5500 0000 0000 0004' },
    ],
  },
};
const DECISION = { action_id: 'act_0123456789abcdefghij', decision: 'ALLOW', allowed: true, reason_codes: ['OK'] };

const blocked = (remediation: Record<string, unknown>) => ({
  ...DECISION,
  decision: 'BLOCK',
  allowed: false,
  remediation,
});

describe('Redaction (row 139)', () => {
  it('test_a_declared_field_is_replaced_in_the_stored_copy', () => {
    const env = structuredClone(ENVELOPE);
    const dec = structuredClone(DECISION);
    const r = Redaction.declared([
      'parameters.account_number',
      'target.email',
      'parameters.lines.card',
      'parameters.iban',
    ]);
    const [stored, storedDec] = r.record(env, dec);

    expect(stored.parameters.account_number).toBe(MARKER);
    expect(stored.target.email).toBe(MARKER);
    expect(stored.parameters.lines.map((l) => l.card)).toEqual([MARKER, MARKER]);
    expect(stored.parameters.lines.map((l) => l.invoice)).toEqual(['INV-7', 'INV-8']);
    expect([stored.parameters.amount, stored.parameters.currency, stored.target.vendor_id]).toEqual([
      1250,
      'gbp',
      'vnd_42',
    ]);
    expect('iban' in stored.parameters).toBe(false);
    for (const k of ['org_id', 'environment', 'action_id', 'agent_id', 'action'] as const) {
      expect(stored[k]).toBe(ENVELOPE[k]);
    }
    expect(storedDec).toEqual(DECISION);
    expect([env, dec]).toEqual([ENVELOPE, DECISION]); // the inputs are never changed
  });

  it.each(['org_id', 'parameters', 'parameters.', '.account_number', 'parameters..x', '', 7])(
    'test_a_declaration_names_a_member_never_a_top_level_field: %s',
    (entry) => {
      expect(() => Redaction.declared([entry as string])).toThrow(/event_format\.md §Redaction/);
      expect(() => Redaction.declared([entry as string])).toThrow(JSON.stringify(entry));
    }
  );

  it('test_a_declaration_is_a_list_and_recorded_parameters_a_map_of_names', () => {
    expect(() => Redaction.declared('parameters.account_number' as unknown as string[])).toThrow(/list of field paths/);
    for (const bad of [['amount'], { pay: 'amount' }, { pay: ['amount', ''] }, { pay: [3] }]) {
      expect(() => Redaction.declared(undefined, bad as unknown as Record<string, string[]>)).toThrow(
        /event_format\.md §Redaction/
      );
    }
  });

  it('test_the_gateway_records_names_with_hashed_values', () => {
    const params = ENVELOPE.parameters as Record<string, unknown>;
    const [stored] = Redaction.declared(undefined, { pay: ['amount'] }).keyed(KEY).record(ENVELOPE, DECISION);
    expect(Object.keys(stored.parameters).sort()).toEqual(Object.keys(params).sort());
    expect(stored.parameters.amount).toBe(1250);
    for (const name of ['account_number', 'currency', 'lines']) {
      expect((stored.parameters as Record<string, unknown>)[name]).toBe(valueHash(params[name], KEY));
    }
    expect(stored.target).toEqual(ENVELOPE.target);

    const other = { ...ENVELOPE, action: 'read_file', parameters: { amount: 1250, path: '/etc/passwd' } };
    const [storedOther] = Redaction.declared(undefined, { pay: ['amount'] }).keyed(KEY).record(other, DECISION);
    expect(storedOther.parameters).toEqual({ amount: valueHash(1250, KEY), path: valueHash('/etc/passwd', KEY) });

    // a tool named like an Object.prototype member is a tool like any other
    const proto = { ...ENVELOPE, action: 'constructor', parameters: { amount: 1250 } };
    expect(Redaction.declared(undefined, {}).keyed(KEY).record(proto, DECISION)[0].parameters).toEqual({
      amount: valueHash(1250, KEY),
    });

    const [nothing] = Redaction.declared(undefined, {}).keyed(KEY).record(ENVELOPE, DECISION);
    for (const [k, v] of Object.entries(nothing.parameters)) expect(v).toBe(valueHash(params[k], KEY));

    const [both] = Redaction.declared(['parameters.account_number', 'parameters.amount'], { pay: ['amount'] })
      .keyed(KEY)
      .record(ENVELOPE, DECISION);
    expect(both.parameters.account_number).toBe(MARKER);
    expect(both.parameters.amount).toBe(MARKER);
  });

  it('test_a_remediation_that_states_a_value_takes_its_fields_treatment', () => {
    const r = Redaction.declared(['parameters.amount', 'parameters.card']);
    const over = blocked({
      type: 'threshold',
      message: 'over the limit',
      details: { threshold: 1000, current_value: 1250, max_allowed: 1000, field: 'parameters.amount' },
    });
    const [, stored] = r.record(ENVELOPE, over);
    expect((stored.remediation as any).details).toEqual({
      threshold: 1000,
      current_value: MARKER,
      max_allowed: 1000,
      field: 'parameters.amount',
    });
    expect((over.remediation as any).details.current_value).toBe(1250);

    const under = blocked({ type: 'threshold', details: { current_value: 4111, field: 'parameters.card.prefix' } });
    expect((r.record(ENVELOPE, under)[1].remediation as any).details.current_value).toBe(MARKER);

    const cards = Redaction.declared(['parameters.lines.card']);
    for (const ref of ['parameters.lines.card', 'parameters.lines']) {
      const restricted = blocked({
        type: 'field_restriction',
        details: { blocked_fields: ['5500 0000 0000 0004'], field_ref: ref },
      });
      expect((cards.record(ENVELOPE, restricted)[1].remediation as any).details).toEqual({
        blocked_fields: MARKER,
        field_ref: ref,
      });
    }

    const nested = { ...DECISION, audit: { remediation: over.remediation } };
    expect((r.record(ENVELOPE, nested)[1].audit.remediation as any).details.current_value).toBe(MARKER);

    const gateway = Redaction.declared(undefined, { pay: ['currency'] }).keyed(KEY);
    expect((gateway.record(ENVELOPE, over)[1].remediation as any).details.current_value).toBe(valueHash(1250, KEY));

    const elsewhere = blocked({ type: 'threshold', details: { current_value: 3, field: 'parameters.retries' } });
    expect(r.record(ENVELOPE, elsewhere)[1]).toEqual(elsewhere);
    const scope = blocked({ type: 'scope', details: { current_value: 1250, field: 'parameters.amount' } });
    expect(r.record(ENVELOPE, scope)[1]).toEqual(scope);
  });

  it('test_no_declaration_writes_the_record_as_given', () => {
    for (const r of [Redaction.declared(), Redaction.declared([], undefined)]) {
      expect(r.active).toBe(false);
      const [stored, storedDec] = r.record(ENVELOPE, DECISION);
      expect(stored).toBe(ENVELOPE);
      expect(storedDec).toBe(DECISION);
    }
  });

  // The hash's literal in both languages is row 163's cell (row163.test.ts), since its key
});
