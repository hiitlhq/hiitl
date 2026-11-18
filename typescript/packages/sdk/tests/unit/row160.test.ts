/**
 * Row 160 (HTL-29): in an SDK's audit store, the dedup read and the record's write are one step. The ruling (HTL-29,
 * 2026-11-09): "dedup read and write are one step under the same lock on (org, environment, key); the index stays
 * non-unique (24 h window)". Spec: docs/specs/ecp_evaluate_spec.md §4, the paragraph "The read and the write are one
 * step". Design: the HTL-29 test design, row 160, behavior 8. Mirrors python/hiitl/sdk/tests/test_row160.py.
 *
 * TypeScript decides synchronously except where it asks a sync route, so that is where the race lives: the first call's
 * route answer is held until the cell lets it go.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HIITL } from '../../src/client.js';
import { AuditLogger } from '../../src/audit.js';

const ORG = 'org_test000000000000000';
const POLICY = {
  version: 'v1.0.0', description: 'Posts are checked before they publish', scope: { org_id: ORG, environment: 'dev' },
  name: 'content_policy',
  rules: [
    { name: 'ask_content_check', priority: 500, conditions: { field: 'action', operator: 'equals', value: 'publish_post' },
      decision: 'ROUTE', reason_code: 'CONTENT_CHECK', route: 'content-check', description: 'Posts are checked' },
    { name: 'allow_otherwise', priority: 1, conditions: { field: 'action', operator: 'exists', value: true },
      decision: 'ALLOW', reason_code: 'ALLOWED', description: 'Everything else' },
  ],
};
const ROUTE = {
  name: 'content-check', version: 'v1.0.0', description: 'The content check', direction: 'bidirectional', timing: 'sync',
  purpose: ['assessment'], endpoint: 'https://checks.example/v1/content', protocol: 'http',
  context: { fields: [{ field_path: 'parameters.body' }] },
  response_schema: { decision_options: ['approve', 'deny'], required_fields: ['verdict'] },
  sla: { timeout: '5s', timeout_action: 'fail_closed' },
};

describe('the dedup read and the record write are one step in an SDK store (row 160)', () => {
  let dir: string;
  let asked: number;
  let release: () => void;
  let answered: Promise<void>;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hiitl-row160-'));
    fs.writeFileSync(path.join(dir, 'policy.json'), JSON.stringify(POLICY));
    fs.mkdirSync(path.join(dir, 'routes'));
    fs.writeFileSync(path.join(dir, 'routes', 'content-check.json'), JSON.stringify(ROUTE));
    asked = 0;
    answered = new Promise((r) => { release = r; });
  });
  afterEach(() => {
    release();
    fs.rmSync(dir, { recursive: true, force: true });
  });
  // A client of the one store, as each agent's client in one process is on the default audit file
  const client = (db = path.join(dir, 'a.db')) => new HIITL({
    environment: 'dev', agent_id: 'poster', org_id: ORG, mode: 'RESPECT_POLICY',
    policy_path: path.join(dir, 'policy.json'), routes_path: path.join(dir, 'routes'),
    audit_db_path: db,
    route_fetch: (async () => {
      asked += 1;
      await answered;
      return new Response(JSON.stringify({ verdict: 'approved' }), { status: 200 });
    }) as typeof fetch,
  });

  it('two clients of one store under one new key: the second follows the first, which asks a sync route', async () => {
    const [a, b] = [client(), client()];
    const first = a.evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_ts' });
    const second = b.evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_ts' });
    release();
    const [d1, d2] = await Promise.all([first, second]);

    expect(d2.action_id).toBe(d1.action_id);
    expect(asked).toBe(1);
    expect(new AuditLogger(path.join(dir, 'a.db')).count()).toBe(1);
    expect((AuditLogger as any)._tails.size).toBe(0);
  });

  // A second name of the store at dir/a.db, made once the store exists, as a mount or a link makes one
  const names: [string, () => string][] = [
    ['a directory link', () => { fs.symlinkSync(dir, path.join(dir, 'alias'), 'dir'); return path.join(dir, 'alias', 'a.db'); }],
    ['a file link', () => { fs.symlinkSync(path.join(dir, 'a.db'), path.join(dir, 'link.db')); return path.join(dir, 'link.db'); }],
    ['a hard link', () => { fs.linkSync(path.join(dir, 'a.db'), path.join(dir, 'hard.db')); return path.join(dir, 'hard.db'); }],
  ];
  for (const [form, another] of names) {
    // A store is its file, whatever name reaches it: the holds are the file's (HTL-29 review, condition 3)
    it(`one store reached through ${form}: two clients under one new key give one route ask and one record`, async () => {
      const a = client();
      const b = client(another());
      const first = a.evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_ts' });
      const second = b.evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_ts' });
      release();
      const [d1, d2] = await Promise.all([first, second]);

      expect(d2.action_id).toBe(d1.action_id);
      expect(asked).toBe(1);
      expect(new AuditLogger(path.join(dir, 'a.db')).count()).toBe(1);
      expect((AuditLogger as any)._tails.size).toBe(0);
    });
  }

  it('a call under another key decides while the first waits on its route', async () => {
    const h = client();
    const first = h.evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_a' });
    const other = h.evaluate({ action: 'read_feed', idempotency_key: 'idem_row160_b' });

    expect(other instanceof Promise).toBe(false);
    expect((other as any).decision).toBe('ALLOW');
    release();
    await first;
  });

  it('a call in another store under the same key decides while the first waits on its route', async () => {
    const first = client().evaluate({ action: 'publish_post', parameters: { body: 'hello' }, idempotency_key: 'idem_row160_ts' });
    const elsewhere = new HIITL({
      environment: 'dev', agent_id: 'reader', org_id: ORG, mode: 'RESPECT_POLICY',
      policy_path: path.join(dir, 'policy.json'), audit_db_path: path.join(dir, 'b.db'),
    }).evaluate({ action: 'read_feed', idempotency_key: 'idem_row160_ts' });

    expect(elsewhere instanceof Promise).toBe(false);
    expect((elsewhere as any).decision).toBe('ALLOW');
    release();
    await first;
  });
});
