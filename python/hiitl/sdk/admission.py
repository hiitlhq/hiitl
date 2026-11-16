"""Keep numeric admission at the SDK entry under its existing failure contract."""
from hiitl.core.numeric_domain import validate_numeric_domain, NumericDomainError
from hiitl.sdk.exceptions import SyncError, ConfigurationError
from functools import lru_cache
from typing import get_type_hints, get_args
from hiitl.sdk.sync_numbers import sync_numeric_shape
from hiitl.core.input_types import model_shape
from pydantic import TypeAdapter


@lru_cache
def call_numeric_shape(owner, model):
    """Envelope members keep their declaration; call-only arguments keep theirs."""
    shape = model_shape(model)
    properties = dict(shape['properties'])
    definitions = dict(shape.get('$defs', {}))
    for name, annotation in get_type_hints(owner).items():
        if name == 'return' or name in properties:
            continue
        child = TypeAdapter(annotation).json_schema()
        for key, definition in child.pop('$defs', {}).items():
            if key in definitions and definitions[key] != definition:
                raise ValueError(f'Conflicting numeric diagnostic declaration: {key}')
            definitions[key] = definition
        properties[name] = child
    return {**shape, 'properties': properties, '$defs': definitions}

def admit_sync(channel, value, path=(), *, shape=None):
    """The sync entry retains its declared recoverable channel failure."""
    try:
        validate_numeric_domain(value, path, shape=shape if shape is not None else sync_numeric_shape(channel))
    except NumericDomainError as error:
        raise SyncError(channel, f"Numeric input refused: {error}", error) from error


def sync_channel(path):
    name = path.rsplit('/', 1)[-1].removesuffix('.json')
    return {'policies': 'policy', 'kill-switches': 'kill_switches'}.get(name, name)



@lru_cache
def _argument_numbers(owner):
    declarations={}
    for name,annotation in get_type_hints(owner).items():
        kinds={annotation,*get_args(annotation)}
        if float in kinds:declarations[name]={'type':'number'}
        elif int in kinds:declarations[name]={'type':'integer'}
    return {'type':'object','properties':declarations}


def admit_configuration(owner, values):
    """Read the component's own numeric argument declarations, without new bounds."""
    try:
        validate_numeric_domain(values, shape=_argument_numbers(owner))
    except NumericDomainError as error:
        raise ConfigurationError(str(error)) from error
