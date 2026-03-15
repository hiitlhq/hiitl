/**
 * Audit logger - SQLite append-only audit log for HIITL.
 *
 * Design:
 * - Append-only pattern (no UPDATE or DELETE operations)
 * - SHA-256 content hashing for integrity verification
 * - Denormalized fields with indexes for efficient queries
 * - Synchronous API using better-sqlite3
 *
 * Schema:
 * - event_id (UUID primary key)
 * - timestamp (ISO 8601 UTC)
 * - org_id, environment, action_id (indexed)
 * - envelope, decision (JSON text)
 * - policy_version, decision_type (denormalized for queries)
 * - content_hash (SHA-256 for integrity)
 *
 * @example
 * ```typescript
 * import { AuditLogger } from '@hiitl/sdk';
 *
 * const logger = new AuditLogger('./hiitl_audit.db');
 * const eventId = logger.write(envelope, decision);
 * const verified = logger.verifyIntegrity(eventId);
 * ```
 */

import Database from 'better-sqlite3';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { Envelope, Decision } from '@hiitl/core';
import { AuditLogError } from './exceptions.js';

/**
 * Audit log record structure.
 */
export interface AuditRecord {
  event_id: string;
  timestamp: string;
  org_id: string;
  environment: string;
  action_id: string;
  envelope: string; // JSON
  decision: string; // JSON
  policy_version: string;
  decision_type: string;
  tool_name: string | null;
  agent_id: string | null;
  content_hash: string;
}

/**
 * Query options for retrieving audit records.
 */
export interface QueryOptions {
  limit?: number;
  offset?: number;
}

/**
 * SQLite append-only audit logger.
 *
 * This logger provides:
 * - Append-only writes (no UPDATE/DELETE)
 * - SHA-256 content hashing for integrity
 * - Efficient queries by org_id, action_id
 * - Zero external dependencies (SQLite embedded)
 *
 * Performance: ~2ms write latency (synchronous SQLite)
 *
 * @example
 * ```typescript
 * const logger = new AuditLogger('./hiitl_audit.db');
 * const eventId = logger.write(envelope, decision);
 * console.log('Audit event:', eventId);
 * ```
 */
export class AuditLogger {
  private db: Database.Database;
  private readonly dbPath: string;

  /**
   * Initialize audit logger with SQLite database.
   *
   * Creates database and schema if they don't exist.
   * Ensures parent directories exist.
   *
   * @param dbPath - Path to SQLite database file (or ':memory:' for in-memory)
   * @throws {AuditLogError} If database cannot be initialized
   */
  constructor(dbPath: string) {
    this.dbPath = dbPath;

    try {
      // Create parent directories if dbPath is not :memory:
      if (dbPath !== ':memory:') {
        const dir = path.dirname(dbPath);
        if (dir && dir !== '.') {
          fs.mkdirSync(dir, { recursive: true });
        }
      }

      // Open database (creates if missing)
      this.db = new Database(dbPath);

      // Initialize schema
      this._initDb();
    } catch (e: any) {
      throw new AuditLogError(
        `Failed to initialize audit database at ${dbPath}: ${e.message}\n\n` +
          'This could indicate:\n' +
          '1. Insufficient permissions to create/access the database file\n' +
          '2. Parent directory does not exist or is not writable\n' +
          '3. Database file is corrupted\n' +
          '4. Disk is full'
      );
    }
  }

  /**
   * Initialize database schema.
   *
   * Creates audit_log table and indexes if they don't exist.
   *
   * @private
   */
  private _initDb(): void {
    // Create audit_log table
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS audit_log (
        event_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        org_id TEXT NOT NULL,
        environment TEXT NOT NULL,
        action_id TEXT NOT NULL,
        envelope TEXT NOT NULL,
        decision TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        decision_type TEXT NOT NULL,
        tool_name TEXT,
        agent_id TEXT,
        content_hash TEXT NOT NULL
      )
    `);

    // Create indexes for efficient queries
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_org_timestamp
      ON audit_log(org_id, timestamp DESC)
    `);

    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_action_id
      ON audit_log(action_id)
    `);

    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_decision_type
      ON audit_log(decision_type, timestamp DESC)
    `);
  }

  /**
   * Write envelope and decision to audit log.
   *
   * This method:
   * 1. Generates unique event_id (evt_<32-char-hex>)
   * 2. Serializes envelope and decision to JSON
   * 3. Computes SHA-256 content hash
   * 4. Inserts record (synchronous)
   * 5. Returns event_id
   *
   * @param envelope - Execution envelope
   * @param decision - Policy decision
   * @returns event_id for the audit record
   * @throws {AuditLogError} If write fails
   */
  write(envelope: Envelope, decision: Decision): string {
    const eventId = `evt_${crypto.randomUUID().replace(/-/g, '')}`;
    const timestamp = new Date().toISOString();

    // Serialize to JSON (deterministic)
    const envelopeJson = JSON.stringify(envelope);
    const decisionJson = JSON.stringify(decision);

    // Compute SHA-256 hash for integrity
    const content = `${eventId}:${envelopeJson}:${decisionJson}`;
    const contentHash = crypto
      .createHash('sha256')
      .update(content)
      .digest('hex');

    // Prepare INSERT statement
    const stmt = this.db.prepare(`
      INSERT INTO audit_log (
        event_id, timestamp, org_id, environment, action_id,
        envelope, decision, policy_version, decision_type,
        tool_name, agent_id, content_hash
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    try {
      stmt.run(
        eventId,
        timestamp,
        envelope.org_id,
        envelope.environment,
        envelope.action_id,
        envelopeJson,
        decisionJson,
        decision.policy_version,
        decision.decision,
        envelope.action ?? null,
        envelope.agent_id ?? null,
        contentHash
      );
    } catch (e: any) {
      throw new AuditLogError(
        `Failed to write audit record to ${this.dbPath}: ${e.message}\n\n` +
          'This could indicate:\n' +
          '1. Database is locked (another process writing)\n' +
          '2. Disk is full\n' +
          '3. Database file permissions are incorrect\n' +
          '4. Database file is corrupted'
      );
    }

    return eventId;
  }

  /**
   * Query audit records by org_id.
   *
   * Returns records in descending timestamp order (newest first).
   *
   * @param org_id - Organization ID to filter by
   * @param options - Query options (limit, offset for pagination)
   * @returns Array of audit records
   */
  queryByOrgId(org_id: string, options: QueryOptions = {}): AuditRecord[] {
    const { limit, offset = 0 } = options;

    let sql = `
      SELECT * FROM audit_log
      WHERE org_id = ?
      ORDER BY timestamp DESC
    `;

    if (limit !== undefined) {
      sql += ` LIMIT ${limit} OFFSET ${offset}`;
    }

    const stmt = this.db.prepare(sql);
    return stmt.all(org_id) as AuditRecord[];
  }

  /**
   * Query audit records by action_id.
   *
   * Returns records matching the specific action_id.
   *
   * @param action_id - Action ID to filter by
   * @returns Array of audit records (usually 0 or 1)
   */
  queryByActionId(action_id: string): AuditRecord[] {
    const stmt = this.db.prepare(`
      SELECT * FROM audit_log
      WHERE action_id = ?
      ORDER BY timestamp DESC
    `);

    return stmt.all(action_id) as AuditRecord[];
  }

  /**
   * Query audit records by decision type.
   *
   * Useful for finding all BLOCK, ALLOW, etc. decisions.
   *
   * @param decision_type - Decision type (ALLOW, BLOCK, etc.)
   * @param options - Query options (limit, offset)
   * @returns Array of audit records
   */
  queryByDecisionType(
    decision_type: string,
    options: QueryOptions = {}
  ): AuditRecord[] {
    const { limit, offset = 0 } = options;

    let sql = `
      SELECT * FROM audit_log
      WHERE decision_type = ?
      ORDER BY timestamp DESC
    `;

    if (limit !== undefined) {
      sql += ` LIMIT ${limit} OFFSET ${offset}`;
    }

    const stmt = this.db.prepare(sql);
    return stmt.all(decision_type) as AuditRecord[];
  }

  /**
   * Get a single audit record by event_id.
   *
   * @param event_id - Event ID to retrieve
   * @returns Audit record or null if not found
   */
  get(event_id: string): AuditRecord | null {
    const stmt = this.db.prepare(`
      SELECT * FROM audit_log
      WHERE event_id = ?
    `);

    const row = stmt.get(event_id);
    return row ? (row as AuditRecord) : null;
  }

  /**
   * Verify integrity of an audit record via SHA-256 hash.
   *
   * Recomputes the content hash and compares to stored hash.
   *
   * @param event_id - Event ID to verify
   * @returns true if integrity check passes
   * @throws {AuditLogError} If event not found
   */
  verifyIntegrity(event_id: string): boolean {
    const record = this.get(event_id);

    if (!record) {
      throw new AuditLogError(
        `Event ${event_id} not found in audit log`
      );
    }

    // Recompute hash
    const content = `${record.event_id}:${record.envelope}:${record.decision}`;
    const computedHash = crypto
      .createHash('sha256')
      .update(content)
      .digest('hex');

    return computedHash === record.content_hash;
  }

  /**
   * Count total audit records.
   *
   * @returns Total number of records in audit log
   */
  count(): number {
    const stmt = this.db.prepare('SELECT COUNT(*) as count FROM audit_log');
    const row = stmt.get() as { count: number };
    return row.count;
  }

  /**
   * Close database connection.
   *
   * Should be called when done with the logger.
   */
  close(): void {
    this.db.close();
  }
}
