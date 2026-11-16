import {z} from 'zod';
import {shapes as numericDeclarations} from './numeric-declarations.js';
import { assertNumericDomain, assertSchemaNumbers, ResultNumberSchema, NumericDomainError, EnvelopeSchema, copySuppliedInput } from '@hiitl/core';
/**
 * HTTP client for hosted mode communication with the ECP server.
 *
 * Uses native fetch (Node 18+) with retry logic. The body is the envelope the SDK built and signed. An action's
 * result goes to POST /v1/actions/{action_id}/result (event_format.md "The lifecycle"). An outage is answered as
 * CONTROL_PLANE_UNAVAILABLE under the client's fail_mode, behind a circuit breaker, and recorded in the local store
 * (decision_response.md "Error Handling", Example 9, "Where the error is answered"; R-0002). What the service could
 * not take is held in that store and pushed before the next call (Stop B (i), row 200).
 */

import fs from 'node:fs';
import type { Decision, Envelope, ExecutionResult } from '@hiitl/core';
import {
  DecisionSchema, LIFECYCLE_MESSAGES, Redaction, auditWriteFailed, envelopeHash, httpsRefusal, outage,
} from '@hiitl/core';
import { AuditLogger } from './audit.js';
import { CircuitBreaker } from './circuit-breaker.js';
import { HostedModeConfigSchema, type HostedModeConfig } from './config.js';
import { AuditLogError, ConfigurationError, EnvelopeValidationError, LifecycleError, ServerError, NetworkError } from './exceptions.js';
import { consoleLogger } from './logger.js';
import { SDK_VERSION } from './sync-client.js';
import { DEFAULTS as SYNC_DEFAULTS, settleUpload } from './sync-engine.js';

/** Status codes that trigger a retry. */
const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);
/**
 * The members the core decision schema declares, read from the schema, never listed here (row 204; R-0872: "no field
 * is ever silently dropped"). The numeric preprocessor's output object declares the decision members.
 */
const DECISION_MEMBERS = Object.keys(DecisionSchema.shape);
/** An outage: its reason, and its cause when a send met it (none when the open breaker held the call back). */
type Unanswered = [reason: string, cause?: string];
/** A response the service answered: its status, and its body, read once. */
type Answer = { status: number; data: any };

/**
 * Hosted mode HTTP client for communicating with the ECP server.
 */

/** The hosted principal's header. */
export const PRINCIPAL_TOKEN_HEADER = 'X-Hiitl-Principal-Token';

const AckNumbers=z.unknown().meta(numericDeclarations.audit_ack);
const ADMITTED_CONFIG=Symbol('SDK-owned admitted hosted settings');
function admitResponse(data:unknown,status:number,schema:Parameters<typeof assertSchemaNumbers>[1]=DecisionSchema):void {
  try {assertSchemaNumbers(data,schema);} catch(error) {
    if(!(error instanceof NumericDomainError))throw error;
    throw new ServerError(status,'UNKNOWN_ERROR',error.message);
  }
}

export class HostedClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly config: HostedModeConfig;
  /** R-0002 "circuit breaker": the sync engine's own, at its own defaults (row 198: no setting). */
  readonly breaker = new CircuitBreaker('hosted');
  /**
   * The local store at audit_db_path: what the service could not take, opened when the client first needs it (Stop B
   * (i)); its record takes the SDK's declaration (event_format.md §Redaction).
   */
  private store?: AuditLogger;
  private readonly redaction: Redaction;
  /**
   * Whether the store may hold what is not yet pushed: at construction, and whenever the client holds something new.
   * A push the service answered clears it, so a refused record is not re-sent before every call.
   */
  private unpushed = true;
  private sequence = 0;

  constructor(config: HostedModeConfig, redaction: Redaction = Redaction.declared(), admitted?:symbol) {
    if(admitted!==ADMITTED_CONFIG){
      try{assertSchemaNumbers(config,HostedModeConfigSchema);}catch(error){
        if(!(error instanceof NumericDomainError))throw error;
        throw new ConfigurationError(error.message);
      }
    }
    const refusal = httpsRefusal(config.server_url, 'server_url');   // the API key goes there (sync_engine.md §8)
    if (refusal) throw new ConfigurationError(refusal);
    this.config = config;
    this.baseUrl = config.server_url;
    this.apiKey = config.api_key;
    this.timeout = config.timeout;
    this.maxRetries = config.max_retries;
    this.redaction = redaction;
  }

  /** @internal Consume only the settings the SDK constructor already admitted. */
  static _fromAdmitted(config:HostedModeConfig,redaction:Redaction):HostedClient {
    return new HostedClient(config,redaction,ADMITTED_CONFIG);
  }

  /** Close the local store, when the client opened it. */
  close(): void {
    this.store?.close();
    this.store = undefined;
  }

  /**
   * Send the envelope to the ECP server.
   *
   * The body is the envelope as the SDK built and signed it (the evaluate implementation guide 1.1: "The request
   * body is the envelope"), its signature under `envelope_signature` (the security architecture §1.3). Its version
   * is the envelope's own `signature_version`, inside the signed form; no header names it (row 171). The service
   * verifies it over the body as sent and records the body as sent.
   *
   * An outage is the decision, never an exception (decision_response.md Error Handling: "`CONTROL_PLANE_UNAVAILABLE`
   * - ECP is unreachable (circuit breaker, timeout)"): every attempt timed out, no connection, or a transient status
   * on the last attempt that the service did not answer: no decision, and not the service's error format
   * (docs-site/api/overview.mdx "Error format", row 145's ServerError). Each counts against the breaker, and any
   * answer from the service is a success, at the one site every send passes (`_ask`); once it is open, a call is not
   * sent and fails fast (Example 9). Before the envelope is sent, what the client holds is pushed; a push the service
   * does not answer is the outage, with no evaluate sent behind it. The outage is recorded in the local store, under
   * the client's fail_mode (Stop B). Mirrors http_client.py.
   *
   * @param envelope - The signed envelope; it carries no principal
   * @param principalToken - Sent in X-Hiitl-Principal-Token, verified by the server (T-130 §A7)
   * @returns Decision object from the server, or CONTROL_PLANE_UNAVAILABLE under the client's fail_mode (BLOCK /
   *   AUDIT_WRITE_FAILED when its record cannot be written)
   * @throws {ServerError} On a response that carries no decision (a decision body is the decision, on any status)
   */
  async evaluate(envelope: Envelope, principalToken?: string): Promise<Decision> {
    envelope=copySuppliedInput(envelope);
    try {assertSchemaNumbers(envelope,EnvelopeSchema);}catch(error){
      if(!(error instanceof NumericDomainError))throw error;
      throw new EnvelopeValidationError(error.message,[error.message]);
    }
    return this._evaluateAdmitted(envelope,principalToken);
  }

  /** @internal Owned input already admitted by this call; no admission scope spans I/O. */
  async _evaluateAdmitted(envelope:Envelope,principalToken?:string):Promise<Decision> {
    const { signature, ...rest } = envelope;
    const body: Record<string, unknown> = { ...rest, envelope_signature: signature };
    const headers: Record<string, string> = {};
    // A principal token rides in its header, never in the body
    if (principalToken) headers[PRINCIPAL_TOKEN_HEADER] = principalToken;

    const started = performance.now();
    const unanswered = await this._pushFirst();
    if (unanswered) return this._unavailable(envelope, started, unanswered);
    const [answer, unansweredSend] = await this._ask(body, headers);
    if (unansweredSend) return this._unavailable(envelope, started, unansweredSend);
    return this._parseResponse(answer.status, answer.data,answer.status!==200);
  }

  /**
   * One send, and whether the service answered it: `[answer]` when it did, `[undefined, outage]` when it did not:
   * every attempt timed out, no connection, or a transient status on the last attempt that the service did not answer
   * (row 199). The breaker counts it here, at the one site every send passes, the pushes' and the call's own: an
   * answer is a success, an outage a failure (R-0002; row 174). Mirrors http_client.py `_ask`.
   */
  private async _ask(
    body: Record<string, unknown>,
    extra: Record<string, string> = {},
    path?: string
  ): Promise<[Answer, undefined] | [undefined, Unanswered]> {
    let unanswered: Unanswered;
    try {
      const answer = await this._sendWithRetry(body, extra, path);
      if (!unansweredStatus(answer.status, answer.data)) {
        this.breaker.recordSuccess();
        return [answer, undefined];
      }
      unanswered = ['CONTROL_PLANE_UNREACHABLE', `HTTP ${answer.status}`];
    } catch (err) {
      if (!(err instanceof NetworkError)) throw err;
      unanswered = outageOf(err);
    }
    this.breaker.recordFailure();
    return [undefined, unanswered];
  }

  /**
   * CONTROL_PLANE_UNAVAILABLE under the client's fail_mode, its cause the reason and its message authored; the cause
   * is logged, and the decision is recorded in the local store (Stop B). The failure was counted where the send met it
   * (`_ask`); a call the open breaker held back was not sent, so has no cause.
   */
  private _unavailable(envelope: Envelope, started: number, [reason, cause]: Unanswered): Decision {
    const failMode = this.config.fail_mode;
    consoleLogger.warn(
      `hosted service at ${this.baseUrl}: ${reason} (${cause ?? 'not sent'}); ` +
        (failMode === 'FAIL_OPEN'
          ? 'fail-open, the action is allowed without being evaluated'
          : 'fail-closed, the action is not allowed')
    );
    const decision = outage(envelope.action_id, reason, failMode, this.breaker.state, {
      envelopeHash: envelopeHash(envelope as unknown as Record<string, unknown>),
      totalMs: performance.now() - started,
    });
    try {
      this._buffer().write(envelope, decision);
    } catch (e: any) {
      if (!(e instanceof AuditLogError)) throw e;
      // A record the store cannot write blocks, in either fail mode (Infrastructure spec 3)
      consoleLogger.error(
        `The outage decision's record could not be written to ${this.config.audit_db_path} (fail-closed): ${e.message}`
      );
      return auditWriteFailed(decision);
    }
    this.unpushed = true;
    return decision;
  }

  /**
   * The local store at audit_db_path, opened on first use, so construction never fails on it.
   *
   * @throws {AuditLogError} The store cannot be opened
   */
  private _buffer(): AuditLogger {
    this.store ??= new AuditLogger(this.config.audit_db_path, this.redaction);
    return this.store;
  }

  /**
   * Push what the client holds before its call is sent: the records to `POST /v1/sync/audit`, oldest first in batches,
   * then each held result to its result path, oldest first (decision_response.md "Where the error is answered";
   * sync_engine.md §7, "Audit Buffer Management"). Returns the outage when the breaker is open or the service did not
   * answer a push; everything is then left held and nothing further is sent. The push that met no answer counted it
   * against the breaker (`_ask`). Mirrors http_client.py `_push_first`.
   */
  private async _pushFirst(): Promise<Unanswered | undefined> {
    if (!this.breaker.allowRequest()) return ['CIRCUIT_BREAKER_OPEN'];
    if (!this.unpushed) return undefined;
    if (!fs.existsSync(this.config.audit_db_path)) {
      this.unpushed = false; // nothing was ever held
      return undefined;
    }
    let unanswered: Unanswered | undefined;
    try {
      const store = this._buffer();
      unanswered = (await this._pushRecords(store)) ?? (await this._pushResults(store));
    } catch (e: any) {
      if (!(e instanceof AuditLogError)) throw e;
      consoleLogger.warn(
        `What the client holds in ${this.config.audit_db_path} could not be read, so it was not pushed: ${e.message}`
      );
      return undefined;
    }
    if (!unanswered) this.unpushed = false;
    return unanswered;
  }

  /**
   * The held records, oldest first, as the sync engine uploads and settles them (sync_engine.md §2.1). An accepted
   * record is marked synced; one refused for its own content is marked refused, logged at error and not sent again;
   * any other refusal stays held, logged at warning, and the drain stops (row 224).
   */
  private async _pushRecords(store: AuditLogger): Promise<Unanswered | undefined> {
    // a batch is the sync engine's audit_batch_size default, read at the call (sync-engine.ts imports this module)
    const batch = SYNC_DEFAULTS.audit_batch_size;
    for (;;) {
      const records = store.getUnsynced(batch);
      if (records.length === 0) return undefined;
      this.sequence += 1;
      assertSchemaNumbers(this.sequence,z.number().int(),['sync_sequence']);
      const [answer, unanswered] = await this._ask(
        { records, sdk_version: SDK_VERSION, sync_sequence: this.sequence }, {}, '/v1/sync/audit');
      if (unanswered) return unanswered;
      const { status, data } = answer;
      if(status===200)admitResponse(data,status,AckNumbers); // current acknowledgement
      if (status !== 200) {
        const [code, message] = errorFromBody(status, data);
        consoleLogger.warn(
          `The hosted service refused the held audit records (HTTP ${status}, ${code}: ${message}); they ` +
            `stay held in ${this.config.audit_db_path}`
        );
        return undefined;
      }
      const errors: Array<Record<string, unknown>> = Array.isArray(data?.errors) ? data.errors : [];
      if (!settleUpload(store, records, errors, consoleLogger) || records.length < batch) return undefined;
    }
  }

  /**
   * Each held result, oldest first. One whose decision's record is still held waits for it, so a result finds its
   * decision (event_format.md "The Lifecycle"). The service's refusal is final: the result is removed and logged at
   * error, naming the action and the reason.
   */
  private async _pushResults(store: AuditLogger): Promise<Unanswered | undefined> {
    const waiting = store.unsyncedActionIds();
    for (const { action_id: actionId, execution_result: result } of store.heldResults()) {
      if (waiting.has(actionId)) continue;
      assertNumericDomain(result, ['execution_result']);
      const [answer, unanswered] = await this._ask(result, {}, resultPath(actionId));
      if (unanswered) return unanswered;
      const { status, data } = answer;
      if (status !== 200) {
        const [code, message] = errorFromBody(status, data);
        if (!Object.hasOwn(LIFECYCLE_MESSAGES, code)) {
          consoleLogger.warn(
            `The hosted service did not take the held result of ${actionId} (HTTP ${status}, ${code}: ` +
              `${message}); it stays held`
          );
          return undefined;
        }
        consoleLogger.error(
          `The held result of ${actionId} was refused by the hosted service: [${code}] ${message}; it is removed`
        );
      }
      store.releaseResult(actionId, result);
    }
    return undefined;
  }

  /**
   * Send an action's result to the service and return the record that carries it.
   *
   * The service refuses as the SDK's store does (event_format.md "The lifecycle"): its refusal is thrown as the
   * LifecycleError it names. The same result again returns the first record, so a retried send is safe
   * (Infrastructure spec 2: "idempotent state transitions"). During an outage the result is held in the local store
   * and pushed before the next call; the return is `{action_id, execution_result, held: true}`, and a warning is logged
   * (row 200). Mirrors http_client.py `record_result`.
   *
   * @throws {LifecycleError} The service did not record the result, with its reason
   * @throws {ServerError} The service answered an error that is not a lifecycle refusal
   * @throws {AuditLogError} The service could not take the result, and the store cannot hold it
   */
  async recordResult(actionId: string, result: ExecutionResult): Promise<Record<string, unknown>> {
    try {assertSchemaNumbers(result,ResultNumberSchema);} catch(error) {
      if(!(error instanceof NumericDomainError))throw error;
      throw new LifecycleError('RESULT_INVALID',error.message);
    }
    const body = result as unknown as Record<string, unknown>;
    let unanswered = await this._pushFirst();
    if (!unanswered) {
      const [answer, unansweredSend] = await this._ask(body, {}, resultPath(actionId));
      if (answer) {
        if (answer.status === 200) return answer.data as Record<string, unknown>;
        const [code, message] = errorFromBody(answer.status, answer.data);
        if (Object.hasOwn(LIFECYCLE_MESSAGES, code)) throw new LifecycleError(code, message);
        throw new ServerError(answer.status, code, message);
      }
      unanswered = unansweredSend;
    }
    this._buffer().holdResult(actionId, body);
    this.unpushed = true;
    consoleLogger.warn(
      `hosted service at ${this.baseUrl}: ${unanswered[0]} (${unanswered[1] ?? 'not sent'}); the result of ` +
        `${actionId} is held in ${this.config.audit_db_path} and pushed before the next call`
    );
    return { action_id: actionId, execution_result: result, held: true };
  }

  /**
   * Send request with exponential backoff retry on transient failures.
   */
  private async _sendWithRetry(
    body: Record<string, unknown>,
    extra: Record<string, string> = {},
    path = '/v1/evaluate'
  ): Promise<Answer> {
    const url = `${this.baseUrl}${path}`;
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (attempt > 0) {
        const delay = backoffDelay(attempt - 1);
        await sleep(delay);
      }

      try {
        const controller = new AbortController();
        // timeout is seconds, as in the Python SDK (row 173); the timer takes milliseconds
        const timeoutId = setTimeout(() => controller.abort(), this.timeout * 1000);

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${this.apiKey}`,
            ...extra,
          },
          body: JSON.stringify(body),
          signal: controller.signal,
          redirect: 'manual',     // a redirect is the service's answer, not a hop (sync_engine.md section 8)
        });

        clearTimeout(timeoutId);
        const data = await bodyOf(response); // a body is read once
        if (response.status !== 200) admitResponse(data,response.status,path==='/v1/sync/audit'?AckNumbers:DecisionSchema);


        // A non-retryable status, or the last attempt's: the server answered, so its answer is read
        // (a ServerError with its code and message, as http_client.py does; HTL-20, row 145)
        if (!RETRYABLE_STATUS_CODES.has(response.status) || attempt === this.maxRetries) {
          return { status: response.status, data };
        }

        // Retryable status — continue loop if retries remain
        lastError = new Error(`Server returned ${response.status}`);
      } catch (err: any) {
        if (err instanceof NumericDomainError || err instanceof ServerError) throw err;
        // AbortError = timeout, TypeError = network failure — both retryable
        if (err.name === 'AbortError') {
          lastError = new Error(`Request timed out after ${this.timeout}s`);
        } else {
          lastError = err;
        }
        // the timeout fired: named as the platform names a timed-out signal (row 174 reads it)
        if (err.name === 'AbortError' && lastError) lastError.name = 'TimeoutError';

        // Non-retryable fetch errors (not timeout, not network)
        if (err.name !== 'AbortError' && err.name !== 'TypeError') {
          throw new NetworkError(this.baseUrl, err);
        }
      }
    }

    // All retries exhausted
    throw new NetworkError(this.baseUrl, lastError ?? new Error('Request failed'));
  }

  /**
   * The decision the response carries, on any status, or ServerError when it carries none.
   *
   * An error is a decision and keeps its HTTP status, the decision as its body (decision_response.md "Error
   * Handling"; HTL-22 row 159): a 403 SIGNATURE_INVALID or a 500 POLICY_ERROR is read as the decision it is. A
   * response with no decision body — a 401, a 422's field list — is ServerError. Mirrors http_client.py.
   */
  private async _parseResponse(status: number, data: any, admitted=false): Promise<Decision> {
    if(!admitted)admitResponse(data,status);
    if (isDecision(data)) {

      // Bridge server timing format to SDK Timing format
      const rawTiming = data.timing ?? {};
      const totalMs = rawTiming.total_ms ?? 0;

      // Every member the schema declares reaches the caller; an absent or null one is left out (row 204)
      const members = Object.fromEntries(
        DECISION_MEMBERS.filter((m) => data[m] !== undefined && data[m] !== null).map((m) => [m, data[m]])
      );
      return {
        ...members,
        action_id: data.action_id ?? '',
        decision: data.decision,
        allowed: data.allowed,
        reason_codes: data.reason_codes ?? [],
        policy_version: data.policy_version ?? '',
        timing: {
          ingest_ms: rawTiming.ingest_ms ?? 0,
          evaluation_ms: rawTiming.evaluation_ms ?? totalMs,
          total_ms: totalMs,
        },
        // staged_observations is .default([]) in the zod schema — required
        // on the inferred type. Server may also send the array under the
        // same key; pick it up if present, otherwise default to [].
        staged_observations: Array.isArray(data.staged_observations)
          ? data.staged_observations
          : [],
        // Matching windowed RATE_LIMIT rules (R-0852); counted server-side.
        rate_limit_rules: Array.isArray(data.rate_limit_rules) ? data.rate_limit_rules : [],
      } as Decision;
    }

    throw new ServerError(status, ...errorFromBody(status, data));
  }
}

/** The response's JSON body, or undefined when it has none. */
async function bodyOf(response: Response): Promise<any> {
  try {
    return await response.json();
  } catch {
    return undefined; // Could not parse the body: the defaults below
  }
}

/** An action's result path (event_format.md "The lifecycle"). */
function resultPath(actionId: string): string {
  return `/v1/actions/${encodeURIComponent(actionId)}/result`;
}

/** The outage a send that met no answer is: every attempt timed out, or no connection (Error Handling). */
function outageOf(err: NetworkError): Unanswered {
  const timedOut = err.cause_error.name === 'TimeoutError';
  return [timedOut ? 'CONTROL_PLANE_TIMEOUT' : 'CONTROL_PLANE_UNREACHABLE', err.cause_error.message];
}

/**
 * A transient status on the last attempt, answered by something other than the service (a gateway): an outage (row
 * 199, as built).
 */
function unansweredStatus(status: number, data: any): boolean {
  return RETRYABLE_STATUS_CODES.has(status) && !isServiceError(data);
}

/**
 * Whether the body is the service's error format: "a JSON body with a `detail` field" (docs-site/api/overview.mdx
 * "Error format"), or a decision, which an error is once there is an envelope (decision_response.md "Error Handling";
 * row 159). The Python SDK reads the same.
 */
function isServiceError(data: any): boolean {
  return (data !== null && typeof data === 'object' && !Array.isArray(data) && 'detail' in data) || isDecision(data);
}

/** Whether a body is a decision: a string `decision` and a boolean `allowed` (decision_response.md). */
function isDecision(data: any): boolean {
  return data !== null && typeof data === 'object' && typeof data.decision === 'string' && typeof data.allowed === 'boolean';
}

function errorFromBody(status: number, data: any): [string, string] {
  let errorCode = 'UNKNOWN_ERROR';
  let errorMessage = `Server returned HTTP ${status}`;

  if (data !== undefined) {
    // The documented error shapes (docs-site/api/overview.mdx "Error format";
    // HTL-20, row 145): an object under `detail` with a string `error` and
    // `message`, a 422's list of field problems, or a message string. The
    // Python SDK reads the same three.
    const detail = data !== null && typeof data === 'object' && !Array.isArray(data) && 'detail' in data
      ? data.detail
      : data;
    if (Array.isArray(detail)) {
      errorCode = 'VALIDATION_ERROR';
      errorMessage = detail.map(validationProblem).join('; ') || errorMessage;
    } else if (detail !== null && typeof detail === 'object') {
      if (typeof detail.error === 'string') errorCode = detail.error;
      if (typeof detail.message === 'string') errorMessage = detail.message;
    } else if (typeof detail === 'string') {
      errorMessage = detail;
    }
  }
  return [errorCode, errorMessage];
}

/**
 * Compute exponential backoff delay: min(0.5 * 2^attempt, 4) seconds.
 * Returns delay in milliseconds.
 */
export function backoffDelay(attempt: number): number {
  return Math.min(500 * Math.pow(2, attempt), 4000);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** One entry of a 422's list as `field.path: message`. */
export function validationProblem(problem: unknown): string {
  if (problem === null || typeof problem !== 'object' || Array.isArray(problem)) return String(problem);
  const p = problem as { loc?: unknown[]; msg?: unknown };
  const loc = Array.isArray(p.loc) ? p.loc.map(String).join('.') : '';
  const msg = String(p.msg ?? '');
  return loc ? `${loc}: ${msg}` : msg;
}
