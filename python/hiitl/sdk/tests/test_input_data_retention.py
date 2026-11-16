"""HTL-43: own open keys remain data through the actual Python decision/record path."""
import copy
import hashlib
import json

import pytest

from hiitl.core.canonical import canonical_hash, canonical_json
from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.types import Envelope, PolicySet
from hiitl.core.tests.input_contract_support import cases
from hiitl.sdk.audit import AuditLogger


@pytest.mark.parametrize('member', ['parameters', 'target', 'metadata'])
def test_own_keys_survive_model_field_read_canonicalization_and_record(member, tmp_path):
    own = {'__proto__': {'allowed': True}, 'constructor': False, 'toString': None}
    canonical = '{"__proto__":{"allowed":true},"constructor":false,"toString":null}'
    source = copy.deepcopy(cases('envelope')[0]['control'])
    source[member] = own
    envelope = Envelope.model_validate(source)
    policy_source = {
        'name': 'own-keys', 'version': 'v1.0.0', 'description': 'A supplied own data key decides',
        'scope': {'org_id': source['org_id'], 'environment': source['environment']},
        'metadata': own,
        'rules': [{
            'name': 'own-key', 'description': 'Read the own nested key', 'priority': 2,
            'conditions': {'field': f'{member}.__proto__.allowed', 'operator': 'equals', 'value': True},
            'decision': 'BLOCK', 'reason_code': 'OWN_DATA', 'metadata': own,
            'remediation': {'message': 'Own data was read', 'suggestion': 'Keep it',
                            'type': 'custom', 'details': own},
        }, {
            'name': 'otherwise', 'description': 'The changed answer if data is lost', 'priority': 1,
            'conditions': {'field': 'action', 'operator': 'exists', 'value': True},
            'decision': 'ALLOW', 'reason_code': 'NO_OWN_DATA',
        }],
    }
    policy = PolicySet.model_validate(policy_source)
    assert getattr(envelope, member) == own
    assert policy.metadata == own
    assert policy.rules[0].metadata == own
    decision = PolicyEvaluator().evaluate(envelope, policy)
    assert decision.decision == 'BLOCK'
    assert decision.allowed is False
    assert decision.reason_codes == ['OWN_DATA']
    assert decision.remediation.details == own
    assert type(decision.remediation.details) is dict
    assert canonical_json(getattr(envelope, member)) == canonical
    assert canonical_hash(getattr(envelope, member)) == hashlib.sha256(canonical.encode()).hexdigest()
    assert json.loads(canonical_json(policy.model_dump(mode='json', exclude_unset=True)))['metadata'] == own
    audit = AuditLogger(str(tmp_path / 'own-keys.db'))
    audit.write(envelope, decision)
    record = audit.query_by_action_id(envelope.action_id)
    assert json.loads(record['envelope'])[member] == own
    assert json.loads(record['decision'])['remediation']['details'] == own
    assert source[member] == own
    assert policy_source['metadata'] == own

