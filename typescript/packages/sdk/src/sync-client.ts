import { assertNumericDomain, assertSchemaNumbers, NumericDomainError } from '@hiitl/core';
/**
 * HTTP client for sync engine communication with /v1/sync/* endpoints
 * (Block 5c — direct port of `python/hiitl/sdk/sync_client.py`).
 *
 * Endpoints:
 *   POST /v1/sync/audit      — batch audit upload
 *   POST /v1/sync/telemetry  — telemetry record upload
 *   GET  /v1/sync/policies   — policy download (conditional via ETag)
 *   GET  /v1/sync/routes     — route download (conditional via ETag)
 *   GET  /v1/sync/kill-switches — kill switch polling
 *
 * Port choices vs the Python version:
 *  - HTTP: Node's built-in `fetch` (stable on Node ≥18) instead of httpx.
 *    Avoids adding axios/got as a dependency.
 *  - Timeouts: `fetch` has no per-request timeout; we use `AbortController`
 *    with a `setTimeout` to abort. The abort surfaces as a TypeError on
 *    fetch which we translate back into a SyncError("transport").
 *  - Retry/backoff: identical algorithm to Python — exponential with
 *    jitter, capped at 60s. `_backoffWithJitter(attempt)` returns the
 *    same value distribution as Python's helper for a given attempt.
 *  - Gzip: `zlib.promises.gzip` instead of `gzip.compress`. Same bytes.
 *  - SDK version + headers: identical strings ("python" → "typescript").
 */

import { z } from 'zod';
import {admitSync,syncChannel,admitConfiguration} from './admission.js';
import {TelemetryUploadNumberSchema} from './sync-numbers.js';
import { createRequire } from 'node:module';
import { gzip as gzipCallback } from 'node:zlib';
import { promisify } from 'node:util';

import { httpsRefusal } from '@hiitl/core';
import { ConfigurationError, SyncError } from './exceptions.js';
import { validationProblem } from './http-client.js';
import type { Logger } from './logger.js';
import { consoleLogger } from './logger.js';

const gzip = promisify(gzipCallback);

/** Retryable HTTP status codes — matches Python set exactly. */
const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);

/** SDK version reported in headers: the package's own version, read from its package.json (one copy, at the
 *  package root in the source tree and in the published tarball alike). */
export const { version: SDK_VERSION } = createRequire(import.meta.url)('../package.json') as { version: string };

/** Compress request bodies larger than this threshold (matches Python: 1 KB). */
const GZIP_THRESHOLD_BYTES = 1024;

// ─── Result types (mirror dataclasses in sync_client.py) ──────────────────

export interface AuditUploadResult {
  accepted: number;
  duplicates: number;
  errors: Array<Record<string, unknown>>;
}

export interface PolicyDownloadResult {
  policies: Array<Record<string, unknown>>;
  version: string;
  etag: string;
  /**
   * The org's redaction policy, `{manual_redact_fields: [...]}` (event_format.md §Redaction, row 163(a)); undefined
   * when the response carries none.
   */
  redaction_policy?: Record<string, unknown>;
}

export interface RouteDownloadResult {
  routes: Array<Record<string, unknown>>;
  etag: string;
}

export interface KillSwitchResult {
  kill_switches: Array<Record<string, unknown>>;
  /**
   * The active version as far as its live switches go: the policy set's own fields and its live kill-switch rules
   * (sync_engine.md 2.4; HTL-29 row 240). null when the org has no active version or the response carries none.
   */
  policy_set: Record<string, unknown> | null;
  server_time: string;
}

export interface TelemetryUploadResult {
  accepted: number;
}

// ─── Client ───────────────────────────────────────────────────────────────

const SyncClientNumbers=z.object({timeout:z.number().optional(),max_retries:z.number().optional()});
export interface SyncClientOptions extends z.infer<typeof SyncClientNumbers> {
  server_url: string;
  api_key: string;
  org_id: string;
  environment: string;
  /** Per-request timeout in seconds. Default 10. */
  /** Max retry attempts on retryable status codes / timeouts. Default 3. */
  /** Optional logger override. */
  logger?: Logger;
  /** Optional fetch implementation override (for testing). */
  fetchImpl?: typeof fetch;
}

/**
 * Internal helper: shape returned by `_sendWithRetry`. We don't expose
 * the raw Response so callers can't accidentally consume the body twice.
 */
interface ParsedResponse {
  status: number;
  text: string;
}

export class SyncClient {
  private readonly serverUrl: string;
  private readonly orgId: string;
  private readonly environment: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly defaultHeaders: Record<string, string>;
  private readonly fetchImpl: typeof fetch;
  private readonly log: Logger;
  /** Allows tests to inject deterministic delays for retry timing. */
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(opts: SyncClientOptions) {
    admitConfiguration(opts,SyncClientNumbers);
    const refusal = httpsRefusal(opts.server_url, 'server_url');   // the API key goes there (sync_engine.md §8)
    if (refusal) throw new ConfigurationError(refusal);
    this.serverUrl = opts.server_url.replace(/\/$/, '');
    this.orgId = opts.org_id;
    this.environment = opts.environment;
    this.timeoutMs = (opts.timeout ?? 10) * 1000;
    this.maxRetries = opts.max_retries ?? 3;
    this.log = opts.logger ?? consoleLogger;
    this.fetchImpl = opts.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.sleep = (ms: number) =>
      new Promise<void>((resolve) => setTimeout(resolve, ms));

    this.defaultHeaders = {
      Authorization: `Bearer ${opts.api_key}`,
      'Content-Type': 'application/json',
      'Accept-Encoding': 'gzip',
      'X-HIITL-Org-Id': opts.org_id,
      'X-HIITL-Environment': opts.environment,
      'X-HIITL-SDK-Version': SDK_VERSION,
      // Python sends "python"; TS sends "typescript". The hosted sync
      // endpoint treats both as valid clients and uses
      // the value only for telemetry tagging.
      'X-HIITL-SDK-Language': 'typescript',
    };
  }

  // ─── audit upload ───────────────────────────────────────────────────────

  async uploadAudit(
    records: Array<Record<string, unknown>>,
    syncSequence: number
  ): Promise<AuditUploadResult> {
    // Stored content is not admitted again; the new frame still is.
    admitSync('audit',syncSequence,['sync_sequence'],z.number().int());
    const payload = {
      records,
      sdk_version: SDK_VERSION,
      sync_sequence: syncSequence,
    };
    const { body, headers } = await this._encodeJsonBody(payload);

    const response = await this._sendWithRetry('POST', '/v1/sync/audit', body, headers);

    if (response.status === 200) {
      const data = this._parseJsonOrEmpty(response,'audit');
      return {
        accepted: Number(data.accepted ?? 0),
        duplicates: Number(data.duplicates ?? 0),
        errors: Array.isArray(data.errors) ? (data.errors as Array<Record<string, unknown>>) : [],
      };
    }

    throw new SyncError(
      'audit',
      `Audit upload failed with status ${response.status}: ${extractError(response)}`
    );
  }

  // ─── policy download ────────────────────────────────────────────────────

  async downloadPolicies(etag?: string | null): Promise<PolicyDownloadResult | null> {
    const headers: Record<string, string> = {};
    if (etag) headers['If-None-Match'] = `"${etag}"`;

    const response = await this._sendWithRetry('GET', '/v1/sync/policies', undefined, headers);

    if (response.status === 304) return null; // Not Modified
    if (response.status === 200) {
      const data = this._parseJsonOrEmpty(response,'policy');
      return {
        policies: Array.isArray(data.policies) ? (data.policies as Array<Record<string, unknown>>) : [],
        version: typeof data.version === 'string' ? data.version : '',
        etag: typeof data.etag === 'string' ? data.etag : '',
        redaction_policy:
          data.redaction_policy !== null && typeof data.redaction_policy === 'object' && !Array.isArray(data.redaction_policy)
            ? (data.redaction_policy as Record<string, unknown>)
            : undefined,
      };
    }

    throw new SyncError(
      'policy',
      `Policy download failed with status ${response.status}: ${extractError(response)}`
    );
  }

  // ─── route download ─────────────────────────────────────────────────────

  async downloadRoutes(etag?: string | null): Promise<RouteDownloadResult | null> {
    const headers: Record<string, string> = {};
    if (etag) headers['If-None-Match'] = `"${etag}"`;

    const response = await this._sendWithRetry('GET', '/v1/sync/routes', undefined, headers);

    if (response.status === 304) return null;
    if (response.status === 200) {
      const data = this._parseJsonOrEmpty(response,'routes');
      return {
        routes: Array.isArray(data.routes) ? (data.routes as Array<Record<string, unknown>>) : [],
        etag: typeof data.etag === 'string' ? data.etag : '',
      };
    }

    throw new SyncError(
      'routes',
      `Route download failed with status ${response.status}: ${extractError(response)}`
    );
  }

  // ─── kill switches poll ─────────────────────────────────────────────────

  async pollKillSwitches(): Promise<KillSwitchResult> {
    const response = await this._sendWithRetry('GET', '/v1/sync/kill-switches');

    if (response.status === 200) {
      const data = this._parseJsonOrEmpty(response,'kill_switches');
      return {
        kill_switches: Array.isArray(data.kill_switches)
          ? (data.kill_switches as Array<Record<string, unknown>>)
          : [],
        policy_set:
          data.policy_set && typeof data.policy_set === 'object' && !Array.isArray(data.policy_set)
            ? (data.policy_set as Record<string, unknown>)
            : null,
        server_time: typeof data.server_time === 'string' ? data.server_time : '',
      };
    }

    throw new SyncError(
      'kill_switches',
      `Kill switch poll failed with status ${response.status}: ${extractError(response)}`
    );
  }

  // ─── telemetry upload ───────────────────────────────────────────────────

  async uploadTelemetry(
    records: Array<Record<string, unknown>>
  ): Promise<TelemetryUploadResult> {
    const payload = { records, sdk_version: SDK_VERSION };
    admitSync('telemetry',payload,[],TelemetryUploadNumberSchema);
    const { body, headers } = await this._encodeJsonBody(payload);

    const response = await this._sendWithRetry('POST', '/v1/sync/telemetry', body, headers);

    if (response.status === 200) {
      const data = this._parseJsonOrEmpty(response,'telemetry');
      return { accepted: Number(data.accepted ?? records.length) };
    }

    throw new SyncError(
      'telemetry',
      `Telemetry upload failed with status ${response.status}: ${extractError(response)}`
    );
  }

  // ─── core HTTP plumbing ─────────────────────────────────────────────────

  /**
   * Send with exponential backoff + jitter on transient failures.
   * Backoff: 1s → 2s → 4s → 8s (capped at 60s, matching Python).
   * Retryable: 429, 502, 503, 504, and timeouts.
   * Non-retryable: any other status, or generic transport errors
   * (DNS, connection refused, etc) — these surface immediately.
   */
  private async _sendWithRetry(
    method: string,
    path: string,
    body?: Uint8Array | Buffer,
    extraHeaders?: Record<string, string>
  ): Promise<ParsedResponse> {
    const url = `${this.serverUrl}${path}`;
    const headers = { ...this.defaultHeaders, ...(extraHeaders ?? {}) };

    let lastError: unknown;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const fetchInit: RequestInit = {
          method,
          headers,
          signal: controller.signal,
          redirect: 'manual',     // a redirect is the service's answer, not a hop (sync_engine.md section 8)
        };
        if (body !== undefined) {
          // fetch's BodyInit accepts Uint8Array; Buffer is a Uint8Array subclass.
          fetchInit.body = body;
        }

        const response = await this.fetchImpl(url, fetchInit);
        const text = await response.text();
        const parsed: ParsedResponse = { status: response.status, text };
        if (response.status !== 200) this._parseJsonOrEmpty(parsed,syncChannel(path));

        // Success or non-retryable
        if (!RETRYABLE_STATUS_CODES.has(response.status)) {
          return parsed;
        }

        // Retryable — wait and retry
        if (attempt < this.maxRetries) {
          const delaySec = backoffWithJitter(attempt);
          this.log.warn(
            `Sync request ${method} ${path} returned ${response.status}, ` +
              `retrying in ${delaySec.toFixed(1)}s ` +
              `(attempt ${attempt + 1}/${this.maxRetries})`
          );
          await this.sleep(delaySec * 1000);
          continue;
        }

        // Out of retries — return the last response as-is so the caller's
        // status check can produce a SyncError with the actual code.
        return parsed;
      } catch (err) {
        if (err instanceof NumericDomainError || err instanceof SyncError) throw err;
        lastError = err;
        const isAbort = err instanceof Error && err.name === 'AbortError';
        const isFetchTypeErr = err instanceof TypeError; // fetch network-level errors

        if (isAbort || isFetchTypeErr) {
          if (attempt < this.maxRetries) {
            const delaySec = backoffWithJitter(attempt);
            this.log.warn(
              `Sync request ${method} ${path} ${isAbort ? 'timed out' : 'failed'}, ` +
                `retrying in ${delaySec.toFixed(1)}s ` +
                `(attempt ${attempt + 1}/${this.maxRetries})`
            );
            await this.sleep(delaySec * 1000);
            continue;
          }
          // Out of retries — surface as a transport SyncError.
          throw new SyncError(
            'transport',
            `Sync request ${method} ${path} failed after ${this.maxRetries + 1} attempts: ${
              err instanceof Error ? err.message : String(err)
            }`,
            err instanceof Error ? err : undefined
          );
        }

        // Non-retryable transport error (e.g. invalid URL) — raise immediately.
        throw new SyncError(
          'transport',
          `HTTP error during sync ${method} ${path}: ${
            err instanceof Error ? err.message : String(err)
          }`,
          err instanceof Error ? err : undefined
        );
      } finally {
        clearTimeout(timeoutId);
      }
    }

    // Unreachable — the loop either returns or throws. TypeScript can't
    // see that, so we add a defensive throw using `lastError` for clarity.
    throw new SyncError(
      'transport',
      `Sync request ${method} ${path} failed: ${
        lastError instanceof Error ? lastError.message : String(lastError ?? 'unknown')
      }`
    );
  }

  /**
   * Encode a JSON payload as bytes, gzipping when over the threshold.
   * Returns the body and any headers we need to add (Content-Encoding).
   */
  private async _encodeJsonBody(
    payload: unknown
  ): Promise<{ body: Uint8Array | Buffer; headers: Record<string, string> }> {
    const json = JSON.stringify(payload);
    const raw = Buffer.from(json, 'utf-8');
    if (raw.length > GZIP_THRESHOLD_BYTES) {
      const compressed = await gzip(raw);
      return {
        body: compressed,
        headers: {
          'Content-Encoding': 'gzip',
          'Content-Type': 'application/json',
        },
      };
    }
    return { body: raw, headers: {} };
  }

  /** Parse JSON body, returning `{}` on parse failure (matches Python's `.get(...)` calls). */
  private _parseJsonOrEmpty(resp: ParsedResponse,channel:string): Record<string, unknown> {
    let parsed: unknown;
    try { parsed = JSON.parse(resp.text); } catch { return {}; }
    admitSync(channel,parsed);
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};

  }
}

// ─── free helpers ─────────────────────────────────────────────────────────

/**
 * Exponential backoff with jitter — matches Python sync_client._backoff_with_jitter.
 * Base delay: 1s, 2s, 4s, 8s, capped at 60s. Jitter: delay × (0.5 + random × 1.0).
 *
 * Exported for unit tests that want to assert the distribution shape.
 */
export function backoffWithJitter(attempt: number): number {
  const base = Math.min(1.0 * 2 ** attempt, 60.0);
  return base * (0.5 + Math.random());
}

/**
 * The message of the documented error shapes (docs-site/api/overview.mdx
 * "Error format"), read as the hosted client reads them; the Python sync
 * client gives the same text.
 */
function extractError(response: ParsedResponse): string {
  try {
    const data = JSON.parse(response.text);
    const detail = data !== null && typeof data === 'object' && !Array.isArray(data) && 'detail' in data
      ? data.detail
      : data;
    if (detail !== null && typeof detail === 'object' && !Array.isArray(detail) && typeof detail.message === 'string') {
      return detail.message;
    }
    if (Array.isArray(detail)) return detail.map(validationProblem).join('; ');
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  } catch {
    return response.text.length > 0 ? response.text.slice(0, 200) : 'No response body';
  }
}
