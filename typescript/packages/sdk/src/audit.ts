/**
 * Audit logger - SQLite append-only audit log for HIITL.
 *
 * Design:
 * - Append-only: a record's content, and each member read from it, never changes. The one write after
 *   the insert is a mark beside it (`synced`, `refused`), outside its hash (event_format.md "Append-Only
 *   Requirement"). `held_results` holds no record: a held result is removed once the service answers it
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
 * - each further member core's AUDIT_FURTHER names (JSON text, null on a record that does not carry it)
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
import { AUDIT_FURTHER, auditContentHash, auditHashMatches, assertNumericDomain, assertSchemaNumbers, EnvelopeSchema, DecisionSchema, ResultNumberSchema, NumericDomainError, ENVELOPE_RENAMED, eventType, ORG_FIELDS, readDateTime, Redaction } from '@hiitl/core';
import type { UnreadReview } from '@hiitl/core';
import { AuditLogError } from './exceptions.js';
import { storeKey } from './hash-key.js';

function auditNumbers(value:unknown,path:(string|number)[],schema?:Parameters<typeof assertSchemaNumbers>[1]):void {
  try {
    if(schema)assertSchemaNumbers(value,schema,path);else assertNumericDomain(value,path);
  }catch(error){
    if(!(error instanceof NumericDomainError))throw error;
    throw new AuditLogError(`New audit record refused: ${error.message}`);
  }
}


/**
 * The file at `p`, whatever name reaches it: its device and inode, which POSIX names its identity (`<sys/stat.h>`, "The
 * st_ino and st_dev fields taken together uniquely identify the file within the system"). Read as bigints, which hold
 * an inode past 2^53.
 */
function fileIdentity(p: string): string {
  const st = fs.statSync(p, { bigint: true });
  return `${st.dev}:${st.ino}`;
}

// A record still to send: not synced, and not refused for its own content (sync_engine.md section 2.1, row 224). Every
// read of the records still to send reads this one predicate. Mirrors audit.py `_PENDING`.
const PENDING = 'synced = 0 AND refused IS NULL';

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
  /** The envelope's action, under its name (event_format.md 2.0). */
  action: string | null;
  agent_id: string | null;
  content_hash: string;
  /** On a result record only (event_format.md "The lifecycle"). */
  execution_result?: Record<string, unknown>;
  /** Only where a declared path is absent: `{absent: [...]}` (event_format.md §Redaction). */
  redaction?: { absent: string[] };
  /** On a result for a held decision whose writer holds no review case: `{unread: <resume_token>}` (row 217). */
  review?: UnreadReview;
  /** Computed as the record is read from its decision (event_format.md "Event types"), in no column. */
  event_type: string;
}

/**
 * The record's hash over its content as stored, each further member it carries a term (row 191). The members are
 * core's `AUDIT_FURTHER`, the one copy (event_format.md `content_hash`).
 */
function contentHash(eventId: string, envelope: unknown, decision: unknown, carried: Record<string, unknown>): string {
  const further = AUDIT_FURTHER.filter((m) => carried[m] != null).map((m) => [m, carried[m]]);
  return auditContentHash(eventId, envelope, decision, Object.fromEntries(further));
}

/**
 * A record as it is read and uploaded: each further member it carries parsed, one it does not carry absent (its
 * column null), and carrying its `event_type`, computed from its decision and its `execution_result`, never stored in
 * a column (event_format.md "Event types" and "Where it is held"; HTL-22 row 150). Mirrors audit.py `_as_read`.
 */
function asRead<R extends object>(row: R): R & { event_type: string } {
  const read = row as Record<string, unknown>;
  for (const member of AUDIT_FURTHER) {
    const value = read[member];
    if (value === null || value === undefined) delete read[member];
    else if (typeof value === 'string') read[member] = JSON.parse(value);
  }
  const result = read.execution_result as { status?: unknown } | undefined;
  return Object.assign(row, { event_type: eventType(read.decision_type as string, result) });
}

/** The envelope and decision columns parsed back into objects, best-effort, as the upload and the lifecycle read them. */
function parsed(row: Record<string, unknown>): Record<string, unknown> {
  for (const column of ['envelope', 'decision']) {
    if (typeof row[column] === 'string') {
      try {
        row[column] = JSON.parse(row[column] as string);
      } catch {
        // leave as string
      }
    }
  }
  return row;
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
const ADMITTED_WRITE=Symbol('SDK produced record');

export class AuditLogger {
  /** The step each key's in-flight call ends with, by store and key (HTL-29 row 160). */
  private static readonly _tails = new Map<string, Promise<void>>();
  private db: Database.Database;
  private readonly dbPath: string;
  /** The store's identity in this process: the file it opened, or this instance for ':memory:' (row 160). */
  private readonly store: string;
  private readonly redaction: Redaction;
  private readonly orgDeclared?: () => readonly string[];

  /**
   * Initialize audit logger with SQLite database.
   *
   * Creates database and schema if they don't exist.
   * Ensures parent directories exist.
   *
   * @param dbPath - Path to SQLite database file (or ':memory:' for in-memory)
   * @param redaction - What the record holds in place of each declared field (event_format.md §Redaction)
   * @param orgDeclared - The org's declared fields as last pulled (hybrid mode). Each write redacts the union of them
   *   and `redaction`'s (row 163(a)).
   * @throws {AuditLogError} If database cannot be initialized
   */
  constructor(dbPath: string, redaction: Redaction = Redaction.declared(), orgDeclared?: () => readonly string[]) {
    this.dbPath = dbPath;
    this.orgDeclared = orgDeclared;

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
    // The store is the file it opened, whatever name reached it (HTL-29 review, condition 3)
    this.store = dbPath === ':memory:' ? `:memory:${crypto.randomUUID()}` : fileIdentity(dbPath);
    if (redaction.recordedParameters !== undefined) {
      // The value hash's key lives beside the store's file, made at its first start (row 163(c))
      try {
        redaction = redaction.keyed(storeKey(dbPath));
      } catch (e: any) {
        this.db.close();
        throw new AuditLogError(`The audit store ${dbPath} has no usable value-hash key: ${e.message}`);
      }
    }
    this.redaction = redaction;
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
        action TEXT,
        agent_id TEXT,
        content_hash TEXT NOT NULL,
        synced INTEGER DEFAULT 0,
        refused TEXT,
        ${AUDIT_FURTHER.map((m) => `${m} TEXT`).join(',\n        ')}
      )
    `);

    // Migration: add synced column to existing databases that pre-date
    // Block 5e. SQLite allows IF NOT EXISTS on tables but not on
    // ALTER TABLE — so we probe via PRAGMA table_info and add the
    // column when missing. Matches the python/hiitl/sdk/audit.py migration.
    const cols = this.db.prepare("PRAGMA table_info(audit_log)").all() as Array<{
      name: string;
    }>;
    // The record projects the envelope's members under the envelope's names, so a store written before record format
    // 2.0 renames each column the envelope schema renamed; each record keeps its value, its hash (the member is outside
    // it) and its synced mark (event_format.md 2.0, "From 1.x"; row 230). Mirrors audit.py.
    for (const [old, now] of Object.entries(ENVELOPE_RENAMED)) {
      if (cols.some((c) => c.name === old)) this.db.exec(`ALTER TABLE audit_log RENAME COLUMN ${old} TO ${now}`);
    }
    if (!cols.some((c) => c.name === 'synced')) {
      this.db.exec(`ALTER TABLE audit_log ADD COLUMN synced INTEGER DEFAULT 0`);
    }
    // A store written before the refused mark gains it, null on the records it holds; their synced marks stand, so a
    // record synced before stays synced and one still to send stays to send (row 224)
    if (!cols.some((c) => c.name === 'refused')) {
      this.db.exec(`ALTER TABLE audit_log ADD COLUMN refused TEXT`);
    }
    // A store written before the further members gains their columns, null on the records it holds: none of them
    // carries one, so each hashes as it did (row 191)
    for (const member of AUDIT_FURTHER) {
      if (!cols.some((c) => c.name === member)) this.db.exec(`ALTER TABLE audit_log ADD COLUMN ${member} TEXT`);
    }

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

    // Index for the sync drain query. Ordered by timestamp ASC so the
    // server receives records in chronological order — matches Python.
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_synced
      ON audit_log(synced, timestamp ASC)
    `);

    // A repeated idempotency key is found by the key the recorded envelope carries (row 143)
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_idempotency_key
      ON audit_log(org_id, environment, json_extract(envelope, '$.idempotency_key'))
    `);

    // A result the hosted service could not take, held until the hosted client pushes it (event_format.md "The
    // Lifecycle"; row 200). It is no record: the service writes the result record when it takes it.
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS held_results (
        action_id TEXT NOT NULL,
        execution_result TEXT NOT NULL
      )
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
  /** @internal Inputs were admitted and the Decision produced in this SDK call. */
  _writeAdmitted(envelope:Envelope,decision:Decision):string {return this.write(envelope,decision,ADMITTED_WRITE);}

  write(envelope: Envelope, decision: Decision, admission?:typeof ADMITTED_WRITE): string {
    if(admission!==ADMITTED_WRITE){
      auditNumbers(envelope,['envelope'],EnvelopeSchema);
      auditNumbers(decision,['decision'],DecisionSchema);
    }
    const eventId = `evt_${crypto.randomUUID().replace(/-/g, '')}`;
    const timestamp = new Date().toISOString();

    // Serialize to JSON (deterministic)
    let envelopeJson = JSON.stringify(envelope);
    let decisionJson = JSON.stringify(decision);

    // The record as stored (event_format.md §Redaction, row 139): each declared field's value replaced, after the
    // envelope's signature and envelope_hash, and before contentHash, which is over the record as stored
    const redaction = this.orgDeclared ? this.redaction.joined(this.orgDeclared(), ORG_FIELDS) : this.redaction;
    if (redaction.active) {
      const [storedEnvelope, storedDecision] = redaction.record(JSON.parse(envelopeJson), JSON.parse(decisionJson));
      envelopeJson = JSON.stringify(storedEnvelope);
      decisionJson = JSON.stringify(storedDecision);
    }

    // A declared path the envelope holds no value at is named in the record (row 163 (e)), and joins its hash
    const absent = redaction.absent(JSON.parse(envelopeJson));
    this.insert(eventId, timestamp, {
      org_id: envelope.org_id,
      environment: envelope.environment,
      action_id: envelope.action_id,
      action: envelope.action ?? null,
      agent_id: envelope.agent_id ?? null,
      policy_version: decision.policy_version,
      decision_type: decision.decision,
    }, JSON.parse(envelopeJson), JSON.parse(decisionJson), absent.length ? { redaction: { absent } } : {});
    return eventId;
  }

  /**
   * Write the result record of the action whose decision record is `decided` (as `lifecycle` reads it): a new record
   * under its org, environment and action_id, carrying its envelope, decision and further terms as stored, the
   * `execution_result`, and `review`, the review the result was read under when it is one (row 217), its hash over
   * every term it carries (event_format.md "The lifecycle", "The result record"). Mirrors audit.py `write_result`.
   *
   * @returns The record as read
   * @throws {AuditLogError} If the write fails
   */
  writeResult(
    decided: Record<string, any>,
    executionResult: Record<string, unknown>,
    review: UnreadReview | null = null
  ): Record<string, unknown> {
    // The decided record is stored history; supplied result/review still needs admission.
    auditNumbers(executionResult,['execution_result'],ResultNumberSchema);
    auditNumbers(review,['review']);
    const eventId = `evt_${crypto.randomUUID().replace(/-/g, '')}`;
    const carried: Record<string, unknown> = {
      ...Object.fromEntries(AUDIT_FURTHER.filter((m) => decided[m] !== undefined).map((m) => [m, decided[m]])),
      execution_result: { ...executionResult },
    };
    if (review !== null) carried.review = { ...review };
    const found = Object.fromEntries(
      ['org_id', 'environment', 'action_id', 'action', 'agent_id', 'policy_version', 'decision_type']
        .map((k) => [k, decided[k] ?? null])
    );
    // The record as its write stored it, read in the write's own transaction, never after its commit (event_format.md
    // "The Lifecycle", "One step")
    return this.db.transaction(() => {
      this.insert(eventId, new Date().toISOString(), found, decided.envelope, decided.decision, carried);
      return this.lifecycle(decided.org_id, decided.environment, decided.action_id).find((r) => r.event_id === eventId)!;
    })();
  }

  /**
   * Write one record: its content as stored, the fields read from it, and its hash over every term it carries. The
   * canonical serialisation (sync_engine.md §2.1): over the JSON values exactly as they are uploaded.
   */
  private insert(
    eventId: string,
    timestamp: string,
    found: Record<string, unknown>,
    envelope: unknown,
    decision: unknown,
    carried: Record<string, unknown>
  ): void {
    const row: Record<string, unknown> = {
      event_id: eventId,
      timestamp,
      ...found,
      envelope: JSON.stringify(envelope),
      decision: JSON.stringify(decision),
      ...Object.fromEntries(
        AUDIT_FURTHER.filter((m) => carried[m] != null).map((m) => [m, JSON.stringify(carried[m])]),
      ),
      content_hash: contentHash(eventId, envelope, decision, carried),
    };
    const columns = Object.keys(row);
    try {
      this.db
        .prepare(`INSERT INTO audit_log (${columns.join(', ')}) VALUES (${columns.map(() => '?').join(', ')})`)
        .run(...Object.values(row));
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
    return (stmt.all(org_id) as AuditRecord[]).map(asRead);
  }

  /**
   * The decision first recorded under (org, environment, idempotency_key) for an envelope whose timestamp is within
   * the dedup window of `at`, or null (row 143; the hosted service reads the same). No decision carrying `error` is a
   * first decision: ECP itself failed and the action was not evaluated, so its retry is (Error Handling, "Audit
   * requirement"; HTL-22 row 159, HTL-23 row 193). Each timestamp is the instant RFC 3339's grammar reads
   * (`@hiitl/core`'s date-time.ts); one the store cannot read throws, so the key is not known to be new.
   */
  firstDecisionUnderKey(
    org_id: string,
    environment: string,
    idempotency_key: string,
    at: string,
    window_seconds: number
  ): Decision | null {
    const called = readDateTime(at);
    const rows = this.db
      .prepare(
        `
      SELECT json_extract(envelope, '$.timestamp') AS written, decision FROM audit_log
      WHERE org_id = ? AND environment = ?
        AND json_extract(envelope, '$.idempotency_key') = ?
        AND json_extract(decision, '$.error') IS NULL
      ORDER BY rowid
    `
      )
      .all(org_id, environment, idempotency_key) as Array<{ written: unknown; decision: string }>;
    const first = rows.find(({ written }) => Math.abs(readDateTime(written) - called) <= window_seconds * 1000);
    return first ? (JSON.parse(first.decision) as Decision) : null;
  }

  /**
   * `step` run as the one call under (org, environment, idempotency_key) in this store: the dedup read and the record's
   * write are one step (HTL-29 row 160, ruled 2026-11-09; ecp_evaluate_spec.md §4). A synchronous step holds the key by
   * running to its end; a step that asks a sync route holds it until its decision settles, and a call under the same
   * key follows it. The holds are the process's own, shared by every client of this store in it.
   */
  underKey<T>(
    org_id: string,
    environment: string,
    idempotency_key: string,
    step: () => T | Promise<T>
  ): T | Promise<T> {
    const key = JSON.stringify([this.store, org_id, environment, idempotency_key]);
    const ahead = AuditLogger._tails.get(key);
    const result = ahead ? ahead.then(step) : step();
    if (result instanceof Promise) {
      const done = (): void => {
        if (AuditLogger._tails.get(key) === tail) AuditLogger._tails.delete(key);
      };
      const tail: Promise<void> = result.then(done, done);
      AuditLogger._tails.set(key, tail);
    }
    return result;
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

    return (stmt.all(action_id) as AuditRecord[]).map(asRead);
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
    return (stmt.all(decision_type) as AuditRecord[]).map(asRead);
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
    return row ? asRead(row as AuditRecord) : null;
  }

  /**
   * The records of one action in one org and environment, oldest first, as the lifecycle reads them: envelope and
   * decision parsed, each carrying its `event_type` (event_format.md "The lifecycle"; HTL-22 row 150). Mirrors
   * audit.py `lifecycle`.
   *
   * @throws {AuditLogError} On query failure
   */
  lifecycle(org_id: string, environment: string, action_id: string): Array<Record<string, unknown>> {
    try {
      const rows = this.db
        .prepare('SELECT * FROM audit_log WHERE org_id = ? AND environment = ? AND action_id = ? ORDER BY rowid')
        .all(org_id, environment, action_id) as Array<Record<string, unknown>>;
      return rows.map((row) => asRead(parsed(row)));
    } catch (e: any) {
      throw new AuditLogError(`Failed to read the lifecycle of ${action_id}: ${e.message}`);
    }
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

    // Recompute the hash over every term the record carries, read from the record itself (row 191)
    const further = Object.fromEntries(AUDIT_FURTHER.filter(m => record[m] != null).map(m => [m, record[m]]));
    return auditHashMatches(record.content_hash, record.event_id, JSON.parse(record.envelope), JSON.parse(record.decision), further);
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

  // ─── sync engine drain surface (Block 5e) ─────────────────────────────

  /**
   * Get unsynced audit records for upload to the hosted service.
   *
   * Returns records ordered by timestamp ASC (oldest first) so the
   * server receives them in chronological order — matches Python's
   * `get_unsynced` exactly. The `envelope` and `decision` columns
   * are stored as JSON strings; we parse them back into objects so
   * the sync client can re-serialize the batch.
   *
   * @param limit Maximum records to return (default 100)
   * @returns Array of audit records with parsed envelope + decision
   * @throws {AuditLogError} On query failure
   */
  getUnsynced(limit = 100): Array<Record<string, unknown>> {
    try {
      const stmt = this.db.prepare(`
        SELECT event_id, timestamp, org_id, environment, action_id,
               envelope, decision, policy_version, decision_type,
               action, agent_id, content_hash, ${AUDIT_FURTHER.join(', ')}
        FROM audit_log
        WHERE ${PENDING}
        ORDER BY timestamp ASC
        LIMIT ?
      `);
      const rows = stmt.all(limit) as Array<Record<string, unknown>>;
      // Match Python: best-effort parse, and each record carries its event_type into the upload.
      return rows.map((row) => asRead(parsed(row)));
    } catch (e: any) {
      throw new AuditLogError(`Failed to query unsynced audit records: ${e.message}`);
    }
  }

  /**
   * The unsynced audit records: [how many, their size in bytes (envelope and decision as stored)].
   * This backlog is the sync engine's audit buffer (sync_engine.md section 7). Mirrors audit.py
   * `unsynced_backlog`.
   *
   * @throws {AuditLogError} On query failure
   */
  unsyncedBacklog(): [number, number] {
    try {
      const row = this.db
        .prepare(
          `SELECT COUNT(*) AS n,
                  COALESCE(SUM(LENGTH(CAST(envelope AS BLOB)) + LENGTH(CAST(decision AS BLOB))), 0) AS bytes
           FROM audit_log WHERE ${PENDING}`
        )
        .get() as { n: number; bytes: number };
      return [Number(row.n), Number(row.bytes)];
    } catch (e: any) {
      throw new AuditLogError(`Failed to read the unsynced audit backlog: ${e.message}`);
    }
  }

  /**
   * Mark audit records as synced after successful upload.
   *
   * @param eventIds Event IDs to mark as synced
   * @returns Number of records updated
   * @throws {AuditLogError} On update failure
   */
  markSynced(eventIds: string[]): number {
    if (eventIds.length === 0) return 0;
    try {
      const placeholders = eventIds.map(() => '?').join(',');
      const stmt = this.db.prepare(
        `UPDATE audit_log SET synced = 1 WHERE event_id IN (${placeholders})`
      );
      const result = stmt.run(...eventIds);
      return Number(result.changes);
    } catch (e: any) {
      throw new AuditLogError(`Failed to mark audit records as synced: ${e.message}`);
    }
  }

  /**
   * Mark each record refused with the service's code, by event_id: a record refused for its own content is kept as
   * written and never sent again (sync_engine.md section 2.1, row 224). The mark is beside the record, as `synced` is;
   * its content and hash never change. Mirrors audit.py `mark_refused`.
   *
   * @returns Number of records marked
   * @throws {AuditLogError} On update failure
   */
  markRefused(refusals: Record<string, string>): number {
    const entries = Object.entries(refusals);
    if (entries.length === 0) return 0;
    try {
      const stmt = this.db.prepare('UPDATE audit_log SET refused = ? WHERE event_id = ?');
      return entries.reduce((marked, [eventId, code]) => marked + Number(stmt.run(code, eventId).changes), 0);
    } catch (e: any) {
      throw new AuditLogError(`Failed to mark audit records as refused: ${e.message}`);
    }
  }

  /**
   * The action_ids of the records not yet pushed (hosted mode's held results wait for their decision's record).
   * Mirrors audit.py `unsynced_action_ids`.
   *
   * @throws {AuditLogError} On query failure
   */
  unsyncedActionIds(): Set<string> {
    try {
      const rows = this.db.prepare(`SELECT DISTINCT action_id FROM audit_log WHERE ${PENDING}`).all() as Array<{
        action_id: string;
      }>;
      return new Set(rows.map((r) => r.action_id));
    } catch (e: any) {
      throw new AuditLogError(`Failed to read the unsynced audit records: ${e.message}`);
    }
  }

  /**
   * Hold a result the hosted service could not take, to be pushed before the hosted client's next call (row 200).
   *
   * @throws {AuditLogError} If the store cannot hold it
   */
  holdResult(actionId: string, executionResult: Record<string, unknown>): void {
    auditNumbers(executionResult,['execution_result'],ResultNumberSchema);
    try {
      this.db.prepare('INSERT INTO held_results (action_id, execution_result) VALUES (?, ?)')
        .run(actionId, JSON.stringify(executionResult));
    } catch (e: any) {
      throw new AuditLogError(`Failed to hold the result of ${actionId} in ${this.dbPath}: ${e.message}`);
    }
  }

  /**
   * The results held for the hosted service, oldest first. Mirrors audit.py `held_results`.
   *
   * @throws {AuditLogError} On query failure
   */
  heldResults(): Array<{ action_id: string; execution_result: Record<string, unknown> }> {
    try {
      const rows = this.db.prepare('SELECT action_id, execution_result FROM held_results ORDER BY rowid').all() as
        Array<{ action_id: string; execution_result: string }>;
      return rows.map((r) => ({ action_id: r.action_id, execution_result: JSON.parse(r.execution_result) }));
    } catch (e: any) {
      throw new AuditLogError(`Failed to read the held results: ${e.message}`);
    }
  }

  /**
   * Remove a held result once the service has answered it, taken or refused (the same result held twice goes
   * together: the same result again is the record already written).
   *
   * @throws {AuditLogError} If the delete fails
   */
  releaseResult(actionId: string, executionResult: Record<string, unknown>): void {
    try {
      this.db.prepare('DELETE FROM held_results WHERE action_id = ? AND execution_result = ?')
        .run(actionId, JSON.stringify(executionResult));
    } catch (e: any) {
      throw new AuditLogError(`Failed to release the held result of ${actionId}: ${e.message}`);
    }
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
