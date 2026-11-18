"""Read supplied nulls against the route schema's generated null constraints.

Omission, non-null validation and defaults remain the route model's concerns.
Untyped values have no child constraints and retain arbitrary JSON data.
"""
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from hiitl.core.route_null_shape import ROUTE_NULL_SHAPE


def forbidden_nulls(value: Any, shape: Mapping = ROUTE_NULL_SHAPE) -> list[tuple[str | int, ...]]:
    """Return concrete paths of explicit nulls refused by the supplied shape."""
    paths: list[tuple[str | int, ...]] = []

    def visit(current: Any, node: Mapping, path: tuple[str | int, ...]) -> None:
        if isinstance(current, BaseModel):
            current = current.model_dump(exclude_unset=True)
        if current is None:
            if not node.get('allows_null', True):
                paths.append(path)
            return
        if isinstance(current, Mapping):
            properties = node.get('properties', {})
            additional = node.get('additionalProperties', {})
            for key, child in current.items():
                constraint = properties[key] if key in properties else additional
                if constraint:
                    visit(child, constraint, (*path, key))
        elif isinstance(current, (list, tuple)) and 'items' in node:
            for index, child in enumerate(current):
                visit(child, node['items'], (*path, index))

    visit(value, shape, ())
    return paths
