"""Audit logger - SQLite-based audit logging for local mode.

This module provides append-only audit logging to SQLite for tracking all
policy evaluation decisions in local/edge mode.

Design principles:
- Append-only: No UPDATE or DELETE operations
- Content integrity: SHA-256 hashing of records
- Query performance: Denormalized fields with indexes
- Timezone-aware: ISO 8601 timestamps with UTC
- Thread-safe: SQLite handles concurrent writes via locking

Security tier 1 features (per CLAUDE.md):
- Content hashing for integrity verification
- Immutable records (append-only)
- Denormalized data for audit queries

Example:
    >>> logger = AuditLogger("./hiitl_audit.db")
    >>> event_id = logger.write(envelope, decision)
    >>> # Record is now in database with integrity hash
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

from hiitl.core.types import Decision, Envelope
from hiitl.sdk.exceptions import AuditLogError


class AuditLogger:
    """SQLite-based audit logger for policy evaluation decisions.

    This logger maintains an append-only audit trail of all policy evaluations
    in local mode. Each record includes:
    - Full envelope and decision (as JSON)
    - Denormalized fields for efficient queries
    - Content hash (SHA-256) for integrity verification
    - Timestamps in ISO 8601 format (UTC)

    The database schema is optimized for common audit queries:
    - Query by org_id + timestamp
    - Query by action_id (idempotency)
    - Query by decision_type (BLOCK, ALLOW, etc.)

    Attributes:
        db_path: Path to SQLite database file
        _conn: SQLite connection (lazy-initialized)
    """

    def __init__(self, db_path: str):
        """Initialize audit logger.

        Args:
            db_path: Path to SQLite database file (will be created if missing)

        The database is created lazily on first write() call.
        Parent directories are created automatically.
        """
        self.db_path = Path(db_path)
        self._conn = None
        self._init_db()

    def _init_db(self):
        """Create database schema if it doesn't exist.

        Creates:
        - audit_log table with all required fields
        - Indexes for common query patterns

        This method is idempotent - safe to call multiple times.
        """
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Connect to database (creates file if missing)
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Create audit_log table
            cursor.execute("""
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
                    content_hash TEXT NOT NULL,
                    synced INTEGER DEFAULT 0
                )
            """)

            # Migration: add synced column to existing databases
            try:
                cursor.execute("ALTER TABLE audit_log ADD COLUMN synced INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_org_timestamp
                ON audit_log(org_id, timestamp DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_id
                ON audit_log(action_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_type
                ON audit_log(decision_type, timestamp DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_synced
                ON audit_log(synced, timestamp ASC)
            """)

            conn.commit()
            conn.close()

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to initialize audit database {self.db_path}: {e}\n\n"
                "Check that:\n"
                "1. The directory exists and is writable\n"
                "2. You have permissions to create/write the database file\n"
                "3. Disk space is available"
            ) from e

    def write(
        self,
        envelope: Union[Envelope, dict],
        decision: Union[Decision, dict]
    ) -> str:
        """Write audit record to database.

        This method:
        1. Generates unique event_id
        2. Serializes envelope and decision to JSON
        3. Computes SHA-256 content hash
        4. Writes record with denormalized fields
        5. Returns event_id for reference

        Args:
            envelope: Execution envelope (Envelope model or dict)
            decision: Policy decision (Decision model or dict)

        Returns:
            event_id: Unique event identifier (evt_<32-char-hex>)

        Raises:
            AuditLogError: If database write fails
        """
        # Generate unique event ID
        event_id = f"evt_{uuid4().hex}"

        # Get current timestamp in ISO 8601 format (UTC)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Serialize to JSON (handles Pydantic models correctly)
        if hasattr(envelope, 'model_dump_json'):
            # Pydantic model - use model_dump_json() which handles datetime, etc.
            envelope_json = envelope.model_dump_json(exclude_none=False)
        else:
            # Dict - serialize with json.dumps
            envelope_json = json.dumps(envelope, sort_keys=True)

        if hasattr(decision, 'model_dump_json'):
            # Pydantic model
            decision_json = decision.model_dump_json(exclude_none=False)
        else:
            # Dict
            decision_json = json.dumps(decision, sort_keys=True)

        # Get dict representation for extracting denormalized fields
        if hasattr(envelope, 'model_dump'):
            envelope_dict = envelope.model_dump()
        else:
            envelope_dict = envelope

        if hasattr(decision, 'model_dump'):
            decision_dict = decision.model_dump()
        else:
            decision_dict = decision

        # Compute content hash (SHA-256)
        content = f"{event_id}:{envelope_json}:{decision_json}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Extract denormalized fields from envelope and decision
        org_id = envelope_dict.get('org_id', '')
        environment = envelope_dict.get('environment', '')
        action_id = envelope_dict.get('action_id', '')
        tool_name = envelope_dict.get('action') or envelope_dict.get('tool_name')
        agent_id = envelope_dict.get('agent_id')

        policy_version = decision_dict.get('policy_version', '')
        decision_type = decision_dict.get('decision', '')

        # Write to database
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO audit_log (
                    event_id, timestamp, org_id, environment, action_id,
                    envelope, decision, policy_version, decision_type,
                    tool_name, agent_id, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, timestamp, org_id, environment, action_id,
                envelope_json, decision_json, policy_version, decision_type,
                tool_name, agent_id, content_hash
            ))

            conn.commit()
            conn.close()

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to write audit record to {self.db_path}: {e}\n\n"
                "This could indicate:\n"
                "1. Database is locked (another process writing)\n"
                "2. Disk is full\n"
                "3. Database file permissions are incorrect\n"
                "4. Database file is corrupted"
            ) from e

        return event_id

    def query_by_org(
        self,
        org_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """Query audit records by organization ID.

        Returns most recent records first (timestamp DESC).

        Args:
            org_id: Organization ID to filter by
            limit: Maximum number of records to return (default: 100)
            offset: Number of records to skip (for pagination)

        Returns:
            List of audit records as dicts

        Raises:
            AuditLogError: If query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row  # Return rows as dicts
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM audit_log
                WHERE org_id = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (org_id, limit, offset))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to query audit log: {e}"
            ) from e

    def query_by_action_id(self, action_id: str) -> Optional[dict]:
        """Query audit record by action_id (for idempotency checks).

        Args:
            action_id: Action ID to find

        Returns:
            Audit record as dict, or None if not found

        Raises:
            AuditLogError: If query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM audit_log
                WHERE action_id = ?
                LIMIT 1
            """, (action_id,))

            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to query audit log by action_id: {e}"
            ) from e

    def verify_integrity(self, event_id: str) -> bool:
        """Verify integrity of audit record by recomputing content hash.

        Args:
            event_id: Event ID to verify

        Returns:
            True if hash matches (record is intact), False if tampered

        Raises:
            AuditLogError: If query fails or record not found
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT event_id, envelope, decision, content_hash
                FROM audit_log
                WHERE event_id = ?
            """, (event_id,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                raise AuditLogError(f"Event {event_id} not found in audit log")

            # Recompute hash
            content = f"{row['event_id']}:{row['envelope']}:{row['decision']}"
            computed_hash = hashlib.sha256(content.encode()).hexdigest()

            # Compare with stored hash
            return computed_hash == row['content_hash']

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to verify integrity of event {event_id}: {e}"
            ) from e

    def get_unsynced(self, limit: int = 100) -> list[dict]:
        """Get unsynced audit records for upload to hosted service.

        Returns records ordered by timestamp ASC (oldest first) so the
        server receives records in chronological order.

        Args:
            limit: Maximum number of records to return (default: 100)

        Returns:
            List of audit records as dicts (with parsed envelope/decision JSON)

        Raises:
            AuditLogError: If query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT event_id, timestamp, org_id, environment, action_id,
                       envelope, decision, policy_version, decision_type,
                       tool_name, agent_id, content_hash
                FROM audit_log
                WHERE synced = 0
                ORDER BY timestamp ASC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            results = []
            for row in rows:
                record = dict(row)
                # Parse JSON strings back to dicts for upload
                try:
                    record["envelope"] = json.loads(record["envelope"])
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    record["decision"] = json.loads(record["decision"])
                except (json.JSONDecodeError, TypeError):
                    pass
                results.append(record)

            return results

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to query unsynced audit records: {e}"
            ) from e

    def mark_synced(self, event_ids: list[str]) -> int:
        """Mark audit records as synced after successful upload.

        Args:
            event_ids: List of event IDs to mark as synced

        Returns:
            Number of records updated

        Raises:
            AuditLogError: If update fails
        """
        if not event_ids:
            return 0

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            placeholders = ",".join("?" for _ in event_ids)
            cursor.execute(
                f"UPDATE audit_log SET synced = 1 WHERE event_id IN ({placeholders})",
                event_ids,
            )

            updated = cursor.rowcount
            conn.commit()
            conn.close()

            return updated

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to mark audit records as synced: {e}"
            ) from e

    def count_unsynced(self) -> int:
        """Count unsynced audit records.

        Returns:
            Number of records not yet uploaded to server
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_log WHERE synced = 0")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except sqlite3.Error:
            return -1

    def close(self):
        """Close database connection (if open).

        This is optional - connections are closed automatically on write/query.
        """
        if self._conn:
            self._conn.close()
            self._conn = None
