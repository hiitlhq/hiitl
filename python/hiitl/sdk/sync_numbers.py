"""Diagnostic declarations for channel content, read from the content's owner.

These shapes name a refused number; they never parse, project or admit content.
"""
from functools import lru_cache
from hiitl.core.types import PolicySet, Envelope
from hiitl.core.input_declarations import policy_shape
from hiitl.core.route_types import Route, _route_input_shape
from hiitl.sdk.numeric_declarations import SHAPES


def _wrapped(shape, properties):
    return {**{key:shape[key] for key in ('$defs','definitions') if key in shape},
            'type':'object','properties':properties}


@lru_cache
def sync_numeric_shape(channel, *, cache=False):
    if channel in ('policy','kill_switches'):
        policy=policy_shape(PolicySet,Envelope)
        properties=({'policies':{'type':'array','items':{'type':'object','properties':{'content':policy}}}}
                    if channel=='policy' else {'policy_set':policy})
        return _wrapped(policy,properties)
    if channel=='routes':
        route=_route_input_shape(Route)
        rows={'type':'array','items':{'type':'object','properties':{'config':route}}}
        shape=_wrapped(route,{'routes':rows})
        return {**shape,**rows} if cache else shape
    return SHAPES['audit_ack']


TELEMETRY_UPLOAD_SHAPE=_wrapped(SHAPES['telemetry'],{'records':{'type':'array','items':SHAPES['telemetry']}})
