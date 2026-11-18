/**
 * Row 225 (HTL-27), Codex's review of PR #13, condition 2 and its class: a name the input supplies is a member only
 * where the object holds it as data, never one it inherits (policy_format.md 2.17). The SDK reads the service's error
 * code against its own table of lifecycle refusals. Design: the HTL-27 test design, C2.9 and C2.10. The core's cells
 * are core/tests/unit/row225.test.ts.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import ts from 'typescript';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HIITL } from '../../src/client.js';
import { LifecycleError, ServerError } from '../../src/exceptions.js';

const clients: HIITL[] = [];

afterEach(() => {
  clients.splice(0).forEach((c) => c.close());
  vi.unstubAllGlobals();
});

describe("row 225, Codex's condition 2: the SDK reads a name the service sends as data", () => {
  it('C2.9: a refusal naming a code the lifecycle table does not hold is a ServerError', async () => {
    const actionId = 'act_r225inherited000000';
    const reply = { status: 409, ok: false, headers: new Headers(),
      json: () => Promise.resolve({ detail: { error: 'constructor', message: 'The result was not taken.' } }) } as Response;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply));
    const h = new HIITL({
      environment: 'dev', agent_id: 'refund-agent', org_id: 'org_test000000000000000', api_key: 'sk_test_1234567890abcdef',
      server_url: 'https://ecp.example', evaluation: 'remote', max_retries: 0, signature_key: 's'.repeat(32),
      audit_db_path: ':memory:',
    });
    clients.push(h);

    const refused = await h.recordResult(actionId, 'succeeded').catch((e: Error) => e);
    expect(refused).not.toBeInstanceOf(LifecycleError);
    expect(refused).toBeInstanceOf(ServerError);
    expect([(refused as ServerError).status_code, (refused as ServerError).error_code]).toEqual([409, 'constructor']);
  });

  it('C2.10: no `in` in the source reads a name the input supplies', () => {
    // the class's gate, by the compiler's grammar: a computed name is read with Object.hasOwn; a literal left names
    // no member every object inherits
    const inherited = new Set(Object.getOwnPropertyNames(Object.prototype));
    const src = join(__dirname, '../../src');
    const found: string[] = [];
    for (const f of readdirSync(src, { recursive: true }).map(String).filter((f) => f.endsWith('.ts'))) {
      const file = ts.createSourceFile(f, readFileSync(join(src, f), 'utf8'), ts.ScriptTarget.Latest, true);
      const walk = (n: ts.Node): void => {
        if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.InKeyword
          && !(ts.isStringLiteralLike(n.left) && !inherited.has(n.left.text))) {
          found.push(`${f}:${file.getLineAndCharacterOfPosition(n.getStart()).line + 1}: ${n.getText()}`);
        }
        ts.forEachChild(n, walk);
      };
      walk(file);
    }
    expect(found).toEqual([]);
  });
});
