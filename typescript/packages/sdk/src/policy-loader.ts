/**
 * Policy loader - loads policies from JSON or YAML files.
 *
 * Per docs/specs/policy_format.md:
 * - JSON is the primary format (native format for evaluator)
 * - YAML is a convenience layer for human-friendly editing
 * - Both formats are converted to PolicySet objects for validation
 *
 * Design:
 * - Format detection by file extension (.json, .yaml, .yml)
 * - Fallback: try JSON first (faster), then YAML
 * - mtime-based caching to avoid re-parsing unchanged files
 * - Helpful error messages pointing to policy_format.md
 *
 * @example
 * ```typescript
 * import { PolicyLoader } from '@hiitl/sdk';
 *
 * const loader = new PolicyLoader('./policy.yaml');
 * const policy = loader.load(); // Parses and validates
 * const policyCached = loader.load(); // Cache hit - same object
 * ```
 */

import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import { PolicySetSchema } from '@hiitl/core';
import type { PolicySet } from '@hiitl/core';
import { PolicyLoadError } from './exceptions.js';

/**
 * Cached policy with modification time.
 */
interface CachedPolicy {
  policy: PolicySet;
  mtime: number;
}

/**
 * Loads and caches policy files from JSON or YAML.
 *
 * This loader supports both JSON (primary format) and YAML (convenience layer).
 * Policies are parsed into PolicySet objects and validated with Zod.
 *
 * The loader maintains an mtime-based cache to avoid re-parsing unchanged files.
 * This is critical for performance in high-throughput scenarios.
 *
 * @example
 * ```typescript
 * const loader = new PolicyLoader('./policy.yaml');
 * const policy = loader.load(); // Loads and caches
 * const samePol = loader.load(); // Cache hit - same object reference
 * ```
 */
export class PolicyLoader {
  private readonly policyPath: string;
  private cache: Map<string, CachedPolicy> = new Map();

  /**
   * Initialize policy loader.
   *
   * @param policyPath - Path to policy file (JSON or YAML format)
   */
  constructor(policyPath: string) {
    this.policyPath = policyPath;
  }

  /**
   * Load policy from JSON or YAML file with mtime-based caching.
   *
   * This method:
   * 1. Checks file modification time
   * 2. Returns cached policy if file unchanged
   * 3. Otherwise, parses file (JSON or YAML)
   * 4. Validates with Zod PolicySet schema
   * 5. Caches result for next call
   *
   * Format detection:
   * - .json extension → parse as JSON
   * - .yaml or .yml extension → parse as YAML
   * - No extension → try JSON first (faster), fallback to YAML
   *
   * @returns PolicySet object (validated)
   * @throws {PolicyLoadError} If file not found, invalid syntax, or validation fails
   */
  load(): PolicySet {
    // Check if file exists
    if (!fs.existsSync(this.policyPath)) {
      throw new PolicyLoadError(
        `Policy file not found: ${this.policyPath}\n\n` +
          'Make sure the path is correct and the file exists.\n' +
          'See docs/specs/policy_format.md for policy file format.'
      );
    }

    // Get current file modification time
    let currentMtime: number;
    try {
      const stats = fs.statSync(this.policyPath);
      currentMtime = stats.mtimeMs;
    } catch (e: any) {
      throw new PolicyLoadError(
        `Cannot access policy file ${this.policyPath}: ${e.message}`
      );
    }

    // Return cached policy if file unchanged
    const cached = this.cache.get(this.policyPath);
    if (cached && cached.mtime === currentMtime) {
      return cached.policy;
    }

    // Parse file to JavaScript object
    const policyDict = this._parseFile();

    // Handle optional "policy_set" wrapper
    // Some policy files wrap the policy in {"policy_set": {...}}
    const unwrapped =
      typeof policyDict === 'object' &&
      policyDict !== null &&
      'policy_set' in policyDict
        ? (policyDict as any).policy_set
        : policyDict;

    // Validate with Zod PolicySet schema
    let policy: PolicySet;
    try {
      policy = PolicySetSchema.parse(unwrapped);
    } catch (e: any) {
      throw new PolicyLoadError(
        `Invalid policy format in ${this.policyPath}:\n\n${e}\n\n` +
          "The policy file doesn't match the required schema.\n" +
          'Check docs/specs/policy_format.md for the correct format.\n\n' +
          'Note: JSON is the primary format; YAML is a convenience layer.\n' +
          'Both formats must produce valid PolicySet objects.'
      );
    }

    // Cache for next call
    this.cache.set(this.policyPath, { policy, mtime: currentMtime });

    return policy;
  }

  /**
   * Parse policy file to JavaScript object (JSON or YAML).
   *
   * Format detection:
   * 1. Check file extension (.json, .yaml, .yml)
   * 2. Parse accordingly
   * 3. If no extension or unknown, try JSON first (faster), then YAML
   *
   * @returns JavaScript object from JSON or YAML
   * @throws {PolicyLoadError} If file cannot be parsed as JSON or YAML
   * @private
   */
  private _parseFile(): unknown {
    const ext = path.extname(this.policyPath).toLowerCase();

    let content: string;
    try {
      content = fs.readFileSync(this.policyPath, 'utf-8');
    } catch (e: any) {
      throw new PolicyLoadError(
        `Cannot read policy file ${this.policyPath}: ${e.message}`
      );
    }

    // JSON format (primary)
    if (ext === '.json') {
      try {
        return JSON.parse(content);
      } catch (e: any) {
        throw new PolicyLoadError(
          `Invalid JSON in ${this.policyPath}:\n${e.message}\n\n` +
            'The file has .json extension but contains invalid JSON.\n' +
            'Check for syntax errors (missing commas, quotes, brackets).'
        );
      }
    }

    // YAML format (convenience layer)
    if (ext === '.yaml' || ext === '.yml') {
      try {
        const data = yaml.load(content);
        if (typeof data !== 'object' || data === null) {
          throw new PolicyLoadError(
            `Invalid YAML in ${this.policyPath}: ` +
              `YAML file must contain a mapping/dict, but got ${typeof data}`
          );
        }
        return data;
      } catch (e: any) {
        // Re-throw PolicyLoadError as-is
        if (e instanceof PolicyLoadError) {
          throw e;
        }
        throw new PolicyLoadError(
          `Invalid YAML in ${this.policyPath}:\n${e.message}\n\n` +
            'The file has .yaml/.yml extension but contains invalid YAML.\n' +
            'Check for syntax errors (indentation, colons, dashes).'
        );
      }
    }

    // Unknown or no extension: try JSON first, fallback to YAML
    try {
      return JSON.parse(content);
    } catch {
      // JSON parsing failed, try YAML
      try {
        const data = yaml.load(content);
        if (typeof data !== 'object' || data === null) {
          throw new PolicyLoadError(
            `Invalid policy file ${this.policyPath}: ` +
              `File must contain JSON object or YAML mapping, but got ${typeof data}`
          );
        }
        return data;
      } catch (yamlError: any) {
        // Re-throw PolicyLoadError as-is
        if (yamlError instanceof PolicyLoadError) {
          throw yamlError;
        }
        throw new PolicyLoadError(
          `Cannot parse ${this.policyPath} as JSON or YAML:\n${yamlError.message}\n\n` +
            'The file is neither valid JSON nor valid YAML.\n' +
            'Ensure the file is properly formatted.'
        );
      }
    }
  }

  /**
   * Invalidate cached policy, forcing reload on next load() call.
   *
   * This is useful for testing or when you know the file has changed
   * but the mtime might not have been updated (e.g., same-second edits).
   */
  invalidateCache(): void {
    this.cache.delete(this.policyPath);
  }

  /**
   * Clear all cached policies.
   *
   * This is useful for testing or resetting the loader state.
   */
  clearCache(): void {
    this.cache.clear();
  }
}
