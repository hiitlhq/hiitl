/**
 * Tests for hosted mode: HostedModeConfig, HostedClient, and HIITL hosted mode.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createHostedConfig, HostedModeConfigSchema } from '../../src/config.js';
import { HostedClient, backoffDelay } from '../../src/http-client.js';
import { HIITL } from '../../src/client.js';
import {
  ConfigurationError,
  ServerError,
  NetworkError,
} from '../../src/exceptions.js';
import type { HostedModeConfig } from '../../src/config.js';

// --- Test helpers ---

const VALID_ORG_ID = 'org_mycompany123456789';

function validHostedConfig(): HostedModeConfig {
  return createHostedConfig({
    environment: 'dev',
    agent_id: 'test-agent',
    org_id: VALID_ORG_ID,
    api_key: 'test-api-key-12345',
    server_url: 'https://api.hiitl.com',
  });
}

function mockFetchResponse(body: Record<string, unknown>, status = 200): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
    headers: new Headers(),
    statusText: status === 200 ? 'OK' : 'Error',
  } as Response;
}

function allowResponse(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    decision: 'ALLOW',
    allowed: true,
    reason_codes: ['default_allow'],
    policy_version: '1.0.0',
    timing: { total_ms: 2.5 },
    ...overrides,
  };
}

// --- HostedModeConfig ---

describe('HostedModeConfig', () => {
  it('should create valid config with all required fields', () => {
    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    expect(config.environment).toBe('dev');
    expect(config.agent_id).toBe('test-agent');
    expect(config.org_id).toBe(VALID_ORG_ID);
    expect(config.api_key).toBe('test-api-key-12345');
    expect(config.server_url).toBe('https://api.hiitl.com');
    expect(config.timeout).toBe(5000);
    expect(config.max_retries).toBe(3);
  });

  it('should strip trailing slashes from server_url', () => {
    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com///',
    });

    expect(config.server_url).toBe('https://api.hiitl.com');
  });

  it('should reject invalid server_url', () => {
    expect(() =>
      createHostedConfig({
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: VALID_ORG_ID,
        api_key: 'test-api-key-12345',
        server_url: 'not-a-url',
      })
    ).toThrow();
  });

  it('should reject short api_key', () => {
    expect(() =>
      createHostedConfig({
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: VALID_ORG_ID,
        api_key: 'short',
        server_url: 'https://api.hiitl.com',
      })
    ).toThrow(/api_key/);
  });

  it('should reject invalid org_id', () => {
    expect(() =>
      createHostedConfig({
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: 'bad_org',
        api_key: 'test-api-key-12345',
        server_url: 'https://api.hiitl.com',
      })
    ).toThrow(/org_id/);
  });

  it('should allow custom timeout and max_retries', () => {
    const config = createHostedConfig({
      environment: 'prod',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      timeout: 10000,
      max_retries: 5,
    });

    expect(config.timeout).toBe(10000);
    expect(config.max_retries).toBe(5);
  });

  it('should accept all valid environments', () => {
    for (const env of ['dev', 'stage', 'prod'] as const) {
      const config = createHostedConfig({
        environment: env,
        agent_id: 'test-agent',
        org_id: VALID_ORG_ID,
        api_key: 'test-api-key-12345',
        server_url: 'https://api.hiitl.com',
      });
      expect(config.environment).toBe(env);
    }
  });
});

// --- HIITL Hosted Init ---

describe('HIITL Hosted Init', () => {
  it('should auto-detect hosted mode from api_key + server_url', () => {
    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    expect(hiitl.mode).toBe('hosted');
    expect(hiitl.hostedConfig).toBeDefined();
    expect(hiitl.config).toBeUndefined();
  });

  it('should allow zero-config local mode without policy_path', () => {
    const hiitl = new HIITL({
      audit_db_path: ':memory:',
    });

    expect(hiitl.mode).toBe('local');
    expect(hiitl.evalMode).toBe('OBSERVE_ALL');
    hiitl.close();
  });

  it('should throw ConfigurationError for RESPECT_POLICY without policy_path', () => {
    expect(
      () =>
        new HIITL({
          environment: 'dev',
          agent_id: 'test-agent',
          org_id: VALID_ORG_ID,
          mode: 'RESPECT_POLICY',
        })
    ).toThrow(ConfigurationError);
  });

  it('should auto-detect hybrid mode from api_key without server_url', () => {
    // api_key without server_url → hybrid, but no policy_path → error
    expect(
      () =>
        new HIITL({
          environment: 'dev',
          agent_id: 'test-agent',
          org_id: VALID_ORG_ID,
          api_key: 'test-api-key-12345',
        })
    ).toThrow(ConfigurationError);
  });
});

// --- HostedClient.evaluate ---

describe('HostedClient.evaluate', () => {
  let client: HostedClient;
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    client = new HostedClient(validHostedConfig());
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should return ALLOW decision from server', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    const decision = await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: { account: 'acct_123' },
      parameters: { amount: 100 },
    });

    expect(decision.decision).toBe('ALLOW');
    expect(decision.allowed).toBe(true);
    expect(decision.reason_codes).toEqual(['default_allow']);
    expect(decision.policy_version).toBe('1.0.0');
  });

  it('should return BLOCK decision from server', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({
        decision: 'BLOCK',
        allowed: false,
        reason_codes: ['high_amount'],
        policy_version: '1.0.0',
        timing: { total_ms: 3.0 },
      })
    );

    const decision = await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: {},
      parameters: { amount: 10000 },
    });

    expect(decision.decision).toBe('BLOCK');
    expect(decision.allowed).toBe(false);
    expect(decision.reason_codes).toContain('high_amount');
  });

  it('should return escalation fields for REQUIRE_APPROVAL', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({
        decision: 'REQUIRE_APPROVAL',
        allowed: false,
        reason_codes: ['needs_approval'],
        policy_version: '1.0.0',
        timing: { total_ms: 2.0 },
        resume_token: 'resume_abc123',
        route_ref: 'payment_approval',
        escalation_context: {
          surface_fields: ['amount', 'account'],
          available_responses: ['approve', 'deny'],
        },
      })
    );

    const decision = await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: {},
      parameters: { amount: 5000 },
    });

    expect(decision.decision).toBe('REQUIRE_APPROVAL');
    expect(decision.resume_token).toBe('resume_abc123');
    expect(decision.route_ref).toBe('payment_approval');
    expect(decision.escalation_context).toBeDefined();
    expect(decision.escalation_context!.surface_fields).toEqual(['amount', 'account']);
  });

  it('should send Bearer auth header', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    await client.evaluate({
      action: 'test',
      operation: 'read',
      target: {},
      parameters: {},
    });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [, requestInit] = fetchSpy.mock.calls[0];
    expect(requestInit.headers.Authorization).toBe('Bearer test-api-key-12345');
  });

  it('should send correct request body structure', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: { account: 'acct_123' },
      parameters: { amount: 100 },
    });

    const [url, requestInit] = fetchSpy.mock.calls[0];
    expect(url).toBe('https://api.hiitl.com/v1/evaluate');
    const body = JSON.parse(requestInit.body);
    expect(body.action).toBe('payment');
    expect(body.operation).toBe('execute');
    expect(body.target).toEqual({ account: 'acct_123' });
    expect(body.parameters).toEqual({ amount: 100 });
    expect(body.agent_id).toBe('test-agent');
  });

  it('should omit undefined optional fields from body', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    await client.evaluate({
      action: 'test',
      operation: 'read',
      target: {},
      parameters: {},
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.user_id).toBeUndefined();
    expect(body.session_id).toBeUndefined();
    expect(body.confidence).toBeUndefined();
    expect(body.sensitivity).toBeUndefined();
  });

  it('should include optional fields when provided', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    await client.evaluate({
      action: 'test',
      operation: 'read',
      target: {},
      parameters: {},
      user_id: 'user_123',
      session_id: 'sess_abc',
      confidence: 0.95,
      sensitivity: ['money'],
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.user_id).toBe('user_123');
    expect(body.session_id).toBe('sess_abc');
    expect(body.confidence).toBe(0.95);
    expect(body.sensitivity).toEqual(['money']);
  });

  it('should bridge server timing format to SDK Timing', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse(allowResponse({ timing: { total_ms: 5.0 } }))
    );

    const decision = await client.evaluate({
      action: 'test',
      operation: 'read',
      target: {},
      parameters: {},
    });

    expect(decision.timing.total_ms).toBe(5.0);
    expect(decision.timing.evaluation_ms).toBe(5.0); // Defaults to total_ms
    expect(decision.timing.ingest_ms).toBe(0);
  });
});

// --- HostedClient Error Handling ---

describe('HostedClient Errors', () => {
  let client: HostedClient;
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    client = new HostedClient(validHostedConfig());
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should throw ServerError on 401', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: 'Invalid API key' }, 401)
    );

    await expect(
      client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} })
    ).rejects.toThrow(ServerError);

    try {
      await client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} });
    } catch (e: any) {
      expect(e.status_code).toBe(401);
    }
  });

  it('should throw ServerError on 403', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: { code: 'INSUFFICIENT_SCOPE', message: 'Need evaluate scope' } }, 403)
    );

    try {
      await client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} });
    } catch (e: any) {
      expect(e).toBeInstanceOf(ServerError);
      expect(e.status_code).toBe(403);
      expect(e.error_code).toBe('INSUFFICIENT_SCOPE');
    }
  });

  it('should throw ServerError on 404', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: { code: 'POLICY_NOT_FOUND', message: 'No active policy' } }, 404)
    );

    try {
      await client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} });
    } catch (e: any) {
      expect(e).toBeInstanceOf(ServerError);
      expect(e.status_code).toBe(404);
      expect(e.error_code).toBe('POLICY_NOT_FOUND');
    }
  });

  it('should throw ServerError on 500', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: 'Internal server error' }, 500)
    );

    try {
      await client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} });
    } catch (e: any) {
      expect(e).toBeInstanceOf(ServerError);
      expect(e.status_code).toBe(500);
    }
  });

  it('should throw NetworkError on fetch failure', async () => {
    fetchSpy.mockRejectedValue(new TypeError('fetch failed'));

    // Use 0 retries to fail immediately
    const noRetryConfig = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      max_retries: 0,
    });
    const noRetryClient = new HostedClient(noRetryConfig);

    await expect(
      noRetryClient.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} })
    ).rejects.toThrow(NetworkError);
  });
});

// --- Retry Logic ---

describe('HostedClient Retry', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    // Speed up tests by mocking setTimeout
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('should retry on 503 and succeed', async () => {
    fetchSpy
      .mockResolvedValueOnce(mockFetchResponse({}, 503))
      .mockResolvedValueOnce(mockFetchResponse(allowResponse()));

    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      max_retries: 3,
    });
    const client = new HostedClient(config);

    const decision = await client.evaluate({
      action: 'test',
      operation: 'read',
      target: {},
      parameters: {},
    });

    expect(decision.decision).toBe('ALLOW');
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('should exhaust retries and throw NetworkError', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse({}, 503));

    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      max_retries: 2,
    });
    const client = new HostedClient(config);

    await expect(
      client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} })
    ).rejects.toThrow(NetworkError);

    // 1 initial + 2 retries = 3 total
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it('should not retry on 400 or 404', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: 'Bad request' }, 400)
    );

    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      max_retries: 3,
    });
    const client = new HostedClient(config);

    await expect(
      client.evaluate({ action: 'test', operation: 'read', target: {}, parameters: {} })
    ).rejects.toThrow(ServerError);

    // Only 1 call — no retries for 400
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

// --- Signature ---

describe('HostedClient Signature', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue(mockFetchResponse(allowResponse()));
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should include signature when key is configured', async () => {
    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      signature_key: 'my-secret-key',
    });
    const client = new HostedClient(config);

    await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: {},
      parameters: { amount: 100 },
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.signature).toBeDefined();
    expect(body.signature).toHaveLength(64); // HMAC-SHA256 hex digest
  });

  it('should not include signature when no key is configured', async () => {
    const config = createHostedConfig({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });
    const client = new HostedClient(config);

    await client.evaluate({
      action: 'payment',
      operation: 'execute',
      target: {},
      parameters: {},
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.signature).toBeUndefined();
  });
});

// --- Backoff Delay ---

describe('backoffDelay', () => {
  it('should use exponential backoff', () => {
    expect(backoffDelay(0)).toBe(500);
    expect(backoffDelay(1)).toBe(1000);
    expect(backoffDelay(2)).toBe(2000);
  });

  it('should cap at 4000ms', () => {
    expect(backoffDelay(3)).toBe(4000);
    expect(backoffDelay(4)).toBe(4000);
    expect(backoffDelay(10)).toBe(4000);
  });
});

// --- HIITL Hosted Evaluate (end-to-end through client) ---

describe('HIITL Hosted Evaluate', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should evaluate via hosted mode and return Decision', async () => {
    fetchSpy.mockResolvedValue(mockFetchResponse(allowResponse()));

    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    const decision = await hiitl.evaluate({
      action: 'payment',
      parameters: { amount: 100 },
    });

    expect(decision.decision).toBe('ALLOW');
    expect(decision.allowed).toBe(true);
  });

  it('should propagate ServerError from hosted evaluate', async () => {
    fetchSpy.mockResolvedValue(
      mockFetchResponse({ detail: 'Unauthorized' }, 401)
    );

    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    await expect(
      hiitl.evaluate({
        action: 'test',
      })
    ).rejects.toThrow(ServerError);
  });

  it('should report mode as hosted', () => {
    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    expect(hiitl.mode).toBe('hosted');
  });

  it('should throw when queryAudit is called in hosted mode', () => {
    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    expect(() => hiitl.queryAudit({})).toThrow(/hosted mode/);
  });

  it('should not throw on close in hosted mode', () => {
    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
    });

    expect(() => hiitl.close()).not.toThrow();
  });

  it('should report evalMode', () => {
    const hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      org_id: VALID_ORG_ID,
      api_key: 'test-api-key-12345',
      server_url: 'https://api.hiitl.com',
      mode: 'RESPECT_POLICY',
    });

    expect(hiitl.evalMode).toBe('RESPECT_POLICY');
  });
});
