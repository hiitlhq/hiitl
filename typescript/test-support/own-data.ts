/** Fixtures for HTL-43's own-data contract; key names come from the language's prototype. */
import { ENVELOPE_SCHEMA_VERSION } from '../packages/core/src/types.js';

export const ownData = (): Record<string, unknown> => Object.fromEntries(
  Object.getOwnPropertyNames(Object.prototype).map(key => [key, { marker: 'written', nested: [null, { held: true }] }]),
);

export const envelopeInput = (fields: Record<string, unknown> = {}) => ({
  schema_version: ENVELOPE_SCHEMA_VERSION, org_id: 'org_htl43own000000000', environment: 'prod',
  agent_id: 'fixture-agent', action_id: 'act_htl43own000000000000', idempotency_key: 'own-data',
  action: 'fixture_action', timestamp: '2026-11-14T12:00:00Z', signature: 'a'.repeat(64), ...fields,
});

export const policyInput = () => ({
  name: 'own-data', version: 'v1.0.0', description: 'Own data fixture',
  scope: { org_id: 'org_htl43own000000000', environment: 'prod' },
  rules: [{ name: 'hold', description: 'Match a supplied own value', priority: 1,
    conditions: { field: 'parameters.__proto__.marker', operator: 'equals', value: 'written' },
    decision: 'BLOCK', reason_code: 'OWN_DATA',
    metadata: ownData(), remediation: { message: 'held', suggestion: 'review', type: 'custom', details: ownData() },
    tests: [{ envelope: { action: 'fixture_action', parameters: ownData() }, expect: 'BLOCK' }],
  }], metadata: ownData(),
});

export const routeInput = () => ({ name: 'own-data', version: 'v1.0.0', direction: 'outbound', timing: 'async',
  endpoint: 'https://example.test/fixture', metadata: ownData() });
