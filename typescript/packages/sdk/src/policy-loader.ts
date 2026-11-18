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
 * - File identity/change-metadata caching to avoid re-parsing unchanged files
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
import { z } from 'zod';
import { PolicySetSchema, assertNumericDomain, assertSchemaNumbers, parseAdmittedNumbers, NumericDomainError } from '@hiitl/core';
import type { PolicySet } from '@hiitl/core';
import { PolicyLoadError } from './exceptions.js';
import { readFileClock } from './file-clock.js';

/**
 * A policy's or route's YAML, read as the JSON it converts to ("a thin parsing layer that converts to JSON",
 * policy_format.md). JSON has no timestamp, so YAML's is not resolved: a date-time written in YAML is the string
 * written, which the core reads as it reads the JSON's (ecp_evaluate_spec.md "A date-time is read by RFC 3339's
 * grammar"), and an explicit `!!timestamp` is refused. Mirrors python/hiitl/sdk/policy_loader.py's `YAMLForm`.
 */
// YAML1.2.2 §10.3.2; unrelated existing safe tags are unchanged.
const scalar = (kind: string, expression: RegExp, construct: (raw: string) => unknown): yaml.Type =>
  new yaml.Type('tag:yaml.org,2002:' + kind, {
    kind: 'scalar', resolve: (raw) => expression.test(raw ?? ''), construct: (raw) => construct(raw ?? ''),
  });
const coreNull = scalar('null', /^(?:null|Null|NULL|~|)$/, () => null);
const coreBool = scalar('bool', /^(?:true|True|TRUE|false|False|FALSE)$/, raw => raw.toLowerCase() === 'true');
const coreInt = scalar('int', /^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$/, raw =>
  raw.startsWith('0o') ? parseInt(raw.slice(2), 8) : raw.startsWith('0x') ? parseInt(raw.slice(2), 16) : Number(raw));
const coreFloat = scalar('float', /^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?(?:\.inf|\.Inf|\.INF)|\.nan|\.NaN|\.NAN)$/, raw => {
  const lower = raw.toLowerCase();
  if (lower.replace(/^[-+]/, '') === '.inf') return lower.startsWith('-') ? -Infinity : Infinity;
  if (lower === '.nan') return NaN;
  return Number(raw);
});
export const YAML_FORM = yaml.DEFAULT_SCHEMA.extend({
  implicit: [coreNull, coreBool, coreInt, coreFloat,
    new yaml.Type('tag:yaml.org,2002:timestamp', { kind: 'scalar', resolve: () => false })],
});

/** Read Core scalars, then admit the whole held tree before any projection. */
export const loadYaml = (content: string, admit = true): unknown => {
  const value = yaml.load(content, { schema: YAML_FORM });
  if(admit)assertNumericDomain(value);
  return value;
};

/**
 * Cached policy with the file identity and change metadata it was read from.
 */
interface CachedPolicy {
  policy: PolicySet;
  metadata: string;
  content: string;
  timestampsDistinguish: boolean;
}

/**
 * Loads and caches policy files from JSON or YAML.
 *
 * This loader supports both JSON (primary format) and YAML (convenience layer).
 * Policies are parsed into PolicySet objects and validated with Zod.
 *
 * The loader holds a reading while file identity and change metadata agree.
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
   * Load policy from JSON or YAML file with metadata-based caching.
   *
   * This method:
   * 1. Checks file identity and change metadata
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
          'See docs/specs/policy_format.md for policy file format.',
        'POLICY_NOT_FOUND'
      );
    }

    // Read metadata before content, so a concurrent change invalidates on the
    // next call. BigInt timestamps preserve the filesystem's precision; atime
    // is a read observation, not a change to the held source.
    let currentMetadata: string;
    let current: fs.BigIntStats;
    try {
      const stats = current = fs.statSync(this.policyPath, {bigint: true});
      currentMetadata = [stats.dev, stats.ino, stats.size, stats.mtimeNs, stats.ctimeNs,
        stats.mode, stats.uid, stats.gid, stats.nlink].join(':');
    } catch (e: any) {
      throw new PolicyLoadError(`Cannot access policy file ${this.policyPath}: ${e.message}`, 'POLICY_LOAD_FAILED');
    }

    // Return cached policy if file unchanged
    const cached = this.cache.get(this.policyPath);
    if (cached && cached.metadata === currentMetadata && cached.timestampsDistinguish) {
      return cached.policy;
    }

    const readTime = readFileClock(current);
    const content = this._readFile();
    const timestampsDistinguish = readTime !== undefined && current.ctimeNs < readTime;
    if (cached && cached.metadata === currentMetadata && cached.content === content) {
      cached.timestampsDistinguish = timestampsDistinguish;
      return cached.policy;
    }
    // Changed content is parsed and admitted at its source, as before.
    const policyDict = this._parseFile(content);
    try {
      const wrapped=policyDict!==null && typeof policyDict==='object' && Object.hasOwn(policyDict,'policy_set');
      assertSchemaNumbers(policyDict,wrapped?z.object({policy_set:PolicySetSchema}):PolicySetSchema);
    }catch(error){
      if(!(error instanceof NumericDomainError))throw error;
      throw new PolicyLoadError(`Invalid policy numeric value in ${this.policyPath}: ${error.message}`);
    }

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
      policy = parseAdmittedNumbers(PolicySetSchema,unwrapped);
    } catch (e: any) {
      throw new PolicyLoadError(
        `Invalid policy format at <root> in ${this.policyPath}:\n\n${e}\n\n` +
          "The policy file doesn't match the required schema.\n" +
          'Check docs/specs/policy_format.md for the correct format.\n\n' +
          'Note: JSON is the primary format; YAML is a convenience layer.\n' +
          'Both formats must produce valid PolicySet objects.'
      );
    }

    // Cache for next call
    this.cache.set(this.policyPath, { policy, metadata: currentMetadata, content, timestampsDistinguish });

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
  private _readFile(): string {
    try {
      return fs.readFileSync(this.policyPath, 'utf-8');
    } catch (e: any) {
      throw new PolicyLoadError(`Cannot read policy file ${this.policyPath}: ${e.message}`, 'POLICY_LOAD_FAILED');
    }
  }

  private _parseFile(content = this._readFile()): unknown {
    const ext = path.extname(this.policyPath).toLowerCase();

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
        const data = loadYaml(content, false);
        if (typeof data !== 'object' || data === null) {
          throw new PolicyLoadError(
            `Invalid YAML in ${this.policyPath}: ` +
              `YAML file at <root> policy root must contain a mapping/dict, but got ${typeof data}`
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
        const data = loadYaml(content, false);
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
