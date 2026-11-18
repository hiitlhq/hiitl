/**
 * The policy models after the T-130 follow-up (policy_format.md 2.2) — the
 * TypeScript twin of python/hiitl/core/tests/test_t130_followup.py.
 *
 * H6 (S2): every model of the format refuses a field it does not define; `enabled` / `mode` refused naming
 * `lifecycle_stage`. H1 (T47): `metadata.rate_limits` compiled to windowed RATE_LIMIT rules on load.
 */
import { describe, it, expect } from 'vitest';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { PolicySetSchema, ENVELOPE_SCHEMA_VERSION } from '../../src/types.js';

const ALLOW_ALL = {
  name: 'allow_all',
  description: 'd',
  priority: 1,
  conditions: { field: 'action', operator: 'exists', value: true },
  decision: 'ALLOW',
  reason_code: 'OK',
};
const set = (rules: unknown[], extra: Record<string, unknown> = {}) => ({
  name: 't', version: 'v1.0.0', description: 'A set built for one check',
  scope: { org_id: 'org_1234567890abcdef', environment: 'prod' }, rules, ...extra,
});
const env = {
  schema_version: ENVELOPE_SCHEMA_VERSION,
  org_id: 'org_1234567890abcdef',
  environment: 'prod',
  agent_id: 'bot',
  action_id: 'act_00000000000000000000',
  idempotency_key: 'k',
  action: 'pay',
  timestamp: '2026-10-08T00:00:00Z',
  signature: '0'.repeat(64),
  target: {},
  parameters: {},
};
const refusal = (input: unknown): string => {
  const r = PolicySetSchema.safeParse(input);
  expect(r.success).toBe(false);
  return r.success ? '' : JSON.stringify(r.error.issues);
};
const diagnosticIssues = (text: string): any[] => {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { parsed = undefined; }
  expect(parsed).toEqual(expect.any(Array));
  return parsed as any[];
};

describe('H6: no policy field is dropped', () => {
  it('refuses enabled: false naming lifecycle_stage', () => {
    const m = refusal(set([{ ...ALLOW_ALL, enabled: false }]));
    expect(m).toContain('lifecycle_stage');
    expect(m).toContain('disabled');
  });
  it('refuses mode naming lifecycle_stage', () => {
    expect(refusal(set([{ ...ALLOW_ALL, mode: 'observe' }]))).toContain('lifecycle_stage');
  });
  for (const where of ['rule', 'set', 'condition', 'scope', 'remediation', 'rate_limit']) {
    it(`refuses an undefined field on the ${where}`, () => {
      const rule: Record<string, unknown> = { ...ALLOW_ALL };
      const s: Record<string, unknown> = set([rule]);
      if (where === 'rule') rule.colour = 'red';
      else if (where === 'set') s.colour = 'red';
      else if (where === 'condition') rule.conditions = { ...(rule.conditions as object), colour: 'red' };
      else if (where === 'scope') rule.scope = { agents: ['bot'], colour: 'red' };
      else if (where === 'remediation')
        Object.assign(rule, { decision: 'BLOCK', remediation: { message: 'm', suggestion: 's', type: 'custom', colour: 'red' } });
      else Object.assign(rule, { decision: 'RATE_LIMIT', rate_limit: { limit: 1, window_seconds: 60, colour: 'red' } });
      expect(refusal(s)).toContain('colour');
    });
  }
  it('a disabled kill switch does not bind', () => {
    const kill = { ...ALLOW_ALL, name: 'stop', priority: 1000, lifecycle_stage: 'disabled', decision: 'KILL_SWITCH', reason_code: 'STOP' };
    const d = new PolicyEvaluator().evaluate(env as never, set([kill, ALLOW_ALL]) as never);
    expect(d.decision).toBe('ALLOW');
    expect(d.reason_codes).toEqual(['OK']);
  });
});

describe('H1: metadata.rate_limits compiled to rules on load', () => {
  const compiled = (entry: unknown) => {
    const ps = PolicySetSchema.parse(set([ALLOW_ALL], { metadata: { rate_limits: [entry], tags: ['x'] } }));
    return { ps, rule: ps.rules.find((r) => r.name === 'metadata.rate_limits[0]')! };
  };
  const scopes: Array<[string, string]> = [
    ['org', 'org'], ['agent_id', 'agent'], ['agent', 'agent'], ['user', 'user'], ['user_id', 'user'],
    ['tool', 'action'], ['org:tool', 'action'], ['user:tool', 'user_action'],
  ];
  for (const [scope, want] of scopes) {
    it(`compiles scope ${scope} to ${want}`, () => {
      const { rule } = compiled({ scope, limit: 5, window: 'minute' });
      expect(rule.rate_limit).toEqual({ limit: 5, window_seconds: 60, scope: want });
    });
  }
  for (const [w, sec] of [['second', 1], ['minute', 60], ['hour', 3600], ['day', 86400]] as const) {
    it(`compiles window ${w} to ${sec}s`, () => {
      expect(compiled({ scope: 'org', limit: 3, window: w }).rule.rate_limit!.window_seconds).toBe(sec);
    });
  }
  it('is the same throttle and drops nothing', () => {
    const entry = { scope: 'agent_id', limit: 100 };
    const { ps, rule } = compiled(entry);
    expect(rule.decision).toBe('RATE_LIMIT');
    expect(rule.lifecycle_stage).toBe('active');
    expect(rule.priority).toBe(0);
    expect(rule.reason_code).toBe('RATE_LIMIT_EXCEEDED');
    expect(rule.rate_limit!.window_seconds).toBe(3600);
    expect(rule.metadata!.compiled_from).toEqual({ path: 'metadata.rate_limits[0]', entry });
    expect(ps.metadata).toEqual({ tags: ['x'] });
    expect(compiled({}).rule.rate_limit).toEqual({ limit: 1000, window_seconds: 3600, scope: 'org' });
  });
  it('the evaluator lists a compiled throttle for the limiter', () => {
    const d = new PolicyEvaluator().evaluate(env as never,
      set([ALLOW_ALL], { metadata: { rate_limits: [{ scope: 'agent_id', window: 'hour', limit: 2 }] } }) as never);
    expect(d.decision).toBe('ALLOW');
    expect(d.rate_limit_rules!.map((r) => [r.rule_name, r.limit, r.window_seconds, r.scope]))
      .toEqual([['metadata.rate_limits[0]', 2, 3600, 'agent']]);
  });
  for (const [entry, named] of [[{ scope: 'team', limit: 1 }, 'team'], [{ scope: 'org', window: 'week', limit: 1 }, 'week'],
    [{ scope: 'org', limit: 1, burst: 4 }, 'burst']] as const) {
    it(`refuses an entry outside the table (${named})`, () => {
      const m = refusal(set([ALLOW_ALL], { metadata: { rate_limits: [entry] } }));
      expect(m).toContain(named);
      const issues = diagnosticIssues(m);
      const locations = issues.map(issue => {
        expect(issue).toEqual(expect.objectContaining({ path: expect.any(Array) }));
        if (issue.path.length) return JSON.stringify(issue.path);
        expect(issue.message).toContain('metadata.rate_limits[0]');
        return JSON.stringify(['metadata', 'rate_limits', 0]);
      });
      // The protocol declares the named location, not duplicate diagnostic count.
      expect(new Set(locations)).toEqual(new Set([JSON.stringify(['metadata', 'rate_limits', 0])]));
    });
  }
  it('refuses a singleton object and compiles its declared list form', () => {
    const entry = { scope: 'org', limit: 7 };
    const m = refusal(set([ALLOW_ALL], { metadata: { rate_limits: entry } }));
    expect(diagnosticIssues(m)).toMatchObject([{ path: ['metadata', 'rate_limits'], expected: 'array' }]);
    const ps = PolicySetSchema.parse(set([ALLOW_ALL], { metadata: { rate_limits: [entry] } }));
    expect(ps.rules.map((r) => r.name)).toEqual(['allow_all', 'metadata.rate_limits[0]']);
  });
  it('refuses a rule already named like a compiled one', () => {
    const m = refusal(set([{ ...ALLOW_ALL, name: 'metadata.rate_limits[0]' }], { metadata: { rate_limits: [{ limit: 1 }] } }));
    expect(m).toContain('metadata.rate_limits[0]');
  });
});

describe('K: a folded rule cites a list; a dependency rides on the rule (policy_format.md 2.3)', () => {
  const cite = (atom: string) => ({ atom_id: atom, standard: 'owasp_agentic_top_10' });
  it('loads a rule citing several determinations and carrying its dependency', () => {
    const rule = { ...ALLOW_ALL, requirement_citation: [cite('at-0002'), cite('at-0023')],
                   waits_on: { kind: 'verifier', target: 'principal' } };
    const r = PolicySetSchema.safeParse(set([rule]));
    expect(r.success).toBe(true);
    expect(PolicySetSchema.safeParse(set([{ ...ALLOW_ALL, requirement_citation: cite('at-0002') }])).success).toBe(true);
  });
  it('refuses a dependency of a kind the format does not define, or with a field it does not define', () => {
    expect(refusal(set([{ ...ALLOW_ALL, waits_on: { kind: 'instrument', target: 'x' } }]))).toContain('kind');
    expect(refusal(set([{ ...ALLOW_ALL, waits_on: { kind: 'verifier', target: 'principal', colour: 'red' } }])))
      .toContain('colour');
  });
});

describe("K5': the route and hiitl_record dependency kinds; the DECLARED placeholder (policy_format.md 2.5)", () => {
  it('loads both kinds', () => {
    for (const kind of ['route', 'hiitl_record']) {
      expect(PolicySetSchema.safeParse(set([{ ...ALLOW_ALL, waits_on: { kind, target: 'x' } }])).success).toBe(true);
    }
  });
  it('refuses the removed session kind', () => {
    expect(refusal(set([{ ...ALLOW_ALL, waits_on: { kind: 'session', target: 'x' } }]))).toContain('kind');
  });
  it('a declared value never matches', () => {
    // not_equals would match 'bot' if the rule were evaluated: only skipping it leaves no match
    const rule = { ...ALLOW_ALL, conditions: { field: 'agent_id', operator: 'not_equals', value: { $declared: 'the component' } } };
    const d = new PolicyEvaluator().evaluate(env as never, PolicySetSchema.parse(set([rule])) as never);
    expect(d.reason_codes).not.toContain('OK');
  });
});

describe('2.6: field references, array-left in / not_in, conforms_to (policy_format.md)', () => {
  const principal = { sub: 'u', scopes: ['read', 'write'], verified_by: 'sdk_verifier' };
  const schema = { type: 'object', properties: { id: { type: 'string' }, n: { type: 'number' } }, required: ['id'], additionalProperties: false };
  const matches = (conditions: unknown, extra: Record<string, unknown>) => {
    const rule = { ...ALLOW_ALL, name: 't', decision: 'BLOCK', reason_code: 'T', conditions };
    const d = new PolicyEvaluator().evaluate({ ...env, ...extra } as never, PolicySetSchema.parse(set([rule])) as never);
    return d.reason_codes.length === 1 && d.reason_codes[0] === 'T';
  };
  const scopes = { field: 'requested_scopes', operator: 'not_in', value: { $field: 'principal.scopes' } };
  it('a reference resolves against the same envelope; one that resolves to nothing is false', () => {
    expect(matches(scopes, { requested_scopes: ['read', 'admin'], principal })).toBe(true);
    expect(matches(scopes, { requested_scopes: ['read'], principal })).toBe(false);
    expect(matches(scopes, { requested_scopes: ['admin'] })).toBe(false);
  });
  it('an array on the left of in is a subset test', () => {
    const c = { field: 'sensitivity', operator: 'in', value: ['money', 'identity'] };
    expect(matches(c, { sensitivity: ['money'] })).toBe(true);
    expect(matches(c, { sensitivity: ['money', 'regulated'] })).toBe(false);
  });
  it('conforms_to reads the parameter schema', () => {
    const c = { field: 'parameters', operator: 'conforms_to', value: schema };
    expect(matches(c, { parameters: { id: 'a', n: 2 } })).toBe(true);
    expect(matches(c, { parameters: { id: 'a', x: 1 } })).toBe(false);
    expect(matches(c, { parameters: { id: 'a', n: 'two' } })).toBe(false);
    expect(matches(c, { parameters: { n: 2 } })).toBe(false);
  });
  it('a malformed reference or schema is refused at load', () => {
    expect(refusal(set([{ ...ALLOW_ALL, conditions: { field: 'parameters', operator: 'conforms_to', value: { ...schema, pattern: 'x' } } }]))).toContain('pattern');
    expect(refusal(set([{ ...ALLOW_ALL, conditions: { field: 'action', operator: 'exists', value: { $field: 'agent_id' } } }]))).toContain('never a field reference');
  });
});
