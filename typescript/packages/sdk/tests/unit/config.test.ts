/**
 * Tests for HIITL SDK configuration.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createConfig, LocalModeConfigSchema } from '../../src/config.js';
import type { LocalModeConfig } from '../../src/config.js';

describe('Config', () => {
  // Store original env vars
  const originalEnv = { ...process.env };

  // Reset env vars after each test
  afterEach(() => {
    process.env = { ...originalEnv };
  });

  describe('Valid Configuration', () => {
    it('should create valid config with all required fields', () => {
      const config = createConfig({
        environment: 'dev',
        agent_id: 'payment-agent',
        org_id: 'org_mycompany123456789',
        policy_path: './policy.yaml',
      });

      expect(config.environment).toBe('dev');
      expect(config.agent_id).toBe('payment-agent');
      expect(config.org_id).toBe('org_mycompany123456789');
      expect(config.policy_path).toBe('./policy.yaml');
      expect(config.audit_db_path).toBe('./hiitl_audit.db'); // Default
      expect(config.enable_rate_limiting).toBe(true); // Default
    });

    it('should accept all environment values', () => {
      const envs = ['dev', 'stage', 'prod'] as const;

      for (const env of envs) {
        const config = createConfig({
          environment: env,
          agent_id: 'test-agent',
          org_id: 'org_test000000000000000',
          policy_path: './policy.json',
        });

        expect(config.environment).toBe(env);
      }
    });

    it('should accept valid org_id patterns', () => {
      const validOrgIds = [
        'org_mycompany123456789', // Exactly 18 chars after prefix
        'org_abcdefghij0123456789', // 20 chars
        'org_' + 'a'.repeat(50), // Long org_id
        'org_000000000000000000', // All numbers
        'org_aaaaaaaaaaaaaaaaaa', // All letters
      ];

      for (const org_id of validOrgIds) {
        const config = createConfig({
          environment: 'dev',
          agent_id: 'test-agent',
          org_id,
          policy_path: './policy.json',
        });

        expect(config.org_id).toBe(org_id);
      }
    });

    it('should accept api_key for hybrid mode', () => {
      const config = createConfig({
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: 'org_test000000000000000',
        policy_path: './policy.json',
        api_key: 'sk_test_1234567890',
      });

      expect(config.api_key).toBe('sk_test_1234567890');
    });

    it('should accept custom defaults', () => {
      const config = createConfig({
        environment: 'prod',
        agent_id: 'production-agent',
        org_id: 'org_production123456789',
        policy_path: '/etc/hiitl/policy.yaml',
        audit_db_path: '/var/log/hiitl/audit.db',
        enable_rate_limiting: false,
      });

      expect(config.audit_db_path).toBe('/var/log/hiitl/audit.db');
      expect(config.enable_rate_limiting).toBe(false);
    });

    it('should accept signature_key', () => {
      const config = createConfig({
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: 'org_test000000000000000',
        policy_path: './policy.json',
        signature_key: 'test-secret-key-12345',
      });

      expect(config.signature_key).toBe('test-secret-key-12345');
    });
  });

  describe('Invalid Configuration', () => {
    it('should reject invalid environment', () => {
      expect(() =>
        createConfig({
          environment: 'production' as any, // Invalid
          agent_id: 'test-agent',
          org_id: 'org_test000000000000000',
          policy_path: './policy.json',
        })
      ).toThrow();
    });

    it('should reject invalid org_id patterns', () => {
      const invalidOrgIds = [
        'org_short', // Too short (< 18 chars)
        'org_HAS_UPPERCASE00000', // Has uppercase
        'mycompany123456789', // Missing prefix
        'org_has-dashes-00000000', // Has dashes
        'org_has_underscores_0000', // Has extra underscores
        'ORG_lowercase000000000', // Prefix uppercase
      ];

      for (const org_id of invalidOrgIds) {
        expect(() =>
          createConfig({
            environment: 'dev',
            agent_id: 'test-agent',
            org_id,
            policy_path: './policy.json',
          })
        ).toThrow(/Invalid org_id/);
      }
    });

    it('should reject empty agent_id', () => {
      expect(() =>
        createConfig({
          environment: 'dev',
          agent_id: '',
          org_id: 'org_test000000000000000',
          policy_path: './policy.json',
        })
      ).toThrow(/agent_id cannot be empty/);
    });

    it('should reject empty policy_path', () => {
      expect(() =>
        createConfig({
          environment: 'dev',
          agent_id: 'test-agent',
          org_id: 'org_test000000000000000',
          policy_path: '',
        })
      ).toThrow(/policy_path cannot be empty/);
    });

    it('should use defaults when no fields provided (zero-config)', () => {
      const config = createConfig({});

      expect(config.environment).toBe('dev');
      expect(config.agent_id).toBe('default');
      expect(config.org_id).toBe('org_devlocal0000000000');
      expect(config.mode).toBe('OBSERVE_ALL');
    });
  });

  describe('Environment Variables', () => {
    beforeEach(() => {
      // Clear HIITL_ env vars
      for (const key of Object.keys(process.env)) {
        if (key.startsWith('HIITL_')) {
          delete process.env[key];
        }
      }
    });

    it('should parse environment variables', () => {
      process.env.HIITL_ENVIRONMENT = 'stage';
      process.env.HIITL_AGENT_ID = 'env-agent';
      process.env.HIITL_ORG_ID = 'org_fromenv000000000000';
      process.env.HIITL_POLICY_PATH = '/etc/hiitl/policy.yaml';

      const config = createConfig({});

      expect(config.environment).toBe('stage');
      expect(config.agent_id).toBe('env-agent');
      expect(config.org_id).toBe('org_fromenv000000000000');
      expect(config.policy_path).toBe('/etc/hiitl/policy.yaml');
    });

    it('should parse HIITL_AUDIT_DB_PATH', () => {
      process.env.HIITL_ENVIRONMENT = 'dev';
      process.env.HIITL_AGENT_ID = 'test-agent';
      process.env.HIITL_ORG_ID = 'org_test000000000000000';
      process.env.HIITL_POLICY_PATH = './policy.json';
      process.env.HIITL_AUDIT_DB_PATH = '/custom/path/audit.db';

      const config = createConfig({});

      expect(config.audit_db_path).toBe('/custom/path/audit.db');
    });

    it('should parse HIITL_ENABLE_RATE_LIMITING=false', () => {
      process.env.HIITL_ENVIRONMENT = 'dev';
      process.env.HIITL_AGENT_ID = 'test-agent';
      process.env.HIITL_ORG_ID = 'org_test000000000000000';
      process.env.HIITL_POLICY_PATH = './policy.json';
      process.env.HIITL_ENABLE_RATE_LIMITING = 'false';

      const config = createConfig({});

      expect(config.enable_rate_limiting).toBe(false);
    });

    it('should parse HIITL_ENABLE_RATE_LIMITING=true', () => {
      process.env.HIITL_ENVIRONMENT = 'dev';
      process.env.HIITL_AGENT_ID = 'test-agent';
      process.env.HIITL_ORG_ID = 'org_test000000000000000';
      process.env.HIITL_POLICY_PATH = './policy.json';
      process.env.HIITL_ENABLE_RATE_LIMITING = 'true';

      const config = createConfig({});

      expect(config.enable_rate_limiting).toBe(true);
    });

    it('should parse HIITL_SIGNATURE_KEY', () => {
      process.env.HIITL_ENVIRONMENT = 'dev';
      process.env.HIITL_AGENT_ID = 'test-agent';
      process.env.HIITL_ORG_ID = 'org_test000000000000000';
      process.env.HIITL_POLICY_PATH = './policy.json';
      process.env.HIITL_SIGNATURE_KEY = 'env-secret-key';

      const config = createConfig({});

      expect(config.signature_key).toBe('env-secret-key');
    });

    it('should prioritize constructor args over env vars', () => {
      process.env.HIITL_ENVIRONMENT = 'stage';
      process.env.HIITL_AGENT_ID = 'env-agent';
      process.env.HIITL_ORG_ID = 'org_fromenv000000000000';
      process.env.HIITL_POLICY_PATH = '/etc/hiitl/policy.yaml';

      const config = createConfig({
        environment: 'prod', // Override
        agent_id: 'constructor-agent', // Override
        org_id: 'org_constructor00000000', // Override
        policy_path: './constructor.yaml', // Override
      });

      expect(config.environment).toBe('prod');
      expect(config.agent_id).toBe('constructor-agent');
      expect(config.org_id).toBe('org_constructor00000000');
      expect(config.policy_path).toBe('./constructor.yaml');
    });
  });

  describe('Zod Schema', () => {
    it('should validate with Zod schema directly', () => {
      const validConfig = {
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: 'org_test000000000000000',
        policy_path: './policy.json',
        audit_db_path: './audit.db',
        enable_rate_limiting: true,
      };

      const result = LocalModeConfigSchema.safeParse(validConfig);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.environment).toBe('dev');
        expect(result.data.agent_id).toBe('test-agent');
        expect(result.data.org_id).toBe('org_test000000000000000');
        expect(result.data.policy_path).toBe('./policy.json');
        expect(result.data.audit_db_path).toBe('./audit.db');
        expect(result.data.enable_rate_limiting).toBe(true);
        expect(result.data.mode).toBe('OBSERVE_ALL'); // Default
      }
    });

    it('should apply defaults via schema', () => {
      const minimalConfig = {
        environment: 'dev',
        agent_id: 'test-agent',
        org_id: 'org_test000000000000000',
        policy_path: './policy.json',
      };

      const result = LocalModeConfigSchema.safeParse(minimalConfig);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.audit_db_path).toBe('./hiitl_audit.db'); // Default
        expect(result.data.enable_rate_limiting).toBe(true); // Default
        expect(result.data.api_key).toBeUndefined(); // Default
      }
    });
  });
});
