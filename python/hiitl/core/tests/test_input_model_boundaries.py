"""Native child construction must not hide coercion before the parent reads it."""
import copy
import pytest
from pydantic import ValidationError

from hiitl.core.route_types import InboundPermissions, Route, RouteQueue
from hiitl.core.types import CostEstimate, Envelope, PolicySet, PromptRef
from hiitl.core.numeric_domain import NUMERIC_BOUND
from hiitl.core.tests.input_contract_support import cases
from hiitl.core.tests.route_null_support import assert_named_path


@pytest.mark.parametrize('model,control,path,bad', [
    (PromptRef, {'file': 'source.py', 'line': 1, 'quoted': 'read'}, ['line'], True),
    (PromptRef, {'file': 'source.py', 'line': 1, 'quoted': 'read'}, ['line'], '1'),
    (RouteQueue, {'batch_size': 1}, ['batch_size'], '1'),
    (InboundPermissions, {'can_signal': True}, ['can_signal'], 'true'),
    (CostEstimate, {'tokens': 1}, ['tokens'], True),
    (CostEstimate, {'dollars': 1}, ['dollars'], '1'),
])
def test_native_child_does_not_coerce_before_parent(model, control, path, bad):
    model.model_validate(control)
    with pytest.raises(ValidationError) as caught:
        model.model_validate({**control, path[0]: bad})
    assert_named_path(caught.value, path)


def test_native_integer_keeps_integral_json_number():
    value = PromptRef(file='source.py', line=1.0, quoted='read')
    assert value.line == 1


@pytest.mark.parametrize('format,model', [('envelope', Envelope), ('policy', PolicySet), ('routes', Route)])
@pytest.mark.parametrize('existing_model', [False, True])
def test_whole_supplied_model_numbers_are_checked_before_projection(format, model, existing_model):
    source = copy.deepcopy(cases(format)[0]['control'])
    source['metadata'] = {'own': {'value': 1}}
    control = model.model_validate(source)
    if existing_model:
        control.metadata['own']['value'] = NUMERIC_BOUND
        changed = control
    else:
        source['metadata']['own']['value'] = NUMERIC_BOUND
        changed = source
    caught = None
    try:
        model.model_validate(changed)
    except ValidationError as error:
        caught = error
    assert caught is not None
    assert_named_path(caught, ['metadata', 'own', 'value'])
    assert 'text' in str(caught)



@pytest.mark.parametrize('member', ['timing', 'escalation_context', 'unrecognized'])
def test_decision_numbers_are_checked_before_coercion_or_projection(member):
    from hiitl.core.types import Decision
    source = {'action_id': 'decision-input', 'decision': 'ALLOW', 'allowed': True,
              'reason_codes': [], 'policy_version': 'v1.0.0',
              'timing': {'ingest_ms': 0, 'evaluation_ms': 0, 'total_ms': 0}}
    control = Decision.model_validate(source)
    assert control.cache_status is None
    assert control.timing.total_ms == 0
    if member == 'timing':
        source['timing']['total_ms'] = NUMERIC_BOUND
        path = ['timing', 'total_ms']
    else:
        source[member] = {'own': NUMERIC_BOUND}
        path = [member, 'own']
    caught = None
    try:
        Decision.model_validate(source)
    except ValidationError as error:
        caught = error
    assert caught is not None
    assert_named_path(caught, path)


def test_existing_decision_numbers_are_checked_before_reuse():
    from hiitl.core.types import Decision
    source = {'action_id': 'decision-input', 'decision': 'ALLOW', 'allowed': True,
              'reason_codes': [], 'policy_version': 'v1.0.0',
              'timing': {'ingest_ms': 0, 'evaluation_ms': 0, 'total_ms': 0},
              'escalation_context': {'own': 0}}
    value = Decision.model_validate(source)
    value.escalation_context['own'] = NUMERIC_BOUND
    caught = None
    try:
        Decision.model_validate(value)
    except ValidationError as error:
        caught = error
    assert caught is not None
    assert_named_path(caught, ['escalation_context', 'own'])


@pytest.mark.parametrize('format,model', [('envelope', Envelope), ('policy', PolicySet), ('routes', Route)])
def test_valid_existing_model_preserves_omission_and_identity(format, model):
    value = model.model_validate(copy.deepcopy(cases(format)[0]['control']))
    fields = set(value.model_fields_set)
    before = value.model_dump(mode='python')
    try:
        reread = model.model_validate(value)
    except ValidationError as error:
        raise AssertionError(f'valid existing {format} was refused on reread: {error}') from error
    assert reread is value
    assert value.model_fields_set == fields
    assert value.model_dump(mode='python') == before


@pytest.mark.parametrize('written', [str(NUMERIC_BOUND), 'Infinity', 'NaN'])
def test_decision_numeric_text_is_refused_without_changing_numeric_positive(written):
    from hiitl.core.types import Decision
    source = {'action_id': 'decision-input', 'decision': 'ALLOW', 'allowed': True,
              'reason_codes': [], 'policy_version': 'v1.0.0',
              'timing': {'ingest_ms': 0, 'evaluation_ms': 0, 'total_ms': 0}}
    assert Decision.model_validate(source).timing.total_ms == 0
    source['timing']['total_ms'] = written
    caught = None
    try:
        Decision.model_validate(source)
    except ValidationError as error:
        caught = error
    assert caught is not None
    assert_named_path(caught, ['timing', 'total_ms'])
