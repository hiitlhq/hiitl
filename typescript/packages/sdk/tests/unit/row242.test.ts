/**
 * Row 242 (HTL-29 review, condition 5), in the SDK: a date-time written in a policy's or route's YAML is the string
 * written, read by the core's one reader, and the store's dedup window compares the instants that reader reads.
 *
 * ecp_evaluate_spec.md "A date-time is read by RFC 3339's grammar": a YAML policy or route is "a thin parsing layer
 * that converts to JSON" (policy_format.md), so YAML's timestamp type is not resolved and an explicit `!!timestamp` is
 * refused; where two are compared, each is the instant the reader reads, and a recorded `timestamp` the store cannot
 * read leaves the key not known to be new (row 193). Design: the HTL-29 test design, row 137, behaviors 19 and 20. Mirrors
 * python/hiitl/sdk/tests/test_row242.py.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Database from 'better-sqlite3';
import { ERROR_MESSAGES, dateTimeRefusal, readDateTime, type Decision } from '@hiitl/core';
import { HIITL } from '../../src/client.js';
import { PolicyLoadError } from '../../src/exceptions.js';
import { PolicyLoader } from '../../src/policy-loader.js';
import { RouteLoader } from '../../src/route-loader.js';

const ORG = 'org_test000000000000000';
const POLICY = (validTo: string) => `\
name: refunds
version: v1.0.0
description: The refund agent's refunds
scope:
  org_id: ${ORG}
  environment: dev
rules:
  - name: refunds_in_window
    description: Refunds are allowed in the window
    priority: 100
    conditions: {field: action, operator: equals, value: refund}
    decision: ALLOW
    reason_code: REFUND_ALLOWED
    valid_to: ${validTo}
`;
const ROUTE = (reviewed: string) => `\
name: finance-review
version: v1.0.0
description: High-value refunds go to the finance team
direction: outbound
timing: async
purpose: [review]
endpoint: https://hooks.example.com/hiitl/finance-review
protocol: webhook
metadata:
  reviewed: ${reviewed}
`;
const SET = {
  version: 'v1.0.0', name: 'refunds', description: "The refund agent's refunds",
  scope: { org_id: ORG, environment: 'dev' },
  rules: [{
    name: 'allow_refunds', priority: 100, description: 'Refunds are allowed',
    conditions: { field: 'action', operator: 'equals', value: 'refund' },
    decision: 'ALLOW', reason_code: 'REFUND_ALLOWED',
  }],
};
const HOUR = 3_600_000;

let dir: string;
const clients: HIITL[] = [];
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'row242-'));
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const h of clients.splice(0)) h.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function ruleValidTo(written: string): string | undefined {
  const file = path.join(dir, 'refunds.yaml');
  fs.writeFileSync(file, POLICY(written));
  return new PolicyLoader(file).load().rules[0].valid_to;
}

describe('row 242: a date-time in a YAML policy or route is the string written', () => {
  it.each(['2026-01-02T03:04:05Z', '2026-01-02t03:04:05z', '2026-01-02T04:04:05.5+01:00'])(
    'an unquoted date-time in a YAML policy is read by the core (%s)', (written) => {
      expect(ruleValidTo(written)).toBe(written);
    });

  it.each(['2026-01-02 03:04:05Z', '2026-01-02T03:04:05', '2026-01-02'])(
    "a YAML timestamp RFC 3339 does not read is refused by its form (%s)", (written) => {
      expect(() => ruleValidTo(written)).toThrow(PolicyLoadError);
      expect(() => ruleValidTo(written)).toThrow(`valid_to ${dateTimeRefusal(written)}`);
    });

  it('an explicit YAML timestamp is refused', () => {
    expect(() => ruleValidTo('!!timestamp 2026-01-02T03:04:05Z')).toThrow('tag:yaml.org,2002:timestamp');
  });

  it("a date-time in a YAML route's metadata is the string written", () => {
    fs.writeFileSync(path.join(dir, 'finance-review.yaml'), ROUTE('2026-01-02T03:04:05Z'));
    expect(new RouteLoader(dir).get('finance-review')?.metadata).toEqual({ reviewed: '2026-01-02T03:04:05Z' });
  });
});

function client(): HIITL {
  const file = path.join(dir, 'refunds.json');
  fs.writeFileSync(file, JSON.stringify(SET));
  const h = new HIITL({
    environment: 'dev', agent_id: 'refund-agent', org_id: ORG, policy_path: file,
    audit_db_path: path.join(dir, 'audit.db'), mode: 'RESPECT_POLICY',
  });
  clients.push(h);
  return h;
}

/** The recorded envelope's `timestamp`, as another writer of this store wrote it. */
function recordedAs(actionId: string, timestamp: (written: string) => string): void {
  const db = new Database(path.join(dir, 'audit.db'));
  try {
    const { written } = db.prepare("SELECT json_extract(envelope, '$.timestamp') AS written FROM audit_log " +
      "WHERE json_extract(envelope, '$.action_id') = ?").get(actionId) as { written: string };
    db.prepare("UPDATE audit_log SET envelope = json_set(envelope, '$.timestamp', ?) " +
      "WHERE json_extract(envelope, '$.action_id') = ?").run(timestamp(written), actionId);
  } finally {
    db.close();
  }
}

/** The instant written, in another offset; in RFC 3339's lower case `t` when `lower`. */
function inOffset(written: string, hours: number, lower = false): string {
  const wall = new Date(readDateTime(written) + hours * HOUR).toISOString().slice(0, 23);
  const offset = hours === 0 ? 'Z' : `${hours < 0 ? '-' : '+'}${String(Math.abs(hours)).padStart(2, '0')}:00`;
  const text = `${wall}${offset}`;
  return lower ? text.replace('T', 't').replace('Z', 'z') : text;
}

const evaluate = (h: HIITL, key: string) => h.evaluate({ action: 'refund', idempotency_key: key }) as Decision;

describe("row 242: the store's dedup window reads each recorded timestamp as the core does", () => {
  it.each([[0, true], [1, false], [-5, true]] as const)(
    'a retry is read against a timestamp recorded in any form RFC 3339 reads (%s hours, lower %s)', (hours, lower) => {
      const h = client();
      const first = evaluate(h, 'idem_r242_form');
      recordedAs(first.action_id, (written) => inOffset(written, hours, lower));
      expect(evaluate(h, 'idem_r242_form').action_id, 'the first decision under its key').toBe(first.action_id);
    });

  it('a recorded timestamp the store cannot read leaves the key not known to be new', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const h = client();
    const first = evaluate(h, 'idem_r242_unread');
    recordedAs(first.action_id, () => '2026-11-10T13:04:05.678+01:60');
    const d = evaluate(h, 'idem_r242_unread');
    expect([d.decision, d.reason_codes, d.error?.code]).toEqual(['BLOCK', ['AUDIT_READ_FAILED'], 'AUDIT_READ_FAILED']);
    expect(d.error?.message).toBe(ERROR_MESSAGES.AUDIT_READ_FAILED);
  });
});
