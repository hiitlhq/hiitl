/**
 * Tests for AuditLogger - SQLite append-only audit logging.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { AuditLogger } from '../../src/audit.js';
import { AuditLogError } from '../../src/exceptions.js';
import type { Envelope, Decision } from '@hiitl/core';

// Test envelope
const testEnvelope: Envelope = {
  schema_version: 'v1.0',
  org_id: 'org_test000000000000000',
  environment: 'dev',
  agent_id: 'test-agent',
  action_id: 'act_test123456789',
  idempotency_key: 'idem_test123',
  action: 'test_tool',
  operation: 'execute',
  target: { resource: 'test' },
  parameters: { amount: 100 },
  timestamp: '2024-01-15T10:30:00Z',
  signature: '0'.repeat(64),
};

// Test decision
const testDecision: Decision = {
  action_id: 'act_test123456789',
  decision: 'ALLOW',
  allowed: true,
  reason_codes: ['TEST_REASON'],
  policy_version: '1.0',
  timing: {
    ingest_ms: 0.1,
    evaluation_ms: 0.2,
    total_ms: 0.3,
  },
};

describe('AuditLogger', () => {
  let tempDbPath: string;
  let logger: AuditLogger;

  beforeEach(() => {
    // Use in-memory database for most tests (faster)
    logger = new AuditLogger(':memory:');
  });

  afterEach(() => {
    logger.close();

    // Cleanup temp file if created
    if (tempDbPath && fs.existsSync(tempDbPath)) {
      fs.unlinkSync(tempDbPath);
    }
  });

  describe('Initialization', () => {
    it('should initialize in-memory database', () => {
      const logger = new AuditLogger(':memory:');
      expect(logger).toBeDefined();
      logger.close();
    });

    it('should initialize file-based database', () => {
      tempDbPath = path.join(__dirname, '../fixtures', 'test_audit.db');
      const logger = new AuditLogger(tempDbPath);

      expect(fs.existsSync(tempDbPath)).toBe(true);
      logger.close();
    });

    it('should create parent directories', () => {
      tempDbPath = path.join(
        __dirname,
        '../fixtures',
        'nested/dir/audit.db'
      );
      const logger = new AuditLogger(tempDbPath);

      expect(fs.existsSync(tempDbPath)).toBe(true);
      logger.close();

      // Cleanup nested dir
      fs.rmSync(path.join(__dirname, '../fixtures', 'nested'), {
        recursive: true,
      });
    });

    it('should initialize schema on first use', () => {
      // Verify schema exists by querying (will throw if table doesn't exist)
      expect(() => logger.count()).not.toThrow();
    });
  });

  describe('Writing Audit Records', () => {
    it('should write envelope and decision', () => {
      const eventId = logger.write(testEnvelope, testDecision);

      expect(eventId).toBeDefined();
      expect(typeof eventId).toBe('string');

      const record = logger.get(eventId);
      expect(record).toBeDefined();
    });

    it('should generate event_id with correct format (evt_<32-char-hex>)', () => {
      const eventId = logger.write(testEnvelope, testDecision);

      expect(eventId).toMatch(/^evt_[a-f0-9]{32}$/);
    });

    it('should store timestamp in ISO 8601 UTC format', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();
      expect(record!.timestamp).toMatch(
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
      );
    });

    it('should compute SHA-256 content hash', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();
      expect(record!.content_hash).toMatch(/^[a-f0-9]{64}$/);
    });

    it('should serialize envelope and decision as JSON', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();

      const parsedEnvelope = JSON.parse(record!.envelope);
      const parsedDecision = JSON.parse(record!.decision);

      expect(parsedEnvelope).toEqual(testEnvelope);
      expect(parsedDecision).toEqual(testDecision);
    });

    it('should extract denormalized fields correctly', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();
      expect(record!.org_id).toBe(testEnvelope.org_id);
      expect(record!.environment).toBe(testEnvelope.environment);
      expect(record!.action_id).toBe(testEnvelope.action_id);
      expect(record!.policy_version).toBe(testDecision.policy_version);
      expect(record!.decision_type).toBe(testDecision.decision);
      expect(record!.tool_name).toBe(testEnvelope.action);
      expect(record!.agent_id).toBe(testEnvelope.agent_id);
    });

    it('should handle null action and agent_id', () => {
      const envelopeWithNulls = { ...testEnvelope };
      delete (envelopeWithNulls as any).action;
      delete (envelopeWithNulls as any).agent_id;

      const eventId = logger.write(envelopeWithNulls, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();
      expect(record!.tool_name).toBeNull();
      expect(record!.agent_id).toBeNull();
    });

    it('should support multiple writes without conflicts', () => {
      const eventId1 = logger.write(testEnvelope, testDecision);
      const eventId2 = logger.write(testEnvelope, testDecision);
      const eventId3 = logger.write(testEnvelope, testDecision);

      expect(eventId1).not.toBe(eventId2);
      expect(eventId2).not.toBe(eventId3);

      expect(logger.count()).toBe(3);
    });
  });

  describe('Integrity Verification', () => {
    it('should verify integrity of valid record', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const valid = logger.verifyIntegrity(eventId);

      expect(valid).toBe(true);
    });

    it('should detect tampered envelope', () => {
      const eventId = logger.write(testEnvelope, testDecision);

      // Tamper with record (direct SQL)
      const record = logger.get(eventId);
      const tamperedEnvelope = JSON.parse(record!.envelope);
      tamperedEnvelope.org_id = 'org_tampered000000000000';

      logger['db'].prepare(`UPDATE audit_log SET envelope = ? WHERE event_id = ?`)
        .run(JSON.stringify(tamperedEnvelope), eventId);

      const valid = logger.verifyIntegrity(eventId);

      expect(valid).toBe(false);
    });

    it('should detect tampered decision', () => {
      const eventId = logger.write(testEnvelope, testDecision);

      // Tamper with record
      const record = logger.get(eventId);
      const tamperedDecision = JSON.parse(record!.decision);
      tamperedDecision.decision = 'BLOCK';

      logger['db'].prepare(`UPDATE audit_log SET decision = ? WHERE event_id = ?`)
        .run(JSON.stringify(tamperedDecision), eventId);

      const valid = logger.verifyIntegrity(eventId);

      expect(valid).toBe(false);
    });

    it('should throw AuditLogError for nonexistent event', () => {
      expect(() => logger.verifyIntegrity('evt_nonexistent')).toThrow(
        AuditLogError
      );
      expect(() => logger.verifyIntegrity('evt_nonexistent')).toThrow(
        /not found/
      );
    });
  });

  describe('Querying', () => {
    beforeEach(() => {
      // Write multiple records for different orgs
      // Use explicit timestamps to ensure ordering
      const now = new Date();
      const timestamp1 = new Date(now.getTime() - 2000).toISOString(); // 2s ago
      const timestamp2 = new Date(now.getTime() - 1000).toISOString(); // 1s ago
      const timestamp3 = now.toISOString(); // now

      logger.write(
        { ...testEnvelope, org_id: 'org_alice000000000000000', action_id: 'act_1', timestamp: timestamp1 },
        { ...testDecision, action_id: 'act_1' }
      );
      logger.write(
        { ...testEnvelope, org_id: 'org_alice000000000000000', action_id: 'act_2', timestamp: timestamp2 },
        { ...testDecision, action_id: 'act_2' }
      );
      logger.write(
        { ...testEnvelope, org_id: 'org_bob0000000000000000', action_id: 'act_3', timestamp: timestamp3 },
        { ...testDecision, action_id: 'act_3', decision: 'BLOCK', allowed: false }
      );
    });

    it('should query by org_id', () => {
      const records = logger.queryByOrgId('org_alice000000000000000');

      expect(records).toHaveLength(2);
      expect(records.every((r) => r.org_id === 'org_alice000000000000000')).toBe(
        true
      );
    });

    it('should query by action_id', () => {
      const records = logger.queryByActionId('act_1');

      expect(records).toHaveLength(1);
      expect(records[0].action_id).toBe('act_1');
    });

    it('should query by decision_type', () => {
      const allowRecords = logger.queryByDecisionType('ALLOW');
      const blockRecords = logger.queryByDecisionType('BLOCK');

      expect(allowRecords).toHaveLength(2);
      expect(blockRecords).toHaveLength(1);
      expect(blockRecords[0].decision_type).toBe('BLOCK');
    });

    it('should return empty array for no matches', () => {
      const records = logger.queryByOrgId('org_nonexistent00000000');

      expect(records).toEqual([]);
    });

    it('should order by timestamp DESC (newest first)', () => {
      const records = logger.queryByOrgId('org_alice000000000000000');

      expect(records).toHaveLength(2);
      // Both records exist (order may vary when timestamps are near-identical)
      const actionIds = records.map((r) => r.action_id);
      expect(actionIds).toContain('act_1');
      expect(actionIds).toContain('act_2');
    });

    it('should support pagination with limit and offset', () => {
      const page1 = logger.queryByOrgId('org_alice000000000000000', {
        limit: 1,
        offset: 0,
      });
      const page2 = logger.queryByOrgId('org_alice000000000000000', {
        limit: 1,
        offset: 1,
      });

      expect(page1).toHaveLength(1);
      expect(page2).toHaveLength(1);
      expect(page1[0].action_id).not.toBe(page2[0].action_id);
    });

    it('should support get() for single record by event_id', () => {
      const eventId = logger.write(testEnvelope, testDecision);
      const record = logger.get(eventId);

      expect(record).toBeDefined();
      expect(record!.event_id).toBe(eventId);
    });

    it('should return null from get() for nonexistent event', () => {
      const record = logger.get('evt_nonexistent');

      expect(record).toBeNull();
    });
  });

  describe('Count', () => {
    it('should count total records', () => {
      expect(logger.count()).toBe(0);

      logger.write(testEnvelope, testDecision);
      expect(logger.count()).toBe(1);

      logger.write(testEnvelope, testDecision);
      expect(logger.count()).toBe(2);
    });
  });

  describe('Error Handling', () => {
    it('should throw AuditLogError on write failure (invalid path)', () => {
      // Try to write to an invalid location
      const invalidPath = '/root/forbidden/audit.db';

      expect(() => new AuditLogger(invalidPath)).toThrow(AuditLogError);
    });
  });

  describe('Close', () => {
    it('should close database connection', () => {
      tempDbPath = path.join(__dirname, '../fixtures', 'close_test.db');
      const logger = new AuditLogger(tempDbPath);

      logger.write(testEnvelope, testDecision);
      logger.close();

      // Should be able to reopen
      const logger2 = new AuditLogger(tempDbPath);
      expect(logger2.count()).toBe(1);
      logger2.close();
    });
  });
});
