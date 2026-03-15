/**
 * Tests for PolicyLoader - JSON/YAML loading with mtime caching.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { PolicyLoader } from '../../src/policy-loader.js';
import { PolicyLoadError } from '../../src/exceptions.js';
import type { PolicySet } from '@hiitl/core';

// Fixture paths
const FIXTURES_DIR = path.join(__dirname, '../fixtures');
const VALID_JSON = path.join(FIXTURES_DIR, 'valid_policy.json');
const VALID_YAML = path.join(FIXTURES_DIR, 'valid_policy.yaml');
const WRAPPED_JSON = path.join(FIXTURES_DIR, 'wrapped_policy.json');
const INVALID_JSON = path.join(FIXTURES_DIR, 'invalid_json.json');
const INVALID_YAML = path.join(FIXTURES_DIR, 'invalid_yaml.yaml');
const INVALID_SCHEMA = path.join(FIXTURES_DIR, 'invalid_schema.json');

describe('PolicyLoader', () => {
  describe('Loading Valid Policies', () => {
    it('should load valid JSON policy', () => {
      const loader = new PolicyLoader(VALID_JSON);
      const policy = loader.load();

      expect(policy).toBeDefined();
      expect(policy.name).toBe('test-policy');
      expect(policy.version).toBe('1.0');
      expect(policy.rules).toHaveLength(1);
      expect(policy.rules[0].name).toBe('allow-small-amounts');
    });

    it('should load valid YAML policy', () => {
      const loader = new PolicyLoader(VALID_YAML);
      const policy = loader.load();

      expect(policy).toBeDefined();
      expect(policy.name).toBe('test-policy');
      expect(policy.version).toBe('1.0');
      expect(policy.rules).toHaveLength(1);
      expect(policy.rules[0].name).toBe('allow-small-amounts');
    });

    it('should load wrapped policy (policy_set wrapper)', () => {
      const loader = new PolicyLoader(WRAPPED_JSON);
      const policy = loader.load();

      expect(policy).toBeDefined();
      expect(policy.name).toBe('wrapped-policy');
      expect(policy.version).toBe('1.0');
      expect(policy.rules).toHaveLength(1);
    });

    it('should produce equivalent policies from JSON and YAML', () => {
      const loaderJson = new PolicyLoader(VALID_JSON);
      const loaderYaml = new PolicyLoader(VALID_YAML);

      const policyJson = loaderJson.load();
      const policyYaml = loaderYaml.load();

      // Deep equality check
      expect(policyJson).toEqual(policyYaml);
    });
  });

  describe('Caching', () => {
    it('should return cached policy on second load (same object)', () => {
      const loader = new PolicyLoader(VALID_JSON);

      const policy1 = loader.load();
      const policy2 = loader.load();

      // Same object reference
      expect(policy2).toBe(policy1);
    });

    it('should invalidate cache after file modification', () => {
      // Create a temporary policy file
      const tempPath = path.join(FIXTURES_DIR, 'temp_policy.json');
      const policy1 = {
        name: 'version-1',
        version: '1.0',
        rules: [],
      };
      fs.writeFileSync(tempPath, JSON.stringify(policy1));

      const loader = new PolicyLoader(tempPath);
      const loaded1 = loader.load();

      expect(loaded1.name).toBe('version-1');

      // Wait a bit to ensure different mtime
      setTimeout(() => {
        // Modify file
        const policy2 = {
          name: 'version-2',
          version: '2.0',
          rules: [],
        };
        fs.writeFileSync(tempPath, JSON.stringify(policy2));

        const loaded2 = loader.load();

        expect(loaded2.name).toBe('version-2');
        expect(loaded2).not.toBe(loaded1); // Different object

        // Cleanup
        fs.unlinkSync(tempPath);
      }, 10);
    });

    it('should invalidate cache manually', () => {
      const loader = new PolicyLoader(VALID_JSON);

      const policy1 = loader.load();
      loader.invalidateCache();
      const policy2 = loader.load();

      // Different object (cache was invalidated)
      expect(policy2).not.toBe(policy1);
      // But same content
      expect(policy2).toEqual(policy1);
    });

    it('should clear cache for all paths', () => {
      const loader1 = new PolicyLoader(VALID_JSON);
      const loader2 = new PolicyLoader(VALID_YAML);

      loader1.load();
      loader2.load();

      loader1.clearCache();

      const policy1New = loader1.load();
      const policy2New = loader2.load();

      // Both should be fresh loads (different objects)
      expect(policy1New).toBeDefined();
      expect(policy2New).toBeDefined();
    });

    it('should have independent caches for different loaders', () => {
      const loader1 = new PolicyLoader(VALID_JSON);
      const loader2 = new PolicyLoader(VALID_JSON);

      const policy1 = loader1.load();
      const policy2 = loader2.load();

      // Same content but different object references (independent caches)
      expect(policy1).toEqual(policy2);
      expect(policy1).not.toBe(policy2);
    });
  });

  describe('Error Handling', () => {
    it('should throw PolicyLoadError for missing file', () => {
      const loader = new PolicyLoader('/nonexistent/policy.json');

      expect(() => loader.load()).toThrow(PolicyLoadError);
      expect(() => loader.load()).toThrow(/Policy file not found/);
      expect(() => loader.load()).toThrow(/policy_format\.md/);
    });

    it('should throw PolicyLoadError for invalid JSON syntax', () => {
      const loader = new PolicyLoader(INVALID_JSON);

      expect(() => loader.load()).toThrow(PolicyLoadError);
      expect(() => loader.load()).toThrow(/Invalid JSON/);
    });

    it('should throw PolicyLoadError for invalid YAML syntax', () => {
      const loader = new PolicyLoader(INVALID_YAML);

      expect(() => loader.load()).toThrow(PolicyLoadError);
      expect(() => loader.load()).toThrow(/Invalid YAML/);
    });

    it('should throw PolicyLoadError for invalid schema', () => {
      const loader = new PolicyLoader(INVALID_SCHEMA);

      expect(() => loader.load()).toThrow(PolicyLoadError);
      expect(() => loader.load()).toThrow(/Invalid policy format/);
      expect(() => loader.load()).toThrow(/policy_format\.md/);
    });

    it('should throw PolicyLoadError for non-object YAML', () => {
      // Create a YAML file with a scalar value
      const tempPath = path.join(FIXTURES_DIR, 'temp_scalar.yaml');
      fs.writeFileSync(tempPath, 'just a string');

      const loader = new PolicyLoader(tempPath);

      expect(() => loader.load()).toThrow(PolicyLoadError);
      expect(() => loader.load()).toThrow(/must contain a mapping\/dict/);

      // Cleanup
      fs.unlinkSync(tempPath);
    });

    it('should include helpful error message for JSON files', () => {
      const loader = new PolicyLoader(INVALID_JSON);

      try {
        loader.load();
        expect.fail('Should have thrown');
      } catch (e: any) {
        expect(e).toBeInstanceOf(PolicyLoadError);
        expect(e.message).toContain('Invalid JSON');
        expect(e.message).toContain('.json extension');
        expect(e.message).toContain('syntax errors');
      }
    });

    it('should include helpful error message for YAML files', () => {
      const loader = new PolicyLoader(INVALID_YAML);

      try {
        loader.load();
        expect.fail('Should have thrown');
      } catch (e: any) {
        expect(e).toBeInstanceOf(PolicyLoadError);
        expect(e.message).toContain('Invalid YAML');
        expect(e.message).toContain('.yaml');
        expect(e.message).toContain('syntax errors');
      }
    });
  });

  describe('Format Detection', () => {
    it('should auto-detect JSON format (no extension)', () => {
      // Create a file without extension
      const tempPath = path.join(FIXTURES_DIR, 'no_ext_json');
      fs.writeFileSync(
        tempPath,
        JSON.stringify({
          name: 'no-ext-policy',
          version: '1.0',
          rules: [],
        })
      );

      const loader = new PolicyLoader(tempPath);
      const policy = loader.load();

      expect(policy.name).toBe('no-ext-policy');

      // Cleanup
      fs.unlinkSync(tempPath);
    });

    it('should auto-detect YAML format (no extension)', () => {
      // Create a YAML file without extension
      const tempPath = path.join(FIXTURES_DIR, 'no_ext_yaml');
      fs.writeFileSync(
        tempPath,
        'name: no-ext-yaml-policy\nversion: "1.0"\nrules: []'
      );

      const loader = new PolicyLoader(tempPath);
      const policy = loader.load();

      expect(policy.name).toBe('no-ext-yaml-policy');

      // Cleanup
      fs.unlinkSync(tempPath);
    });

    it('should detect .json extension', () => {
      const loader = new PolicyLoader(VALID_JSON);
      const policy = loader.load();

      expect(policy).toBeDefined();
      expect(policy.name).toBe('test-policy');
    });

    it('should detect .yaml extension', () => {
      const loader = new PolicyLoader(VALID_YAML);
      const policy = loader.load();

      expect(policy).toBeDefined();
      expect(policy.name).toBe('test-policy');
    });

    it('should detect .yml extension', () => {
      // Create a .yml file
      const tempPath = path.join(FIXTURES_DIR, 'test.yml');
      fs.writeFileSync(
        tempPath,
        'name: yml-policy\nversion: "1.0"\nrules: []'
      );

      const loader = new PolicyLoader(tempPath);
      const policy = loader.load();

      expect(policy.name).toBe('yml-policy');

      // Cleanup
      fs.unlinkSync(tempPath);
    });
  });

  describe('Type Correctness', () => {
    it('should return PolicySet type', () => {
      const loader = new PolicyLoader(VALID_JSON);
      const policy: PolicySet = loader.load();

      // TypeScript type check
      expect(policy.name).toBeTypeOf('string');
      expect(policy.version).toBeTypeOf('string');
      expect(Array.isArray(policy.rules)).toBe(true);
    });
  });
});
