/**
 * Route Loader - loads and resolves route configuration files.
 *
 * Per docs/specs/routes.md:
 * - Routes define how ECP communicates with external systems
 * - Referenced by name in policy rules via route field
 * - Loaded from directory of YAML/JSON files
 * - Config name must match filename (e.g., finance-review.yaml contains name: "finance-review")
 *
 * Design:
 * - Directory-based loading (one config per file)
 * - mtime-based caching (same pattern as PolicyLoader)
 * - Zod schema validation via RouteSchema from @hiitl/core
 * - Non-fatal resolution: missing configs produce warnings, not errors
 *
 * @example
 * ```typescript
 * import { RouteLoader, resolveEscalationContext } from '@hiitl/sdk';
 *
 * const loader = new RouteLoader('./routes/');
 * const route = loader.get('finance-review'); // Loads finance-review.yaml
 * if (route) {
 *   const context = resolveEscalationContext(route);
 * }
 * ```
 */

import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import { RouteSchema } from '@hiitl/core';
import type { Route } from '@hiitl/core';
import { RouteLoadError } from './exceptions.js';

/**
 * Cached route with modification time.
 */
interface CachedRoute {
  route: Route;
  mtime: number;
}

/**
 * Flattened escalation context extracted from a route.
 *
 * This is the shape that gets attached to Decision.escalation_context.
 * Derived from the new routes.md spec fields.
 */
export interface EscalationContext {
  endpoint?: string;
  protocol?: string;
  timeout?: string;
  timeout_action?: string;
  decision_options?: string[];
  fields?: Array<{ field_path: string; label?: string; format?: string }>;
  severity?: string;
  summary?: string;
  escalation_ladder?: {
    levels?: Array<{ level: number; route: string; after: string }>;
    max_escalation_depth?: number;
    final_timeout_action?: string;
  };
  token_field?: string;
}

/**
 * Loads and caches route configuration files from a directory.
 *
 * Routes define how ECP communicates with external systems for decisions
 * that require human intervention (REQUIRE_APPROVAL, PAUSE, ESCALATE).
 * They specify endpoint, SLA, response schema, and context fields.
 *
 * The loader searches for configs by name, trying extensions in order:
 * .yaml, .yml, .json
 *
 * @example
 * ```typescript
 * const loader = new RouteLoader('./routes/');
 * const route = loader.get('finance-review');
 * if (route) {
 *   console.log(`Timeout: ${route.sla?.timeout}`);
 * }
 * ```
 */
export class RouteLoader {
  private readonly configsPath: string;
  private cache: Map<string, CachedRoute> = new Map();

  /**
   * Initialize route loader.
   *
   * @param configsPath - Path to directory containing route config files
   */
  constructor(configsPath: string) {
    this.configsPath = configsPath;
  }

  /**
   * Load a route by name.
   *
   * Searches for the config file by trying extensions in order:
   * .yaml, .yml, .json
   *
   * Returns null if the config is not found (non-fatal — caller should
   * log a warning but still return the decision without escalation_context).
   *
   * @param configName - Name of the route config (matches filename without extension)
   * @returns Parsed and validated Route object, or null if not found
   * @throws {RouteLoadError} If the file exists but has invalid content
   */
  get(configName: string): Route | null {
    // Check if configs directory exists
    if (!fs.existsSync(this.configsPath)) {
      return null;
    }

    // Try extensions in order: .yaml, .yml, .json
    const extensions = ['.yaml', '.yml', '.json'];
    for (const ext of extensions) {
      const filePath = path.join(this.configsPath, `${configName}${ext}`);
      if (fs.existsSync(filePath)) {
        return this._loadFile(filePath, configName);
      }
    }

    // Config not found — non-fatal
    return null;
  }

  /**
   * Load and validate a single route config file with mtime-based caching.
   *
   * @param filePath - Absolute or relative path to the config file
   * @param configName - Expected config name (must match name field in file)
   * @returns Parsed and validated Route object
   * @throws {RouteLoadError} If file cannot be parsed or validation fails
   * @private
   */
  private _loadFile(filePath: string, configName: string): Route {
    // Get current file modification time
    let currentMtime: number;
    try {
      const stats = fs.statSync(filePath);
      currentMtime = stats.mtimeMs;
    } catch (e: any) {
      throw new RouteLoadError(
        `Cannot access route config file ${filePath}: ${e.message}`
      );
    }

    // Return cached route if file unchanged
    const cached = this.cache.get(filePath);
    if (cached && cached.mtime === currentMtime) {
      return cached.route;
    }

    // Read and parse file
    let content: string;
    try {
      content = fs.readFileSync(filePath, 'utf-8');
    } catch (e: any) {
      throw new RouteLoadError(
        `Cannot read route config file ${filePath}: ${e.message}`
      );
    }

    const ext = path.extname(filePath).toLowerCase();
    let rawConfig: Record<string, any>;

    if (ext === '.json') {
      try {
        rawConfig = JSON.parse(content);
      } catch (e: any) {
        throw new RouteLoadError(
          `Invalid JSON in route config ${filePath}:\n${e.message}\n\n` +
            'See docs/specs/routes.md for the correct format.'
        );
      }
    } else {
      // YAML (.yaml or .yml)
      try {
        const data = yaml.load(content);
        if (typeof data !== 'object' || data === null) {
          throw new RouteLoadError(
            `Invalid YAML in route config ${filePath}: ` +
              `Expected a mapping/object, got ${typeof data}`
          );
        }
        rawConfig = data as Record<string, any>;
      } catch (e: any) {
        if (e instanceof RouteLoadError) {
          throw e;
        }
        throw new RouteLoadError(
          `Invalid YAML in route config ${filePath}:\n${e.message}\n\n` +
            'See docs/specs/routes.md for the correct format.'
        );
      }
    }

    // Verify config name matches filename (before Zod validation for better error)
    if (rawConfig.name !== configName) {
      throw new RouteLoadError(
        `Route config name mismatch in ${filePath}: ` +
          `file contains name '${rawConfig.name}' but expected '${configName}'.\n\n` +
          'The name field in the config must match the filename (without extension).\n' +
          'See docs/specs/routes.md for naming conventions.'
      );
    }

    // Validate with Zod RouteSchema
    let route: Route;
    try {
      route = RouteSchema.parse(rawConfig);
    } catch (e: any) {
      const issues = e.errors?.map(
        (err: any) => `${err.path.join('.')}: ${err.message}`
      ) || [e.message];
      throw new RouteLoadError(
        `Route config validation failed for ${filePath}:\n` +
          issues.map((i: string) => `  - ${i}`).join('\n') + '\n\n' +
          'See docs/specs/routes.md for the full schema.'
      );
    }

    // Cache and return
    this.cache.set(filePath, { route, mtime: currentMtime });
    return route;
  }

  /**
   * Clear all cached configs.
   */
  clearCache(): void {
    this.cache.clear();
  }
}

/**
 * Extract flattened escalation context from a Route.
 *
 * This converts the Route model into a flat object suitable for
 * Decision.escalation_context. The SDK/server uses this to populate
 * the decision response — the evaluator only sets route_ref,
 * not escalation_context.
 *
 * @param route - Route object (from RouteLoader.get())
 * @returns Flattened escalation context for Decision.escalation_context
 *
 * @example
 * ```typescript
 * const route = loader.get('finance-review');
 * if (route) {
 *   const context = resolveEscalationContext(route);
 *   // { endpoint: "https://...", timeout: "4h", decision_options: ["approve", "deny"], ... }
 * }
 * ```
 */
export function resolveEscalationContext(route: Route): EscalationContext {
  const context: EscalationContext = {
    endpoint: route.endpoint,
    protocol: route.protocol,
  };

  // SLA fields
  if (route.sla) {
    context.timeout = route.sla.timeout;
    context.timeout_action = route.sla.timeout_action;
  }

  // Response schema
  if (route.response_schema) {
    context.decision_options = [...route.response_schema.decision_options];
  }

  // Context fields
  if (route.context?.fields) {
    context.fields = route.context.fields.map((f) => ({
      field_path: f.field_path,
      ...(f.label && { label: f.label }),
      ...(f.format && { format: f.format }),
    }));
  }

  // Risk framing
  if (route.context?.risk_framing) {
    if (route.context.risk_framing.severity) {
      context.severity = route.context.risk_framing.severity;
    }
    if (route.context.risk_framing.summary) {
      context.summary = route.context.risk_framing.summary;
    }
  }

  // Escalation ladder
  if (route.escalation_ladder) {
    context.escalation_ladder = {
      ...(route.escalation_ladder.levels && {
        levels: route.escalation_ladder.levels.map((l) => ({
          level: l.level,
          route: l.route,
          after: l.after,
        })),
      }),
      ...(route.escalation_ladder.max_escalation_depth !== undefined && {
        max_escalation_depth: route.escalation_ladder.max_escalation_depth,
      }),
      ...(route.escalation_ladder.final_timeout_action && {
        final_timeout_action: route.escalation_ladder.final_timeout_action,
      }),
    };
  }

  // Correlation
  if (route.correlation) {
    context.token_field = route.correlation.token_field;
  }

  return context;
}
