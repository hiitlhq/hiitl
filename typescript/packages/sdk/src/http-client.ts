/**
 * HTTP client for hosted mode communication with the ECP server.
 *
 * Uses native fetch (Node 18+) with retry logic and HMAC-SHA256 signing.
 */

import crypto from 'node:crypto';
import type { Decision } from '@hiitl/core';
import type { HostedModeConfig } from './config.js';
import { ServerError, NetworkError } from './exceptions.js';

/** Status codes that trigger a retry. */
const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);

/**
 * Hosted mode HTTP client for communicating with the ECP server.
 */
export class HostedClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly signatureKey?: string;
  private readonly agentId: string;
  private readonly orgId: string;
  private readonly environment: string;

  constructor(config: HostedModeConfig) {
    this.baseUrl = config.server_url;
    this.apiKey = config.api_key;
    this.timeout = config.timeout;
    this.maxRetries = config.max_retries;
    this.signatureKey = config.signature_key;
    this.agentId = config.agent_id;
    this.orgId = config.org_id;
    this.environment = config.environment;
  }

  /**
   * Send an evaluate request to the ECP server.
   *
   * @param options - Evaluation parameters
   * @returns Decision object from the server
   * @throws {ServerError} On non-2xx responses
   * @throws {NetworkError} On connection failures
   */
  async evaluate(options: {
    action: string;
    operation: string;
    target: Record<string, unknown>;
    parameters: Record<string, unknown>;
    agent_id?: string;
    user_id?: string;
    session_id?: string;
    confidence?: number;
    reason?: string;
    sensitivity?: string[];
    cost_estimate?: { tokens?: number; usd_cents?: number };
    idempotency_key?: string;
  }): Promise<Decision> {
    // Build request body
    const body: Record<string, unknown> = {
      action: options.action,
      operation: options.operation,
      target: options.target,
      parameters: options.parameters,
      agent_id: options.agent_id ?? this.agentId,
    };

    // Add optional fields only if provided
    if (options.user_id !== undefined) body.user_id = options.user_id;
    if (options.session_id !== undefined) body.session_id = options.session_id;
    if (options.confidence !== undefined) body.confidence = options.confidence;
    if (options.reason !== undefined) body.reason = options.reason;
    if (options.sensitivity !== undefined) body.sensitivity = options.sensitivity;
    if (options.cost_estimate !== undefined) body.cost_estimate = options.cost_estimate;
    if (options.idempotency_key !== undefined) body.idempotency_key = options.idempotency_key;

    // Compute signature if key is configured
    if (this.signatureKey) {
      body.signature = this._computeSignature(body);
    }

    // Send with retry
    const response = await this._sendWithRetry(body);
    return this._parseResponse(response);
  }

  /**
   * Compute HMAC-SHA256 signature of the request body.
   */
  private _computeSignature(body: Record<string, unknown>): string {
    const canonical = JSON.stringify(body, Object.keys(body).sort());
    return crypto
      .createHmac('sha256', this.signatureKey!)
      .update(canonical)
      .digest('hex');
  }

  /**
   * Send request with exponential backoff retry on transient failures.
   */
  private async _sendWithRetry(body: Record<string, unknown>): Promise<Response> {
    const url = `${this.baseUrl}/v1/evaluate`;
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (attempt > 0) {
        const delay = backoffDelay(attempt - 1);
        await sleep(delay);
      }

      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${this.apiKey}`,
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        // Don't retry on non-retryable status codes
        if (!RETRYABLE_STATUS_CODES.has(response.status)) {
          return response;
        }

        // Retryable status — continue loop if retries remain
        lastError = new Error(`Server returned ${response.status}`);
      } catch (err: any) {
        // AbortError = timeout, TypeError = network failure — both retryable
        if (err.name === 'AbortError') {
          lastError = new Error(`Request timed out after ${this.timeout}ms`);
        } else {
          lastError = err;
        }

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
   * Parse server response into a Decision object.
   */
  private async _parseResponse(response: Response): Promise<Decision> {
    if (response.status === 200) {
      const data = (await response.json()) as Record<string, any>;

      // Bridge server timing format to SDK Timing format
      const rawTiming = data.timing ?? {};
      const totalMs = rawTiming.total_ms ?? 0;

      const decision: Decision = {
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
      };

      // Add optional fields if present
      if (data.envelope_hash !== undefined && data.envelope_hash !== null) {
        (decision as any).envelope_hash = data.envelope_hash;
      }
      if (data.resume_token) decision.resume_token = data.resume_token;
      if (data.route_ref) decision.route_ref = data.route_ref;
      if (data.escalation_context) decision.escalation_context = data.escalation_context;
      if (data.matched_rules) decision.matched_rules = data.matched_rules;
      if (data.rate_limit) decision.rate_limit = data.rate_limit;
      if (data.approval_metadata) decision.approval_metadata = data.approval_metadata;
      if (data.sandbox_metadata) decision.sandbox_metadata = data.sandbox_metadata;
      if (data.error) decision.error = data.error;
      if (data.remediation) decision.remediation = data.remediation;
      if (data.would_be) decision.would_be = data.would_be;
      if (data.would_be_reason_codes) decision.would_be_reason_codes = data.would_be_reason_codes;

      return decision;
    }

    // Error responses
    let errorCode = 'UNKNOWN_ERROR';
    let errorMessage = `Server returned status ${response.status}`;

    try {
      const data = (await response.json()) as Record<string, any>;
      if (typeof data.detail === 'string') {
        errorCode = data.detail;
        errorMessage = data.detail;
      } else if (data.detail?.code) {
        errorCode = data.detail.code;
        errorMessage = data.detail.message ?? data.detail.code;
      } else if (data.error) {
        errorCode = data.error;
        errorMessage = data.message ?? data.error;
      }
    } catch {
      // Could not parse response body — use defaults
    }

    throw new ServerError(response.status, errorCode, errorMessage);
  }
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
