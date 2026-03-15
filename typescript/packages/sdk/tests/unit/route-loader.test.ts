/**
 * Tests for RouteLoader - route config loading and escalation context resolution.
 *
 * Updated for routes.md spec: Route model types with direction-aware validation.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { RouteLoader, resolveEscalationContext } from '../../src/route-loader.js';
import { RouteLoadError } from '../../src/exceptions.js';
import { HIITL } from '../../src/client.js';

const FIXTURES_DIR = path.join(__dirname, '../fixtures');
const ROUTES_DIR = path.join(FIXTURES_DIR, 'routes');
const ESCALATION_POLICY = path.join(FIXTURES_DIR, 'escalation_policy.json');

// Helper: minimal valid bidirectional route YAML
function validBidirectionalYaml(name: string, overrides: Record<string, string> = {}): string {
  return [
    `name: "${name}"`,
    `version: "${overrides.version || 'v1.0.0'}"`,
    'direction: "bidirectional"',
    'timing: "sync"',
    `endpoint: "${overrides.endpoint || 'https://example.com/review'}"`,
    'response_schema:',
    '  decision_options:',
    '    - "approve"',
    '    - "deny"',
    'sla:',
    `  timeout: "${overrides.timeout || '1h'}"`,
    `  timeout_action: "${overrides.timeout_action || 'fail_closed'}"`,
  ].join('\n');
}

describe('RouteLoader', () => {
  describe('Initialization', () => {
    it('should initialize with a configs path', () => {
      const loader = new RouteLoader(ROUTES_DIR);
      expect(loader).toBeDefined();
    });

    it('should return null for nonexistent directory', () => {
      const loader = new RouteLoader('/nonexistent/routes');
      const route = loader.get('any-config');
      expect(route).toBeNull();
    });
  });

  describe('Loading Configs', () => {
    let loader: RouteLoader;

    beforeEach(() => {
      loader = new RouteLoader(ROUTES_DIR);
    });

    it('should load YAML config by name and return Route type', () => {
      const route = loader.get('finance-review');
      expect(route).not.toBeNull();
      expect(route!.name).toBe('finance-review');
      expect(route!.version).toBe('v1.0.0');
      expect(route!.direction).toBe('bidirectional');
      expect(route!.timing).toBe('sync');
      expect(route!.endpoint).toBe('https://review.example.com/api/v1/review');
      expect(route!.sla?.timeout).toBe('4h');
      expect(route!.sla?.timeout_action).toBe('escalate');
    });

    it('should load JSON config by name and return Route type', () => {
      const route = loader.get('simple-review');
      expect(route).not.toBeNull();
      expect(route!.name).toBe('simple-review');
      expect(route!.direction).toBe('bidirectional');
      expect(route!.endpoint).toBe('https://example.com/review');
      expect(route!.protocol).toBe('webhook');
    });

    it('should return null for missing config (non-fatal)', () => {
      const route = loader.get('nonexistent-config');
      expect(route).toBeNull();
    });

    it('should prefer .yaml over .yml and .json', () => {
      // Create a .yml file with different version
      const ymlPath = path.join(ROUTES_DIR, 'finance-review.yml');
      fs.writeFileSync(ymlPath, validBidirectionalYaml('finance-review', { version: 'v2.0.0' }));

      // Clear cache to force reload
      loader.clearCache();
      const route = loader.get('finance-review');
      expect(route).not.toBeNull();
      // Should load the .yaml file (v1.0.0), not the .yml (v2.0.0)
      expect(route!.version).toBe('v1.0.0');

      // Cleanup
      fs.unlinkSync(ymlPath);
    });
  });

  describe('Caching', () => {
    let loader: RouteLoader;

    beforeEach(() => {
      loader = new RouteLoader(ROUTES_DIR);
    });

    it('should return cached route on second load (same object)', () => {
      const route1 = loader.get('finance-review');
      const route2 = loader.get('finance-review');
      expect(route1).toBe(route2); // Same reference
    });

    it('should invalidate cache when file changes', () => {
      const tempPath = path.join(ROUTES_DIR, 'temp-config.yaml');
      fs.writeFileSync(tempPath, validBidirectionalYaml('temp-config', { version: 'v1.0.0' }));

      const route1 = loader.get('temp-config');
      expect(route1!.version).toBe('v1.0.0');

      // Wait briefly to ensure different mtime
      setTimeout(() => {
        fs.writeFileSync(tempPath, validBidirectionalYaml('temp-config', { version: 'v2.0.0' }));

        const route2 = loader.get('temp-config');
        expect(route2!.version).toBe('v2.0.0');

        // Cleanup
        fs.unlinkSync(tempPath);
      }, 10);
    });

    it('should clear all cached configs', () => {
      loader.get('finance-review');
      loader.get('simple-review');

      loader.clearCache();

      // Should reload fresh (no errors)
      const route = loader.get('finance-review');
      expect(route).not.toBeNull();
    });
  });

  describe('Validation', () => {
    let loader: RouteLoader;

    beforeEach(() => {
      loader = new RouteLoader(ROUTES_DIR);
    });

    afterEach(() => {
      // Cleanup any temp files
      const tempFiles = [
        'missing-direction.yaml', 'no-response-schema.yaml', 'no-sla.yaml',
        'no-endpoint.yaml', 'few-options.yaml', 'bad-version.yaml',
        'bad-timeout.yaml', 'name-mismatch.yaml', 'invalid-syntax.json',
        'invalid-syntax.yaml',
      ];
      for (const file of tempFiles) {
        const p = path.join(ROUTES_DIR, file);
        if (fs.existsSync(p)) fs.unlinkSync(p);
      }
    });

    it('should throw for missing required field: direction', () => {
      const tempPath = path.join(ROUTES_DIR, 'missing-direction.yaml');
      fs.writeFileSync(tempPath, [
        'name: "missing-direction"',
        'version: "v1.0.0"',
        'timing: "sync"',
        'endpoint: "https://example.com/review"',
        'response_schema:',
        '  decision_options: ["approve", "deny"]',
        'sla:',
        '  timeout: "1h"',
        '  timeout_action: "fail_closed"',
      ].join('\n'));

      expect(() => loader.get('missing-direction')).toThrow(RouteLoadError);
      expect(() => loader.get('missing-direction')).toThrow(/validation failed/);
    });

    it('should throw for bidirectional missing response_schema', () => {
      const tempPath = path.join(ROUTES_DIR, 'no-response-schema.yaml');
      fs.writeFileSync(tempPath, [
        'name: "no-response-schema"',
        'version: "v1.0.0"',
        'direction: "bidirectional"',
        'timing: "sync"',
        'endpoint: "https://example.com/review"',
        'sla:',
        '  timeout: "1h"',
        '  timeout_action: "fail_closed"',
      ].join('\n'));

      expect(() => loader.get('no-response-schema')).toThrow(RouteLoadError);
      expect(() => loader.get('no-response-schema')).toThrow(/response_schema/);
    });

    it('should throw for bidirectional missing sla', () => {
      const tempPath = path.join(ROUTES_DIR, 'no-sla.yaml');
      fs.writeFileSync(tempPath, [
        'name: "no-sla"',
        'version: "v1.0.0"',
        'direction: "bidirectional"',
        'timing: "sync"',
        'endpoint: "https://example.com/review"',
        'response_schema:',
        '  decision_options: ["approve", "deny"]',
      ].join('\n'));

      expect(() => loader.get('no-sla')).toThrow(RouteLoadError);
      expect(() => loader.get('no-sla')).toThrow(/sla/);
    });

    it('should throw for outbound missing endpoint', () => {
      const tempPath = path.join(ROUTES_DIR, 'no-endpoint.yaml');
      fs.writeFileSync(tempPath, [
        'name: "no-endpoint"',
        'version: "v1.0.0"',
        'direction: "outbound"',
        'timing: "async"',
      ].join('\n'));

      expect(() => loader.get('no-endpoint')).toThrow(RouteLoadError);
      expect(() => loader.get('no-endpoint')).toThrow(/endpoint/);
    });

    it('should throw for fewer than 2 decision_options', () => {
      const tempPath = path.join(ROUTES_DIR, 'few-options.yaml');
      fs.writeFileSync(tempPath, [
        'name: "few-options"',
        'version: "v1.0.0"',
        'direction: "bidirectional"',
        'timing: "sync"',
        'endpoint: "https://example.com/review"',
        'response_schema:',
        '  decision_options: ["approve"]',
        'sla:',
        '  timeout: "1h"',
        '  timeout_action: "fail_closed"',
      ].join('\n'));

      expect(() => loader.get('few-options')).toThrow(RouteLoadError);
    });

    it('should throw for invalid version format', () => {
      const tempPath = path.join(ROUTES_DIR, 'bad-version.yaml');
      fs.writeFileSync(tempPath, [
        'name: "bad-version"',
        'version: "1.0"',
        'direction: "outbound"',
        'timing: "async"',
        'endpoint: "https://example.com/events"',
      ].join('\n'));

      expect(() => loader.get('bad-version')).toThrow(RouteLoadError);
    });

    it('should throw for invalid SLA timeout format', () => {
      const tempPath = path.join(ROUTES_DIR, 'bad-timeout.yaml');
      fs.writeFileSync(tempPath, [
        'name: "bad-timeout"',
        'version: "v1.0.0"',
        'direction: "bidirectional"',
        'timing: "sync"',
        'endpoint: "https://example.com/review"',
        'response_schema:',
        '  decision_options: ["approve", "deny"]',
        'sla:',
        '  timeout: "4 hours"',
        '  timeout_action: "escalate"',
      ].join('\n'));

      expect(() => loader.get('bad-timeout')).toThrow(RouteLoadError);
    });

    it('should throw for config name mismatch with filename', () => {
      const tempPath = path.join(ROUTES_DIR, 'name-mismatch.yaml');
      fs.writeFileSync(tempPath, validBidirectionalYaml('wrong-name'));

      expect(() => loader.get('name-mismatch')).toThrow(RouteLoadError);
      expect(() => loader.get('name-mismatch')).toThrow(/name mismatch/);
    });

    it('should throw for invalid JSON syntax', () => {
      const tempPath = path.join(ROUTES_DIR, 'invalid-syntax.json');
      fs.writeFileSync(tempPath, '{ invalid json }');

      expect(() => loader.get('invalid-syntax')).toThrow(RouteLoadError);
      expect(() => loader.get('invalid-syntax')).toThrow(/Invalid JSON/);
    });

    it('should throw for invalid YAML syntax', () => {
      const tempPath = path.join(ROUTES_DIR, 'invalid-syntax.yaml');
      fs.writeFileSync(tempPath, ':\n  - :\n    bad: [yaml');

      // Clear cache in case .json was loaded first
      loader.clearCache();
      expect(() => loader.get('invalid-syntax')).toThrow(RouteLoadError);
    });
  });
});

describe('resolveEscalationContext', () => {
  it('should extract basic fields (endpoint, protocol, sla, decision_options)', () => {
    const loader = new RouteLoader(ROUTES_DIR);
    const route = loader.get('finance-review');
    expect(route).not.toBeNull();

    const context = resolveEscalationContext(route!);

    expect(context.endpoint).toBe('https://review.example.com/api/v1/review');
    expect(context.protocol).toBe('webhook');
    expect(context.timeout).toBe('4h');
    expect(context.timeout_action).toBe('escalate');
    expect(context.decision_options).toEqual(['approve', 'deny', 'modify']);
  });

  it('should extract context fields', () => {
    const loader = new RouteLoader(ROUTES_DIR);
    const route = loader.get('finance-review');
    expect(route).not.toBeNull();

    const context = resolveEscalationContext(route!);

    expect(context.fields).toBeDefined();
    expect(context.fields!.length).toBe(3);
    expect(context.fields![0].field_path).toBe('parameters.amount');
    expect(context.fields![0].label).toBe('Amount');
    expect(context.fields![0].format).toBe('currency');
  });

  it('should extract risk framing (severity, summary)', () => {
    const loader = new RouteLoader(ROUTES_DIR);
    const route = loader.get('finance-review');
    expect(route).not.toBeNull();

    const context = resolveEscalationContext(route!);

    expect(context.severity).toBe('high');
    expect(context.summary).toBe('Large payment requires finance team approval');
  });

  it('should omit severity and summary when not present', () => {
    const loader = new RouteLoader(ROUTES_DIR);
    const route = loader.get('simple-review');
    expect(route).not.toBeNull();

    const context = resolveEscalationContext(route!);

    expect(context.severity).toBeUndefined();
    expect(context.summary).toBeUndefined();
    expect(context.timeout).toBe('30m');
    expect(context.timeout_action).toBe('fail_closed');
  });
});

describe('Client Escalation Integration', () => {
  let hiitl: HIITL;

  afterEach(() => {
    hiitl?.close();
  });

  it('should resolve escalation_context for REQUIRE_APPROVAL decisions', () => {
    hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      policy_path: ESCALATION_POLICY,
      org_id: 'org_test000000000000000',
      audit_db_path: ':memory:',
      routes_path: ROUTES_DIR,
      mode: 'RESPECT_POLICY',
    });

    const decision = hiitl.evaluate({
      action: 'payment_transfer',
      target: { account_id: 'acct_123' },
      parameters: { amount: 5000 },
    });

    expect(decision.decision).toBe('REQUIRE_APPROVAL');
    expect(decision.allowed).toBe(false);
    expect(decision.route_ref).toBe('finance-review');
    expect(decision.resume_token).toMatch(/^rtk_[a-f0-9]{32}$/);

    // Escalation context should be populated from route config (new schema)
    expect(decision.escalation_context).toBeDefined();
    expect(decision.escalation_context!.endpoint).toBe('https://review.example.com/api/v1/review');
    expect(decision.escalation_context!.protocol).toBe('webhook');
    expect(decision.escalation_context!.timeout).toBe('4h');
    expect(decision.escalation_context!.timeout_action).toBe('escalate');
    expect(decision.escalation_context!.decision_options).toEqual(['approve', 'deny', 'modify']);
    expect(decision.escalation_context!.severity).toBe('high');
  });

  it('should NOT populate escalation_context for non-escalation decisions', () => {
    hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      policy_path: ESCALATION_POLICY,
      org_id: 'org_test000000000000000',
      audit_db_path: ':memory:',
      routes_path: ROUTES_DIR,
      mode: 'RESPECT_POLICY',
    });

    const decision = hiitl.evaluate({
      action: 'payment_transfer',
      target: { account_id: 'acct_123' },
      parameters: { amount: 100 }, // Small amount → ALLOW
    });

    expect(decision.decision).toBe('ALLOW');
    expect(decision.allowed).toBe(true);
    expect(decision.escalation_context).toBeUndefined();
  });

  it('should work without routes_path (no escalation resolution)', () => {
    hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      policy_path: ESCALATION_POLICY,
      org_id: 'org_test000000000000000',
      audit_db_path: ':memory:',
      mode: 'RESPECT_POLICY',
      // No routes_path
    });

    const decision = hiitl.evaluate({
      action: 'payment_transfer',
      target: { account_id: 'acct_123' },
      parameters: { amount: 5000 },
    });

    expect(decision.decision).toBe('REQUIRE_APPROVAL');
    expect(decision.route_ref).toBe('finance-review');
    expect(decision.resume_token).toBeDefined();
    // No escalation_context because no routes_path
    expect(decision.escalation_context).toBeUndefined();
  });

  it('should handle missing config file gracefully (non-fatal)', () => {
    // Create policy that references a config that doesn't exist
    const tempPolicyPath = path.join(FIXTURES_DIR, 'missing_config_policy.json');
    fs.writeFileSync(tempPolicyPath, JSON.stringify({
      name: 'missing-config-policy',
      version: '1.0',
      rules: [
        {
          name: 'escalate-all',
          description: 'Escalate everything',
          priority: 10,
          enabled: true,
          decision: 'REQUIRE_APPROVAL',
          reason_code: 'NEEDS_REVIEW',
          route: 'nonexistent-config',
          conditions: {
            field: 'environment',
            operator: 'equals',
            value: 'dev',
          },
        },
      ],
    }));

    hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      policy_path: tempPolicyPath,
      org_id: 'org_test000000000000000',
      audit_db_path: ':memory:',
      routes_path: ROUTES_DIR,
      mode: 'RESPECT_POLICY',
    });

    // Should NOT throw — missing config is non-fatal
    const decision = hiitl.evaluate({
      action: 'any_tool',
    });

    expect(decision.decision).toBe('REQUIRE_APPROVAL');
    expect(decision.route_ref).toBe('nonexistent-config');
    // No escalation_context because config doesn't exist
    expect(decision.escalation_context).toBeUndefined();

    // Cleanup
    fs.unlinkSync(tempPolicyPath);
  });

  it('should write audit record for escalation decisions', () => {
    hiitl = new HIITL({
      environment: 'dev',
      agent_id: 'test-agent',
      policy_path: ESCALATION_POLICY,
      org_id: 'org_test000000000000000',
      audit_db_path: ':memory:',
      routes_path: ROUTES_DIR,
      mode: 'RESPECT_POLICY',
    });

    const decision = hiitl.evaluate({
      action: 'payment_transfer',
      target: { account_id: 'acct_123' },
      parameters: { amount: 5000 },
    });

    // Query audit to verify record was written
    const records = hiitl.queryAudit({ action_id: decision.action_id });
    expect(records.length).toBeGreaterThan(0);

    const record = records[0];
    expect(record.decision_type).toBe('REQUIRE_APPROVAL');
  });
});
