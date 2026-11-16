"""HTL-43: owned omission never erases explicitly supplied caller data."""
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from hiitl.core.lint import rule_alone
from hiitl.core.types import Rule
from hiitl.sdk.client import HIITL
from hiitl.core.numeric_domain import NUMERIC_BOUND
from hiitl.sdk.exceptions import EnvelopeValidationError, LifecycleError


def accepted(call, *args, **kwargs):
    """A valid authored fixture refused by the named boundary is an assertion failure."""
    try:
        return call(*args, **kwargs)
    except (ValidationError, EnvelopeValidationError) as error:
        raise AssertionError(f'valid owned input was refused: {error}') from error


def client():
    value = HIITL.__new__(HIITL)
    value.config = SimpleNamespace(org_id='org_inputcontract0001', environment='dev', signature_key=None)
    return value


def test_sdk_optional_none_is_absent_but_open_null_is_data():
    value = accepted(client()._build_envelope,
        action='send', operation='execute', agent_id='agent', target={},
        parameters={'null': None, 'false': False, 'zero': 0, 'empty': [], '__proto__': {'own': None}},
        user_id=None, session_id=None, confidence=None, reason=None, sensitivity=None,
        cost_estimate=None, requested_scopes=None, principal=None, correlation_id=None,
    )
    assert value.model_fields_set == {
        'schema_version', 'org_id', 'environment', 'agent_id', 'action_id', 'timestamp',
        'action', 'operation', 'parameters', 'target', 'idempotency_key', 'signature',
    }
    assert value.parameters == {'null': None, 'false': False, 'zero': 0, 'empty': [], '__proto__': {'own': None}}
    assert value.target == {}


def test_public_optional_defaults_still_evaluate_and_build_sparse_data(tmp_path, monkeypatch):
    value = HIITL(audit_db_path=str(tmp_path / 'calls.db'))
    captured = []
    build = value._build_envelope

    def keep(**kwargs):
        envelope = build(**kwargs)
        captured.append(envelope)
        return envelope

    monkeypatch.setattr(value, '_build_envelope', keep)
    optional = {name: None for name, parameter in inspect.signature(value.evaluate).parameters.items()
                if parameter.default is None}
    decision = accepted(value.evaluate, 'send', **optional)
    value.close()
    assert decision.decision == 'OBSERVE'
    assert decision.allowed is True
    assert len(captured) == 1
    assert captured[0].model_fields_set == {
        'schema_version', 'org_id', 'environment', 'agent_id', 'action_id', 'timestamp',
        'action', 'operation', 'parameters', 'target', 'idempotency_key', 'signature',
    }


def test_absent_verified_claims_stay_absent():
    value = client()
    value._principal_verifier = lambda token: {'sub': 'verified-person'}
    principal = value._verified_principal('local-token')
    assert principal is not None
    assert principal.model_fields_set == {'sub', 'verified_by', 'verified_at'}
    assert principal.sub == 'verified-person'


@pytest.mark.parametrize('field', ['scopes', 'iss', 'aud'])
def test_explicit_null_verified_claim_is_not_treated_as_omission(field):
    value = client()
    value._principal_verifier = lambda token: {'sub': 'verified-person', field: None}
    assert value._verified_principal('local-token') is None


def test_rule_alone_preserves_unset_fields_and_open_metadata():
    source = {
        'name': 'rule', 'description': 'One valid rule', 'priority': 1,
        'conditions': {'field': 'action', 'operator': 'exists', 'value': True},
        'decision': 'ALLOW', 'reason_code': 'OK',
        'metadata': {'__proto__': {'own': None}, 'constructor': False, 'toString': []},
    }
    rule = Rule.model_validate(source)
    fields = set(rule.model_fields_set)
    loaded = accepted(rule_alone, rule).rules[0]
    assert loaded.model_fields_set == fields | {'lifecycle_stage'}
    assert rule.model_fields_set == fields
    assert loaded.metadata == source['metadata']


def test_numeric_token_argument_is_read_before_verifier_dispatch():
    value = client()
    value._mode = 'hosted'
    value._evaluate_hosted = Mock(return_value='control')
    assert value.evaluate('send', principal_token='local-token') == 'control'
    value._evaluate_hosted.reset_mock()
    caught = None
    try:
        value.evaluate('send', principal_token=NUMERIC_BOUND)
    except Exception as error:
        caught = error
    assert isinstance(caught, EnvelopeValidationError)
    assert 'principal_token' in str(caught)
    assert 'requires a JSON string' in str(caught)
    assert 'not declared' not in str(caught)
    value._evaluate_hosted.assert_not_called()


def test_numeric_result_argument_is_read_before_result_projection():
    value = client()
    value._mode = 'hosted'
    value._hosted_client = SimpleNamespace(record_result=Mock(return_value={'held': True}))
    assert value.record_result('act_control', 'succeeded', duration_ms=1) == {'held': True}
    value._hosted_client.record_result.reset_mock()
    caught = None
    try:
        value.record_result('act_control', 'succeeded', duration_ms=NUMERIC_BOUND)
    except Exception as error:
        caught = error
    assert isinstance(caught, LifecycleError)
    assert 'duration_ms' in str(caught)
    assert 'JSON number' in str(caught) and str(NUMERIC_BOUND) in str(caught)
    assert 'pass the value as text' not in str(caught)
    value._hosted_client.record_result.assert_not_called()


def test_verifier_does_not_drop_an_unread_numeric_claim():
    value = client()
    value._principal_verifier = lambda token: {'sub': 'person', 'extra': {'number': NUMERIC_BOUND}}
    assert value._verified_principal('local-token') is None

