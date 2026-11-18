/**
 * A sync route's answer re-entering evaluation (policy_format.md 2.7 "Enrichment context"; routes.md "A sync route's
 * answer re-enters evaluation"; decision_response.md 1.7; TICKET-046). Mirrors python/hiitl/core/routing.py.
 *
 * Pure: the steps decide which route to ask, what to send, which of the answer's fields re-enter and what a missing
 * answer does. The asking (the SDK's HTTP POST) is the caller's, injected as `ask(route, payload)`, rejecting with
 * `RouteUnanswered` when there is no answer.
 */

import type { Decision, RouteAsked } from './types.js';
import type { Enrichment } from './evaluator.js';
import { RouteAuthHeaderSchema } from './route-types.js';

export const UNANSWERED = 'ROUTE_UNANSWERED';
export const SYNC_DIRECTION = 'bidirectional';
export const DEFAULT_TIMEOUT_SECONDS = 30;
const UNITS: Record<string, number> = { s: 1, m: 60, h: 3600 };
// routes.md Validation Rules, "The party that sends reads the `auth`": the types an SDK sends, and the one form of
// reference it resolves, a variable of its own process written `env:<NAME>`.
export const SENT_AUTH = ['bearer_token', 'api_key'];
export const SECRET_REF_SCHEME = 'env';
export const RECEIVING_DIRECTION = 'inbound';
/** The `header` an `auth` names when it names none: the schema's own default. */
const AUTH_HEADER_DEFAULT: string = RouteAuthHeaderSchema.parse(undefined);

/** The route gave no answer: a timeout, an error response, or a body that is not an object. */
export class RouteUnanswered extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RouteUnanswered';
  }
}

export type RouteConfig = Record<string, any>;

export function isSync(route: RouteConfig | null | undefined): boolean {
  return !!route && route.direction === SYNC_DIRECTION;
}

/** [route, rule name] when the decision is a ROUTE whose rule names a sync route not yet asked; else null. */
export function toAsk(
  decision: Decision,
  routeOf: (name: string) => RouteConfig | null | undefined,
  asked: Set<string>
): [RouteConfig, string] | null {
  if (decision.decision !== 'ROUTE' || !decision.route_ref || asked.has(decision.route_ref)) return null;
  const route = routeOf(decision.route_ref);
  if (!isSync(route)) return null;
  return [route as RouteConfig, decision.matched_rules?.[0]?.rule_name ?? ''];
}

function at(obj: any, path: string): unknown {
  let cur = obj;
  for (const part of path.split('.')) {
    if (cur == null || typeof cur !== 'object' || Array.isArray(cur) || !Object.hasOwn(cur, part)) return null;
    cur = cur[part];   // a member the object holds as data (policy_format.md 2.17)
  }
  return cur ?? null;
}

/** {route, rule, action, fields}: the values at the route's `context.fields` paths, or the whole envelope. */
export function payload(route: RouteConfig, rule: string, envelope: Record<string, any>): Record<string, unknown> {
  const ctx = route.context ?? {};
  const paths: string[] = (ctx.fields ?? []).map((f: any) => f?.field_path).filter(Boolean);
  const body: Record<string, unknown> = { route: route.name };
  if (ctx.include_policy_ref ?? true) body.rule = rule;
  body.action = envelope.action;
  body.fields = paths.length ? Object.fromEntries(paths.map((p) => [p, at(envelope, p)])) : { ...envelope };
  return body;
}

export function declared(route: RouteConfig): [string[], string[]] {
  const rs = route.response_schema ?? {};
  return [[...(rs.required_fields ?? [])], [...(rs.optional_fields ?? [])]];
}

/** The answer's declared fields; throws RouteUnanswered when it is not an object or lacks a required field. */
export function answerFields(route: RouteConfig, body: unknown): Record<string, unknown> {
  if (body == null || typeof body !== 'object' || Array.isArray(body)) {
    throw new RouteUnanswered('the answer is not a JSON object');
  }
  const answer = body as Record<string, unknown>;
  const b = (f: string): unknown => (Object.hasOwn(answer, f) ? answer[f] : undefined);  // as data (2.17)
  const [required, optional] = declared(route);
  const missing = required.filter((f) => b(f) == null);
  if (missing.length) {
    throw new RouteUnanswered(`the answer lacks the required field(s) ${missing.map((f) => `\`${f}\``).join(', ')}`);
  }
  return Object.fromEntries([...required, ...optional].filter((f) => b(f) != null).map((f) => [f, b(f)]));
}

export function timeoutSeconds(route: RouteConfig): number {
  const m = /^(\d+)([smh])$/.exec(String(route.sla?.timeout ?? ''));
  return m ? Number(m[1]) * UNITS[m[2]] : DEFAULT_TIMEOUT_SECONDS;
}

/** `fail_open` alone; `fail_closed`, and `escalate` / `extend` until escalation ladders exist, fail closed. */
export function failsOpen(route: RouteConfig): boolean {
  return route.sla?.timeout_action === 'fail_open';
}

/**
 * Why the SDK cannot send the `auth` a sending route declares, or null when it can or the route declares none
 * (routes.md Validation Rules, "The party that sends reads the `auth`"): a type it does not send, a reference that is
 * not `env:<NAME>`, or a variable unset or empty in this process. An inbound route's `auth` is what the sender presents
 * to hiitl, so it is not read here.
 */
export function authRefusal(route: RouteConfig, environ: Record<string, string | undefined> = process.env): string | null {
  const auth = route.auth;
  if (!auth || route.direction === RECEIVING_DIRECTION) return null;
  const ref = String(auth.secret_ref ?? '');
  if (!SENT_AUTH.includes(auth.type)) {
    return `route '${route.name}' declares auth type ${JSON.stringify(auth.type)}, which the SDK does not send. It ` +
      `sends ${SENT_AUTH.join(' or ')}, read from a variable of its own process (routes.md, "The party that sends ` +
      'reads the `auth`").';
  }
  const colon = ref.indexOf(':');
  const variable = colon < 0 ? '' : ref.slice(colon + 1);
  if (ref.slice(0, colon) !== SECRET_REF_SCHEME || !variable) {
    return `route '${route.name}' reads its secret from ${JSON.stringify(ref)}. The SDK reads a variable of its own ` +
      `process, written '${SECRET_REF_SCHEME}:<NAME>', e.g. secret_ref: "${SECRET_REF_SCHEME}:ROUTE_TOKEN".`;
  }
  if (!(Object.hasOwn(environ, variable) && environ[variable])) {   // as data (2.17)
    return `route '${route.name}' reads its secret from ${variable}, which is unset or empty in this process. Set ` +
      `${variable}, or remove the route's auth if its endpoint takes none.`;
  }
  return null;
}

/**
 * The header carrying the secret the route's `auth` declares, `{}` when it declares none. A request never goes without
 * the credential its route declares: when the SDK cannot send it, RouteUnanswered names why, and the route's SLA
 * decides.
 */
export function authHeaders(route: RouteConfig, environ: Record<string, string | undefined> = process.env): Record<string, string> {
  const reason = authRefusal(route, environ);
  if (reason) throw new RouteUnanswered(reason);
  const auth = route.auth;
  if (!auth) return {};
  const ref = String(auth.secret_ref);
  const secret = environ[ref.slice(ref.indexOf(':') + 1)] as string;
  return { [auth.header ?? AUTH_HEADER_DEFAULT]: auth.type === 'bearer_token' ? `Bearer ${secret}` : secret };
}

/**
 * Evaluate; while the decision asks a sync route not yet asked, ask it and evaluate again (each route once).
 * An unanswered route fails closed (the decision stays ROUTE, ROUTE_UNANSWERED) unless its SLA says fail_open.
 */
export async function evaluateWithRoutes(
  evaluate: (enrichment: Enrichment | null) => Decision,
  routeOf: (name: string) => RouteConfig | null | undefined,
  ask: (route: RouteConfig, payload: Record<string, unknown>) => Promise<unknown>,
  envelope: Record<string, any>,
  first?: Decision
): Promise<Decision> {
  const enrichment: Enrichment = {};
  const routes: RouteAsked[] = [];
  const asked = new Set<string>();
  let closed = false;
  let decision = first ?? evaluate(null);
  for (;;) {
    const next = toAsk(decision, routeOf, asked);
    if (!next) break;
    const [route, rule] = next;
    asked.add(route.name);
    let error: string | null = null;
    let fields: Record<string, unknown> = {};
    try {
      fields = answerFields(route, await ask(route, payload(route, rule, envelope)));
    } catch (e: any) {
      if (!(e instanceof RouteUnanswered)) throw e;
      error = e.message || 'no answer';
    }
    if (error === null) {
      enrichment[route.name] = fields;
      routes.push({ rule_name: rule, route: route.name, outcome: 'answered', fields: Object.keys(fields) });
    } else if (failsOpen(route)) {
      enrichment[route.name] = {};
      routes.push({ rule_name: rule, route: route.name, outcome: 'failed_open', fields: [], error });
    } else {
      routes.push({ rule_name: rule, route: route.name, outcome: 'unanswered', error });
      closed = true;
      break;
    }
    decision = evaluate(enrichment);
  }
  if (!routes.length) return decision;
  const out: Decision = { ...decision, routes };
  if (Object.keys(enrichment).length) out.enrichment = enrichment;
  if (closed && !out.reason_codes.includes(UNANSWERED)) out.reason_codes = [...out.reason_codes, UNANSWERED];
  return out;
}
