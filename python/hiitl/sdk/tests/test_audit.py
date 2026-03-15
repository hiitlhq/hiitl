"""Tests for AuditLogger."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from hiitl.core.types import Decision, DecisionType, Envelope, Timing
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.exceptions import AuditLogError


class TestAuditLoggerInitialization:
    """Test AuditLogger database initialization."""

    def test_creates_database_file(self, tmp_path):
        """AuditLogger should create database file if it doesn't exist."""
        db_path = tmp_path / "test_audit.db"
        assert not db_path.exists()

        logger = AuditLogger(str(db_path))

        assert db_path.exists()
        assert db_path.is_file()

    def test_creates_parent_directories(self, tmp_path):
        """AuditLogger should create parent directories if they don't exist."""
        db_path = tmp_path / "nested" / "directories" / "audit.db"
        assert not db_path.parent.exists()

        logger = AuditLogger(str(db_path))

        assert db_path.parent.exists()
        assert db_path.exists()

    def test_creates_schema(self, tmp_path):
        """AuditLogger should create audit_log table and indexes."""
        db_path = tmp_path / "test_audit.db"
        logger = AuditLogger(str(db_path))

        # Check table exists
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='audit_log'
        """)
        assert cursor.fetchone() is not None

        # Check indexes exist
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name IN (
                'idx_org_timestamp', 'idx_action_id', 'idx_decision_type'
            )
        """)
        indexes = cursor.fetchall()
        assert len(indexes) == 3

        conn.close()

    def test_idempotent_initialization(self, tmp_path):
        """Creating multiple AuditLogger instances should be safe."""
        db_path = tmp_path / "test_audit.db"

        # Create first logger
        logger1 = AuditLogger(str(db_path))

        # Create second logger (should not fail)
        logger2 = AuditLogger(str(db_path))

        # Both should work
        assert db_path.exists()


class TestAuditLoggerWrite:
    """Test AuditLogger write() method."""

    @pytest.fixture
    def sample_envelope(self):
        """Create sample envelope for testing."""
        return Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={"amount": 500},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )

    @pytest.fixture
    def sample_decision(self):
        """Create sample decision for testing."""
        return Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

    def test_write_returns_event_id(self, tmp_path, sample_envelope, sample_decision):
        """write() should return event_id."""
        logger = AuditLogger(tmp_path / "audit.db")
        event_id = logger.write(sample_envelope, sample_decision)

        assert event_id.startswith("evt_")
        assert len(event_id) == 36  # "evt_" + 32 hex chars

    def test_write_creates_record(self, tmp_path, sample_envelope, sample_decision):
        """write() should create record in database."""
        logger = AuditLogger(tmp_path / "audit.db")
        event_id = logger.write(sample_envelope, sample_decision)

        # Query database directly
        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM audit_log WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row['event_id'] == event_id
        assert row['org_id'] == "org_test000000000000"
        assert row['environment'] == "dev"
        assert row['action_id'] == "act_test00000000000000000"
        assert row['tool_name'] == "test_tool"
        assert row['agent_id'] == "test-agent"
        assert row['policy_version'] == "1.0.0"
        assert row['decision_type'] == "ALLOW"

    def test_write_stores_json(self, tmp_path, sample_envelope, sample_decision):
        """write() should store envelope and decision as JSON."""
        logger = AuditLogger(tmp_path / "audit.db")
        event_id = logger.write(sample_envelope, sample_decision)

        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT envelope, decision FROM audit_log WHERE event_id = ?",
            (event_id,)
        )
        row = cursor.fetchone()
        conn.close()

        # Should be valid JSON
        envelope_dict = json.loads(row['envelope'])
        decision_dict = json.loads(row['decision'])

        assert envelope_dict['org_id'] == "org_test000000000000"
        assert decision_dict['decision'] == "ALLOW"

    def test_write_computes_content_hash(self, tmp_path, sample_envelope, sample_decision):
        """write() should compute SHA-256 content hash."""
        logger = AuditLogger(tmp_path / "audit.db")
        event_id = logger.write(sample_envelope, sample_decision)

        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT event_id, envelope, decision, content_hash FROM audit_log WHERE event_id = ?",
            (event_id,)
        )
        row = cursor.fetchone()
        conn.close()

        # Recompute hash
        content = f"{row['event_id']}:{row['envelope']}:{row['decision']}"
        expected_hash = hashlib.sha256(content.encode()).hexdigest()

        assert row['content_hash'] == expected_hash
        assert len(row['content_hash']) == 64  # SHA-256 is 64 hex chars

    def test_write_includes_timestamp(self, tmp_path, sample_envelope, sample_decision):
        """write() should include ISO 8601 timestamp."""
        logger = AuditLogger(tmp_path / "audit.db")
        event_id = logger.write(sample_envelope, sample_decision)

        conn = sqlite3.connect(tmp_path / "audit.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT timestamp FROM audit_log WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        # Should be valid ISO 8601 format
        timestamp_str = row['timestamp']
        parsed = datetime.fromisoformat(timestamp_str)

        # Should be recent (within last 10 seconds)
        from datetime import timezone
        now = datetime.now(timezone.utc)
        delta = (now - parsed).total_seconds()
        assert 0 <= delta < 10

    def test_write_accepts_dicts(self, tmp_path):
        """write() should accept dicts instead of Pydantic models."""
        logger = AuditLogger(tmp_path / "audit.db")

        envelope_dict = {
            "schema_version": "v1.0",
            "org_id": "org_test000000000000",
            "environment": "dev",
            "agent_id": "test-agent",
            "action_id": "act_test00000000000000000",
            "timestamp": "2026-02-15T10:00:00Z",
            "tool_name": "test_tool",
            "operation": "execute",
            "parameters": {},
            "idempotency_key": "idem_test",
            "target": {},
            "signature": "0" * 64,
        }

        decision_dict = {
            "action_id": "act_test00000000000000000",
            "decision": "ALLOW",
            "allowed": True,
            "reason_codes": ["TEST"],
            "policy_version": "1.0.0",
            "timing": {"ingest_ms": 0.1, "evaluation_ms": 0.2, "total_ms": 0.3},
        }

        event_id = logger.write(envelope_dict, decision_dict)
        assert event_id.startswith("evt_")


class TestAuditLoggerQuery:
    """Test AuditLogger query methods."""

    @pytest.fixture
    def logger_with_records(self, tmp_path):
        """Create logger with sample records."""
        logger = AuditLogger(tmp_path / "audit.db")

        # Write 3 records for org1
        for i in range(3):
            envelope = Envelope(
                schema_version="v1.0",
                org_id="org_test000000000001",
                environment="dev",
                agent_id="test-agent",
                action_id=f"act_test0000000000000000{i}",
                timestamp="2026-02-15T10:00:00Z",
                action="test_tool",
                operation="execute",
                parameters={"index": i},
                idempotency_key=f"idem_test_{i}",
                target={},
                signature="0" * 64,
            )
            decision = Decision(
                action_id=f"act_test0000000000000000{i}",
                decision=DecisionType.ALLOW if i < 2 else DecisionType.BLOCK,
                allowed=i < 2,
                reason_codes=["TEST"],
                policy_version="1.0.0",
                timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
            )
            logger.write(envelope, decision)

        # Write 2 records for org2
        for i in range(2):
            envelope = Envelope(
                schema_version="v1.0",
                org_id="org_test000000000002",
                environment="dev",
                agent_id="test-agent",
                action_id=f"act_test000000000000000{i+10}",
                timestamp="2026-02-15T10:00:00Z",
                action="test_tool",
                operation="execute",
                parameters={"index": i + 10},
                idempotency_key=f"idem_test_{i+10}",
                target={},
                signature="0" * 64,
            )
            decision = Decision(
                action_id=f"act_test000000000000000{i+10}",
                decision=DecisionType.ALLOW,
                allowed=True,
                reason_codes=["TEST"],
                policy_version="1.0.0",
                timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
            )
            logger.write(envelope, decision)

        return logger

    def test_query_by_org(self, logger_with_records):
        """query_by_org() should return records for org."""
        records = logger_with_records.query_by_org("org_test000000000001")

        assert len(records) == 3
        for record in records:
            assert record['org_id'] == "org_test000000000001"

    def test_query_by_org_respects_limit(self, logger_with_records):
        """query_by_org() should respect limit parameter."""
        records = logger_with_records.query_by_org("org_test000000000001", limit=2)

        assert len(records) == 2

    def test_query_by_org_supports_pagination(self, logger_with_records):
        """query_by_org() should support offset for pagination."""
        page1 = logger_with_records.query_by_org("org_test000000000001", limit=2, offset=0)
        page2 = logger_with_records.query_by_org("org_test000000000001", limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 1
        # Should be different records
        assert page1[0]['event_id'] != page2[0]['event_id']

    def test_query_by_action_id_finds_record(self, logger_with_records):
        """query_by_action_id() should find record by action_id."""
        record = logger_with_records.query_by_action_id("act_test00000000000000000")

        assert record is not None
        assert record['action_id'] == "act_test00000000000000000"

    def test_query_by_action_id_returns_none_if_not_found(self, logger_with_records):
        """query_by_action_id() should return None if not found."""
        record = logger_with_records.query_by_action_id("act_nonexistent")

        assert record is None


class TestAuditLoggerIntegrity:
    """Test AuditLogger integrity verification."""

    def test_verify_integrity_succeeds_for_intact_record(self, tmp_path):
        """verify_integrity() should return True for intact record."""
        logger = AuditLogger(tmp_path / "audit.db")

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )
        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        event_id = logger.write(envelope, decision)

        # Verify integrity
        assert logger.verify_integrity(event_id) is True

    def test_verify_integrity_fails_for_tampered_record(self, tmp_path):
        """verify_integrity() should return False if record is tampered."""
        logger = AuditLogger(tmp_path / "audit.db")

        envelope = Envelope(
            schema_version="v1.0",
            org_id="org_test000000000000",
            environment="dev",
            agent_id="test-agent",
            action_id="act_test00000000000000000",
            timestamp="2026-02-15T10:00:00Z",
            action="test_tool",
            operation="execute",
            parameters={},
            idempotency_key="idem_test",
            target={},
            signature="0" * 64,
        )
        decision = Decision(
            action_id="act_test00000000000000000",
            decision=DecisionType.ALLOW,
            allowed=True,
            reason_codes=["TEST"],
            policy_version="1.0.0",
            timing=Timing(ingest_ms=0.1, evaluation_ms=0.2, total_ms=0.3),
        )

        event_id = logger.write(envelope, decision)

        # Tamper with record (modify decision field directly in DB)
        conn = sqlite3.connect(tmp_path / "audit.db")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE audit_log SET decision = ? WHERE event_id = ?",
            ('{"decision": "BLOCK"}', event_id)
        )
        conn.commit()
        conn.close()

        # Verify integrity should fail
        assert logger.verify_integrity(event_id) is False

    def test_verify_integrity_raises_for_missing_event(self, tmp_path):
        """verify_integrity() should raise for nonexistent event_id."""
        logger = AuditLogger(tmp_path / "audit.db")

        with pytest.raises(AuditLogError) as exc_info:
            logger.verify_integrity("evt_nonexistent")

        assert "not found" in str(exc_info.value).lower()


class TestAuditLoggerErrors:
    """Test AuditLogger error handling."""

    def test_write_to_invalid_path_raises_error(self):
        """Initializing with invalid path should raise AuditLogError."""
        # Try to create logger with path that can't be created (read-only filesystem)
        # This should raise during __init__ when trying to create parent directories
        with pytest.raises((AuditLogError, OSError)):
            logger = AuditLogger("/invalid/path/audit.db")
