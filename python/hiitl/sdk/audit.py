"""Audit logger - SQLite-based audit logging for local mode.

This module provides append-only audit logging to SQLite for tracking all
policy evaluation decisions in local/edge mode.

Design principles:
- Append-only: a record's content, and each member read from it, never changes. The one write after the
  insert is a mark beside it (`synced`, `refused`), outside its hash (event_format.md "Append-Only
  Requirement"). `held_results` holds no record: a held result is removed once the service answers it
- Content integrity: SHA-256 hashing of records
- Query performance: Denormalized fields with indexes
- Timezone-aware: ISO 8601 timestamps with UTC
- Thread-safe: SQLite handles concurrent writes via locking

Security tier 1 features:
- Content hashing for integrity verification
- Immutable records (append-only)
- Denormalized data for audit queries

Example:
    >>> logger = AuditLogger("./hiitl_audit.db")
    >>> event_id = logger.write(envelope, decision)
    >>> # Record is now in database with integrity hash
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union
from uuid import uuid4

from hiitl.core import date_time
from hiitl.core.input_types import model_shape
from hiitl.core.input_declarations import policy_shape
from hiitl.core.canonical import AUDIT_FURTHER, audit_content_hash, audit_hash_matches
from hiitl.core.numeric_domain import validate_numeric_domain, admitted_numbers, NumericDomainError
from hiitl.core.lifecycle import RECORD_REFUSALS, event_type, RESULT_NUMBER_SHAPE
from hiitl.core.redaction import ORG_FIELDS, Redaction
from hiitl.core.types import ENVELOPE_RENAMED, Decision, Envelope
from hiitl.sdk.exceptions import AuditLogError
from hiitl.sdk.hash_key import MEMORY, store_key

# A record still to send: not synced, and not refused for its own content (sync_engine.md §2.1, row 224). Every read of
# the records still to send reads this one predicate.
_PENDING = "synced = 0 AND refused IS NULL"


def _admit_audit(value, path, *, shape=None):
    try:
        validate_numeric_domain(value, path, shape=shape)
    except NumericDomainError as error:
        raise AuditLogError(f"New audit record refused: {error}") from error


def envelope_record(envelope: Envelope) -> dict:
    """The envelope as the SDK records, signs and sends it: its JSON values, an unset optional field absent (a
    caller's own null inside parameters or target is kept). One form for all three, so the record alone re-derives
    the signature and envelope_hash (row 127; hiitl.core.canonical.envelope_signed_form)."""
    validate_numeric_domain(envelope)
    return envelope.model_dump(mode="json", exclude_none=True)


def _as_read(record: dict) -> dict:
    """A record as it is read and uploaded: each further member it carries parsed, one it does not carry absent (its
    column null), and carrying its `event_type`, computed from its decision and its `execution_result`, never stored
    in a column (event_format.md "Event types" and "Where it is held"; HTL-22 row 150)."""
    for member in AUDIT_FURTHER:
        value = record.pop(member, None)
        if value is not None:
            record[member] = json.loads(value) if isinstance(value, str) else value
    record["event_type"] = event_type(record["decision_type"], record.get("execution_result"))
    return record


def content_hash(event_id: str, envelope: Any, decision: Any, carried: Mapping[str, Any]) -> str:
    """The record's hash over its content as stored, each further member it carries a term (row 191). The members are
    core's `AUDIT_FURTHER`, the one copy (event_format.md `content_hash`)."""
    return audit_content_hash(event_id, envelope, decision,
                              **{m: carried[m] for m in AUDIT_FURTHER if carried.get(m) is not None})


def _parsed(record: dict) -> dict:
    """The record with its envelope and decision JSON parsed back to objects (best-effort: left as stored on
    failure)."""
    for column in ("envelope", "decision"):
        try:
            record[column] = json.loads(record[column])
        except (json.JSONDecodeError, TypeError):
            pass
    return record


def settle_upload(store, records: Sequence[Mapping], errors: Sequence[Mapping], log: logging.Logger) -> bool:
    """An upload's answer, settled in the local store (sync_engine.md §2.1; row 224, ruled 2026-11-08). A record no
    error names is marked synced. A record refused for its own content (core's `RECORD_REFUSALS`) is final: it stays in
    the store as written, marked refused with the code, logged at error, and is not sent again. Any other error leaves
    its record unsynced, logged at warning; a code the SDK does not know is retried, never read as final. The sync
    engine and the hosted client both settle here, each logging to its own `log`.

    Returns:
        Whether the drain goes on: False when any error is retried
    """
    retried = {e.get("event_id") for e in errors if e.get("code") not in RECORD_REFUSALS}
    sent = [r["event_id"] for r in records]
    refused = {e.get("event_id"): e.get("code") for e in errors if e.get("code") in RECORD_REFUSALS
               and e.get("event_id") in sent and e.get("event_id") not in retried}
    synced = [e for e in sent if e not in refused and e not in retried]
    if synced:
        store.mark_synced(synced)
    if refused:
        store.mark_refused(refused)
    for err in errors:
        if err.get("code") in RECORD_REFUSALS:
            log.error("Audit record %s refused for its own content: [%s] %s. It is kept in the local store, marked "
                      "refused, and not sent again (sync_engine.md §2.1).", err.get("event_id", "?"), err.get("code"),
                      err.get("message", "?"))
        else:
            log.warning("Audit record %s was not stored: [%s] %s. It stays unsynced and is sent again.",
                        err.get("event_id", "?"), err.get("code", "?"), err.get("message", "?"))
    return not retried


def _file_identity(path: Path) -> tuple[int, int]:
    """The file at `path`, whatever name reaches it: its device and inode, which POSIX names its identity
    (`<sys/stat.h>`, "The st_ino and st_dev fields taken together uniquely identify the file within the system")."""
    st = os.stat(path)
    return st.st_dev, st.st_ino


def _admitted_envelope_record(envelope):
    with admitted_numbers():
        return envelope_record(envelope)


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

    # Each held key's lock and the calls holding or waiting on it, by store and key (HTL-29 row 160)
    _holds: dict = {}
    _holds_guard = threading.Lock()

    def __init__(self, db_path: str, redaction: Optional[Redaction] = None,
                 org_declared: Optional[Callable[[], Iterable[str]]] = None):
        """Initialize audit logger.

        Args:
            db_path: Path to SQLite database file (will be created if missing)
            redaction: What the record holds in place of each declared field (event_format.md §Redaction)
            org_declared: The org's declared fields as last pulled (hybrid mode). Each write redacts the union of
                them and `redaction`'s (row 163(a)).

        The database is created lazily on first write() call.
        Parent directories are created automatically.
        """
        self.db_path = Path(db_path)
        self._conn = None
        self._redaction = redaction or Redaction()
        self._org_declared = org_declared
        self._init_db()
        # The store is the file it opened, whatever name reached it (HTL-29 review, condition 3)
        self._store = (MEMORY, uuid4().hex) if str(db_path) == MEMORY else _file_identity(self.db_path)
        if self._redaction.recorded_parameters is not None and self._redaction.key is None:
            # The value hash's key lives beside the store's file, made at its first start (row 163(c))
            try:
                self._redaction = self._redaction.keyed(store_key(self.db_path))
            except (OSError, ValueError) as e:
                raise AuditLogError(f"The audit store {self.db_path} has no usable value-hash key: {e}") from e

    def _init_db(self):
        """Create database schema if it doesn't exist.

        Creates:
        - audit_log table with all required fields
        - Indexes for common query patterns

        This method is idempotent - safe to call multiple times.
        """
        try:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Connect to database (creates file if missing)
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Create audit_log table: a column for each further member core names, the one copy
            members = "".join(f",\n                    {m} TEXT" for m in AUDIT_FURTHER)
            cursor.execute(f"""
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
                    refused TEXT{members}
                )
            """)

            # Migration: the record projects the envelope's members under the envelope's names, so a store written
            # before record format 2.0 renames each column the envelope schema renamed; each record keeps its value,
            # its hash (the member is outside it) and its synced mark (event_format.md 2.0, "From 1.x"; row 230)
            held = {row[1] for row in cursor.execute("PRAGMA table_info(audit_log)")}
            for old, new in ENVELOPE_RENAMED.items():
                if old in held:
                    cursor.execute(f"ALTER TABLE audit_log RENAME COLUMN {old} TO {new}")

            # Migration: a store written before a column existed gains it (null on the records it holds: none of
            # them carries a further member, so each hashes as it did; their synced marks stand, row 224)
            for column in ("synced INTEGER DEFAULT 0", "refused TEXT", *(f"{m} TEXT" for m in AUDIT_FURTHER)):
                try:
                    cursor.execute(f"ALTER TABLE audit_log ADD COLUMN {column}")
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

            # A repeated idempotency key is found by the key the recorded envelope carries (row 143)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_idempotency_key
                ON audit_log(org_id, environment, json_extract(envelope, '$.idempotency_key'))
            """)

            # A result the hosted service could not take, held until the hosted client pushes it (event_format.md
            # "The Lifecycle"; row 200). It is no record: the service writes the result record when it takes it.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS held_results (
                    action_id TEXT NOT NULL,
                    execution_result TEXT NOT NULL
                )
            """)

            conn.commit()
            conn.close()

        except (sqlite3.Error, OSError) as e:
            raise AuditLogError(
                f"Failed to initialize audit database {self.db_path}: {e}\n\n"
                "Check that:\n"
                "1. The directory exists and is writable\n"
                "2. You have permissions to create/write the database file\n"
                "3. Disk space is available"
            ) from e

    def _write_admitted(self, envelope, decision):
        """The SDK's already admitted envelope and produced Decision, in this call."""
        with admitted_numbers():
            return self.write(envelope, decision)

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
        _admit_audit(envelope, ('envelope',), shape=model_shape(Envelope))
        _admit_audit(decision, ('decision',), shape=policy_shape(Decision, Envelope))
        # Generate unique event ID
        event_id = f"evt_{uuid4().hex}"

        # Get current timestamp in ISO 8601 format (UTC)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Serialize to JSON (handles Pydantic models correctly)
        if hasattr(envelope, 'model_dump_json'):
            # Pydantic model - the form the SDK signed (envelope_record)
            envelope_json = json.dumps(envelope_record(envelope))
        else:
            # Dict - serialize with json.dumps
            envelope_json = json.dumps(envelope, sort_keys=True)

        if hasattr(decision, 'model_dump_json'):
            # Pydantic model
            decision_json = decision.model_dump_json(exclude_none=False)
        else:
            # Dict
            decision_json = json.dumps(decision, sort_keys=True)

        # The record as stored (event_format.md §Redaction, row 139): each declared field's value replaced, after the
        # envelope's signature and envelope_hash, and before content_hash, which is over the record as stored
        redaction = self.declaration()
        if redaction.active:
            stored_envelope, stored_decision = redaction.record(json.loads(envelope_json),
                                                                      json.loads(decision_json))
            envelope_json, decision_json = json.dumps(stored_envelope), json.dumps(stored_decision)

        # Get dict representation for extracting denormalized fields
        if hasattr(envelope, 'model_dump'):
            envelope_dict = envelope.model_dump()
        else:
            envelope_dict = envelope

        if hasattr(decision, 'model_dump'):
            decision_dict = decision.model_dump()
        else:
            decision_dict = decision

        # A declared path the envelope holds no value at is named in the record (row 163 (e)), and joins its hash
        absent = redaction.absent(json.loads(envelope_json))
        carried = {"redaction": {"absent": absent}} if absent else {}

        # Extract denormalized fields from envelope and decision
        self._insert(event_id, timestamp, {
            "org_id": envelope_dict.get('org_id', ''),
            "environment": envelope_dict.get('environment', ''),
            "action_id": envelope_dict.get('action_id', ''),
            "action": envelope_dict.get('action'),
            "agent_id": envelope_dict.get('agent_id'),
            "policy_version": decision_dict.get('policy_version', ''),
            "decision_type": decision_dict.get('decision', ''),
        }, json.loads(envelope_json), json.loads(decision_json), carried)
        return event_id

    def declaration(self) -> Redaction:
        """The declaration the store applies at a write: its own, joined to the org's as last pulled (row 163(a))."""
        return self._redaction if self._org_declared is None else self._redaction.joined(
            self._org_declared(), source=ORG_FIELDS)

    def write_result(self, decided: Mapping[str, Any], execution_result: Mapping[str, Any],
                     review: Optional[Mapping[str, Any]] = None) -> dict:
        """Write the result record of the action whose decision record is `decided` (as `lifecycle` reads it): a new
        record under its org, environment and action_id, carrying its envelope, decision and further terms as stored,
        the `execution_result`, and `review`, the review the result was read under when it is one (row 217), its hash
        over every term it carries (event_format.md "The lifecycle", "The result record"). Returns the record as read.

        Raises:
            AuditLogError: If the write fails
        """
        # The decided record is stored history; only the supplied result/review is new.
        _admit_audit(execution_result, ('execution_result',), shape=RESULT_NUMBER_SHAPE)
        _admit_audit(review, ('review',))
        event_id = f"evt_{uuid4().hex}"
        carried = {**{m: decided[m] for m in AUDIT_FURTHER if m in decided}, "execution_result": dict(execution_result)}
        if review is not None:
            carried["review"] = dict(review)
        return _as_read(_parsed(self._insert(
            event_id, datetime.now(timezone.utc).isoformat(),
            {k: decided[k] for k in ("org_id", "environment", "action_id", "action", "agent_id", "policy_version",
                                     "decision_type")},
            decided["envelope"], decided["decision"], carried, read_back=True)))

    def _insert(self, event_id: str, timestamp: str, found: Mapping[str, Any], envelope: Any, decision: Any,
                carried: Mapping[str, Any], *, read_back: bool = False) -> Optional[dict]:
        """Write one record: its content as stored, the fields read from it, and its hash over every term it carries.
        The canonical serialisation (sync_engine.md §2.1): over the JSON values exactly as they are uploaded. With
        `read_back`, returns the row as the write stored it, read in the write's own transaction, never after its
        commit (event_format.md "The Lifecycle", "One step")."""
        row = {"event_id": event_id, "timestamp": timestamp, **found,
               "envelope": json.dumps(envelope), "decision": json.dumps(decision),
               **{m: json.dumps(carried[m]) for m in AUDIT_FURTHER if carried.get(m) is not None},
               "content_hash": content_hash(event_id, envelope, decision, carried)}
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute(f"INSERT INTO audit_log ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                           tuple(row.values()))
            stored = None
            if read_back:
                cursor.execute("SELECT * FROM audit_log WHERE event_id = ?", (event_id,))
                stored = dict(zip((c[0] for c in cursor.description), cursor.fetchone()))

            conn.commit()
            conn.close()
            return stored

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to write audit record to {self.db_path}: {e}\n\n"
                "This could indicate:\n"
                "1. Database is locked (another process writing)\n"
                "2. Disk is full\n"
                "3. Database file permissions are incorrect\n"
                "4. Database file is corrupted"
            ) from e

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

            return [_as_read(dict(row)) for row in rows]

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

            return _as_read(dict(row)) if row else None

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to query audit log by action_id: {e}"
            ) from e

    def lifecycle(self, org_id: str, environment: str, action_id: str) -> list[dict]:
        """The action's records under (org, environment), oldest first, each parsed and carrying its event_type: its
        lifecycle as this store holds it (Principle 4; event_format.md "The lifecycle"; HTL-22 row 150).

        Raises:
            AuditLogError: If the query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM audit_log
                WHERE org_id = ? AND environment = ? AND action_id = ?
                ORDER BY rowid
            """, (org_id, environment, action_id)).fetchall()
            conn.close()
            return [_as_read(_parsed(dict(row))) for row in rows]

        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to read the lifecycle of {action_id}: {e}") from e

    @contextmanager
    def key_held(self, org_id: str, environment: str, idempotency_key: str):
        """Hold (org, environment, idempotency_key) in this store for the block: the dedup read and the record's write
        are one step (HTL-29 row 160, ruled 2026-11-09; ecp_evaluate_spec.md §4). A call under the same key waits; a
        call under another key does not. The holds are the process's own, shared by every client of this store in it."""
        key = (self._store, org_id, environment, idempotency_key)
        with self._held(key):
            yield

    @contextmanager
    def action_held(self, org_id: str, environment: str, action_id: str):
        """Hold the action in this store for the block: the read of its records and its result's write are one step,
        so a result is recorded once (event_format.md "The Lifecycle", "One step"; HTL-29 review, condition 4). The
        hold is the one an idempotency key takes, under the action's own key."""
        with self._held((self._store, "action", org_id, environment, action_id)):
            yield

    @staticmethod
    @contextmanager
    def _held(key: tuple):
        with AuditLogger._holds_guard:
            held = AuditLogger._holds.setdefault(key, [threading.Lock(), 0])
            held[1] += 1
        try:
            with held[0]:
                yield
        finally:
            with AuditLogger._holds_guard:
                held[1] -= 1
                if held[1] == 0:
                    del AuditLogger._holds[key]

    def first_decision_under_key(self, org_id: str, environment: str, idempotency_key: str, at: str,
                                 window_seconds: int) -> Optional[dict]:
        """The decision first recorded under (org, environment, idempotency_key) for an envelope whose timestamp is
        within the dedup window of `at`, or None (row 143; the hosted service reads the same). No decision carrying
        `error` is a first decision: ECP itself failed and the action was not evaluated, so its retry is (Error
        Handling, "Audit requirement"; HTL-22 row 159, HTL-23 row 193). Each timestamp is the instant RFC 3339's
        grammar reads (hiitl.core.date_time); one the store cannot read raises, so the key is not known to be new."""
        called = date_time.read(at)
        try:
            conn = sqlite3.connect(str(self.db_path))
            rows = conn.execute("""
                SELECT json_extract(envelope, '$.timestamp'), decision FROM audit_log
                WHERE org_id = ? AND environment = ?
                  AND json_extract(envelope, '$.idempotency_key') = ?
                  AND json_extract(decision, '$.error') IS NULL
                ORDER BY rowid
            """, (org_id, environment, idempotency_key)).fetchall()
            conn.close()
            return next((json.loads(decision) for written, decision in rows
                         if abs((date_time.read(written) - called).total_seconds()) <= window_seconds), None)

        except sqlite3.Error as e:
            raise AuditLogError(
                f"Failed to query audit log by idempotency_key: {e}"
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

            cursor.execute(f"""
                SELECT event_id, envelope, decision, content_hash, {", ".join(AUDIT_FURTHER)}
                FROM audit_log
                WHERE event_id = ?
            """, (event_id,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                raise AuditLogError(f"Event {event_id} not found in audit log")

            # Recompute the hash over every term the record carries, read from the record itself (row 191)
            carried = {m: json.loads(row[m]) for m in AUDIT_FURTHER if row[m] is not None}
            return audit_hash_matches(row['content_hash'], row['event_id'], json.loads(row['envelope']),
                                      json.loads(row['decision']), **carried)

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

            cursor.execute(f"""
                SELECT event_id, timestamp, org_id, environment, action_id,
                       envelope, decision, policy_version, decision_type,
                       action, agent_id, content_hash, {", ".join(AUDIT_FURTHER)}
                FROM audit_log
                WHERE {_PENDING}
                ORDER BY timestamp ASC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            # Parsed back to dicts for upload, each carrying its event_type
            return [_as_read(_parsed(dict(row))) for row in rows]

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

    def mark_refused(self, refusals: Mapping[str, str]) -> int:
        """Mark each record refused with the service's code, by event_id: a record refused for its own content is
        kept as written and never sent again (sync_engine.md §2.1, row 224). The mark is beside the record, as
        `synced` is; its content and hash never change.

        Returns:
            Number of records marked

        Raises:
            AuditLogError: If the update fails
        """
        if not refusals:
            return 0
        try:
            conn = sqlite3.connect(str(self.db_path))
            marked = sum(conn.execute("UPDATE audit_log SET refused = ? WHERE event_id = ?", (code, event_id)).rowcount
                         for event_id, code in refusals.items())
            conn.commit()
            conn.close()
            return marked
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to mark audit records as refused: {e}") from e

    def unsynced_action_ids(self) -> set[str]:
        """The action_ids of the records not yet pushed (hosted mode's held results wait for their decision's record).

        Raises:
            AuditLogError: If the query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            held = {row[0] for row in conn.execute(f"SELECT DISTINCT action_id FROM audit_log WHERE {_PENDING}")}
            conn.close()
            return held
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to read the unsynced audit records: {e}") from e

    def hold_result(self, action_id: str, execution_result: Mapping[str, Any]) -> None:
        """Hold a result the hosted service could not take, to be pushed before the hosted client's next call (row 200).

        Raises:
            AuditLogError: If the store cannot hold it
        """
        _admit_audit(execution_result, ('execution_result',), shape=RESULT_NUMBER_SHAPE)
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("INSERT INTO held_results (action_id, execution_result) VALUES (?, ?)",
                         (action_id, json.dumps(dict(execution_result))))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to hold the result of {action_id} in {self.db_path}: {e}") from e

    def held_results(self) -> list[dict]:
        """The results held for the hosted service, oldest first, each `{action_id, execution_result}`.

        Raises:
            AuditLogError: If the query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            rows = conn.execute("SELECT action_id, execution_result FROM held_results ORDER BY rowid").fetchall()
            conn.close()
            return [{"action_id": a, "execution_result": json.loads(r)} for a, r in rows]
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to read the held results: {e}") from e

    def release_result(self, action_id: str, execution_result: Mapping[str, Any]) -> None:
        """Remove a held result once the service has answered it, taken or refused (the same result held twice goes
        together: the same result again is the record already written).

        Raises:
            AuditLogError: If the delete fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("DELETE FROM held_results WHERE action_id = ? AND execution_result = ?",
                         (action_id, json.dumps(dict(execution_result))))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to release the held result of {action_id}: {e}") from e

    def unsynced_backlog(self) -> tuple[int, int]:
        """The unsynced audit records: how many, and their size in bytes (envelope and decision as stored).

        This backlog is the sync engine's audit buffer (sync_engine.md section 7). It is on disk, so no
        record is dropped while sync is down, and the engine reads BUFFER_FULL from it.

        Raises:
            AuditLogError: If the query fails
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(envelope AS BLOB)) + LENGTH(CAST(decision AS BLOB))), 0) "
                f"FROM audit_log WHERE {_PENDING}"
            )
            count, size = cursor.fetchone()
            conn.close()
            return count, size
        except sqlite3.Error as e:
            raise AuditLogError(f"Failed to read the unsynced audit backlog: {e}") from e

    def count_unsynced(self) -> int:
        """Count unsynced audit records.

        Returns:
            Number of records not yet uploaded to server
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM audit_log WHERE {_PENDING}")
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
