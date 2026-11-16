"""Decision numeric paths come from its canonical JSON schema, not SDK answers."""
import copy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from hiitl.core.types import Decision
from hiitl.core.tests.route_null_support import assert_named_path

ROOT = Path(__file__).resolve().parents[4]
TEXT = (ROOT / 'docs/specs/decision_response.md').read_text()
START = TEXT.index('```json', TEXT.index('### JSON Schema')) + len('```json')
SCHEMA = json.loads(TEXT[START:TEXT.index('```', START)])


def numeric_members(node, path=()):
    if '$ref' in node:
        target = SCHEMA
        for part in node['$ref'].removeprefix('#/').split('/'):
            target = target[part]
        yield from numeric_members(target, path)
    if node.get('type') in ('integer', 'number'):
        yield path
    for key, child in node.get('properties', {}).items():
        yield from numeric_members(child, (*path, key))
    if 'items' in node:
        yield from numeric_members(node['items'], (*path, 0))


def witness(node):
    if '$ref' in node:
        target = SCHEMA
        for part in node['$ref'].removeprefix('#/').split('/'):
            target = target[part]
        return witness(target)
    if 'enum' in node: return node['enum'][0]
    kind = node.get('type')
    if kind == 'object':
        return {key: witness(value) for key, value in node.get('properties', {}).items()}
    if kind == 'array': return [witness(node.get('items', {}))]
    if kind == 'boolean': return True
    if kind in ('integer', 'number'): return 1
    if node.get('format') == 'date-time': return '2026-11-14T00:00:00Z'
    return 'fixture'


PATHS = list(numeric_members(SCHEMA))


def control_for(path):
    source = {'action_id': 'action', 'decision': 'ALLOW', 'allowed': True,
              'reason_codes': [], 'policy_version': 'v1.0.0',
              'timing': {'ingest_ms': 1, 'evaluation_ms': 1, 'total_ms': 1}}
    source[path[0]] = witness(SCHEMA['properties'][path[0]])
    return source


@pytest.mark.parametrize('path', PATHS, ids=lambda path: '.'.join(map(str, path)))
@pytest.mark.parametrize('bad', [True, False, '1', '1.5'])
def test_every_decision_numeric_member_refuses_bool_and_text(path, bad):
    source = control_for(path)
    Decision.model_validate(source)
    target = source
    for part in path[:-1]: target = target[part]
    target[path[-1]] = bad
    caught = None
    try: Decision.model_validate(source)
    except ValidationError as error: caught = error
    assert caught is not None
    assert_named_path(caught, list(path))



def detail_numbers():
    import re
    for section in TEXT.split('### Type: `')[1:]:
        subtype = section.split('`', 1)[0]
        for member, kind in re.findall(r'^\| `([^`]+)` \| `(number|integer)` \|', section, re.M):
            yield subtype, member, kind


@pytest.mark.parametrize('subtype,member,kind', list(detail_numbers()))
@pytest.mark.parametrize('bad', [True, False, '1', '1.5'])
def test_decision_subtype_numeric_details_refuse_bool_and_text(subtype, member, kind, bad):
    source = control_for(('timing', 'total_ms'))
    source['remediation'] = {'type': subtype, 'message': 'Read', 'suggestion': 'Keep', 'details': {member: 1}}
    assert Decision.model_validate(source).remediation.details[member] == 1
    source['remediation']['details'][member] = bad
    caught = None
    try: Decision.model_validate(source)
    except ValidationError as error: caught = error
    assert caught is not None
    assert_named_path(caught, ['remediation', 'details', member])


def test_decision_numeric_typing_preserves_existing_nulls_and_open_text():
    source = control_for(('timing', 'total_ms'))
    source.update(cache_status=None, rate_limit=None,
                  escalation_context={'arbitrary_text': '1', 'null': None},
                  remediation={'type': 'custom', 'message': 'Read', 'suggestion': 'Keep',
                               'details': {'threshold': '1', 'limit': True, 'current': None}})
    value = Decision.model_validate(source)
    assert value.cache_status is None
    assert value.rate_limit is None
    assert value.escalation_context == source['escalation_context']
    assert value.remediation.details == source['remediation']['details']


def child_model(annotation):
    from typing import get_args
    from pydantic import BaseModel
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for child in get_args(annotation):
        found = child_model(child)
        if found is not None: return found
    return None


@pytest.mark.parametrize('path', PATHS, ids=lambda path: '.'.join(map(str, path)))
@pytest.mark.parametrize('bad', [True, False, '1', '1.5'])
def test_native_decision_child_does_not_hide_numeric_coercion(path, bad):
    model = child_model(Decision.model_fields[path[0]].annotation)
    assert model is not None, f'the declared nested numeric path has a model: {path}'
    source = witness(SCHEMA['properties'][path[0]])
    local = path[1:]
    if local[0] == 0:
        source = source[0]
        local = local[1:]
    model.model_validate(source)
    target = source
    for part in local[:-1]: target = target[part]
    target[local[-1]] = bad
    caught = None
    try: model.model_validate(source)
    except ValidationError as error: caught = error
    assert caught is not None
    assert_named_path(caught, list(local))
