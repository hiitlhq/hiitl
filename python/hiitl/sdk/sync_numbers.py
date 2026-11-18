"""Diagnostic declarations for channel content, read from the content's owner.

These shapes name a refused number; they never parse, project or admit content.
"""
from functools import lru_cache
from hiitl.core.types import PolicySet, Rule, Envelope
from hiitl.core.input_declarations import policy_shape
from hiitl.core.route_types import Route, _route_input_shape
from hiitl.sdk.numeric_declarations import SHAPES


def _wrapped(shape, properties):
    return {**{key:shape[key] for key in ('$defs','definitions') if key in shape},
            'type':'object','properties':properties}


@lru_cache
def _sync_numeric_shapes():
    """Build the channel declarations together before any background cycle."""
    policy = policy_shape(PolicySet, Envelope)
    # A received set also reaches each Rule's own before-validator.
    policy_shape(Rule, Envelope)
    route = _route_input_shape(Route)
    rows = {'type': 'array', 'items': {'type': 'object', 'properties': {'config': route}}}
    return {
        'policy': _wrapped(policy, {'policies': {'type': 'array', 'items': {'type': 'object', 'properties': {'content': policy}}}}),
        'kill_switches': _wrapped(policy, {'policy_set': policy}),
        'routes': _wrapped(route, {'routes': rows}),
        'cached_routes': {**_wrapped(route, {'routes': rows}), **rows},
    }


def sync_numeric_shape(channel, *, cache=False):
    shapes = _sync_numeric_shapes()
    return shapes.get('cached_routes' if channel == 'routes' and cache else channel, SHAPES['audit_ack'])


TELEMETRY_UPLOAD_SHAPE=_wrapped(SHAPES['telemetry'],{'records':{'type':'array','items':SHAPES['telemetry']}})
