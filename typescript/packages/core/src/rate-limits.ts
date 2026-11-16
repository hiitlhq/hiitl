/**
 * The set-level rate limit compiled to rules (policy_format.md "Rate-limit rules", "One representation: the rule's";
 * T47). Mirrors python/hiitl/core/rate_limits.py: entry i of a set's `metadata.rate_limits` becomes the active rule
 * `metadata.rate_limits[i]` matching every envelope, carrying its entry in `metadata.compiled_from`; the entry leaves
 * the set's metadata — nothing is dropped. An entry key, scope or window outside the table is refused with the allowed
 * values.
 */

import type { Decision, RateLimit, RateLimitRule, Remediation } from './types.js';
import { ERROR_MESSAGES } from './error-decisions.js';

/**
 * A windowed rule's counter state (decision_response.md **Rate Limit Counter State**): the rule's scope, its window as
 * `<window_seconds>s`, its limit, the calls the window holds, and when its oldest call leaves it.
 */
export function counterState(rule: RateLimitRule, current: number, resetAt: Date): RateLimit {
  return {
    scope: rule.scope,
    window: `${rule.window_seconds}s`,
    limit: rule.limit,
    current,
    reset_at: resetAt.toISOString(),
  };
}

/**
 * The window with the least headroom left (`limit - current`); on a tie, the first listed (R-0008: "Decisions must
 * include current counter state snapshot" — one snapshot, the window nearest its limit).
 */
export function tightest(states: RateLimit[]): RateLimit {
  return states.reduce((best, s) => (s.limit - s.current < best.limit - best.current ? s : best));
}

/**
 * A `rate_limit` remediation's details are the exceeded window's counter state (policy_format.md **Remediation on
 * Rules**); every other type is the rule's as written.
 */
export function withCounter(rem: Remediation, state: RateLimit): Remediation {
  if (rem.type !== 'rate_limit') return rem;
  return { ...rem, details: { ...(rem.details ?? {}), ...state } };
}

/**
 * The evaluation's decision, refused by `rule`'s window (policy_format.md **Rate-limit rules**): RATE_LIMIT /
 * RATE_LIMIT_EXCEEDED, the rule in `matched_rules`, its counter state and its own remediation. A copy, so nothing the
 * evaluation recorded (staged observations, the listed windows, the envelope hash) is dropped.
 */
export function limitExceeded(decision: Decision, rule: RateLimitRule, current: number, resetAt: Date): Decision {
  const state = counterState(rule, current, resetAt);
  return {
    ...decision,
    decision: 'RATE_LIMIT',
    allowed: false,
    reason_codes: ['RATE_LIMIT_EXCEEDED'],
    matched_rules: [{ rule_name: rule.rule_name, policy_set: rule.policy_set, priority: rule.priority }],
    rate_limit: state,
    remediation: rule.remediation ? withCounter(rule.remediation, state) : undefined,
  };
}

/**
 * A limiter that failed never lets the call through: an ambiguous failure blocks (safe by default). BLOCK /
 * RATE_LIMIT_SERVICE_ERROR with an authored `error`, in the hosted service and the SDK alike; the caller logs the
 * cause, which the message never carries (error-decisions.ts ERROR_MESSAGES). A copy of the evaluation's ALLOW, as a
 * refusal is: no rule decided it, and no window was read.
 */
export function limiterFailed(decision: Decision): Decision {
  return {
    ...decision,
    decision: 'BLOCK',
    allowed: false,
    reason_codes: ['RATE_LIMIT_SERVICE_ERROR'],
    matched_rules: undefined,
    rate_limit: undefined,
    remediation: undefined,
    error: {
      code: 'RATE_LIMIT_SERVICE_ERROR',
      message: ERROR_MESSAGES.RATE_LIMIT_SERVICE_ERROR,
    },
  };
}

export const SET_SCOPE: Record<string, string> = {
  org: 'org',
  agent_id: 'agent',
  agent: 'agent',
  user: 'user',
  user_id: 'user',
  tool: 'action',
  'org:tool': 'action',
  'user:tool': 'user_action',
};
export const WINDOW_SECONDS: Record<string, number> = { second: 1, minute: 60, hour: 3600, day: 86400 };
// what the limiter applied when an entry left a key out: the same throttle, compiled
const SET_DEFAULTS = { scope: 'org', window: 'hour', limit: 1000 };
const ENTRY_KEYS = ['scope', 'limit', 'window', 'window_seconds'];

export const compiledName = (i: number): string => `metadata.rate_limits[${i}]`;

const HOW =
  'write the throttle as a RATE_LIMIT rule with `rate_limit: {limit, window_seconds, scope}` (policy_format.md ' +
  '"Rate-limit rules")';

const isObject = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);

/** The set with its `metadata.rate_limits` compiled, and the refusals (empty when it compiles). */
export function compileSetLimits(data: unknown): { data: unknown; problems: string[] } {
  if (!isObject(data) || !isObject(data.metadata) || !('rate_limits' in data.metadata)) return { data, problems: [] };
  const meta = data.metadata;
  const raw = meta.rate_limits;
  const entries = Array.isArray(raw) ? raw : [raw];
  const rules = Array.isArray(data.rules) ? [...data.rules] : [];
  const problems: string[] = [];
  const compiled: unknown[] = [];
  entries.forEach((e, i) => {
    const path = compiledName(i);
    if (!isObject(e)) {
      problems.push(`${path}: a set-level rate limit is an object with ${ENTRY_KEYS.join(', ')}; ${HOW}`);
      return;
    }
    const extra = Object.keys(e).filter((k) => !ENTRY_KEYS.includes(k)).sort();
    if (extra.length) {
      problems.push(`${path}: ${extra.map((k) => `'${k}'`).join(', ')} is not a set-level rate-limit key (allowed: ` +
        `${ENTRY_KEYS.join(', ')}); ${HOW}`);
      return;
    }
    const scope = (e.scope ?? SET_DEFAULTS.scope) as string;
    if (!Object.hasOwn(SET_SCOPE, scope)) {
      problems.push(`${path}: scope '${scope}' is not one of ${Object.keys(SET_SCOPE).join(', ')}; ${HOW}`);
      return;
    }
    let windowSeconds: unknown;
    if ('window_seconds' in e) windowSeconds = e.window_seconds;
    else {
      const w = (e.window ?? SET_DEFAULTS.window) as string;
      if (!Object.hasOwn(WINDOW_SECONDS, w)) {
        problems.push(`${path}: window '${w}' is not one of ${Object.keys(WINDOW_SECONDS).join(', ')} (or give ` +
          `window_seconds); ${HOW}`);
        return;
      }
      windowSeconds = WINDOW_SECONDS[w];
    }
    compiled.push({
      name: path,
      priority: 0,
      lifecycle_stage: 'active',
      description: `the set-level throttle ${path}, compiled to a rule on load (T47)`,
      conditions: { field: 'action', operator: 'exists', value: true },
      decision: 'RATE_LIMIT',
      reason_code: 'RATE_LIMIT_EXCEEDED',
      rate_limit: { limit: e.limit ?? SET_DEFAULTS.limit, window_seconds: windowSeconds, scope: SET_SCOPE[scope] },
      metadata: { compiled_from: { path, entry: e } },
    });
  });
  const rest = Object.fromEntries(Object.entries(meta).filter(([k]) => k !== 'rate_limits'));
  return { data: { ...data, rules: [...rules, ...compiled], metadata: rest }, problems };
}
