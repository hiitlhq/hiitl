"""policy_format.md: one value comparison for the six JSON kinds."""
from typing import Any
from pydantic import BaseModel


def json_equal(left: Any, right: Any) -> bool:
    """Compare admitted JSON values without Python's boolean/number coercion."""
    # Declared object models hold their supplied members; unset implementation
    # None defaults are not JSON members. Declared envelope date fields already
    # carry their supplied text (or the native datetime's existing JSON form).
    if isinstance(left, BaseModel):
        left = left.model_dump(mode="python", exclude_unset=True)
    if isinstance(right, BaseModel):
        right = right.model_dump(mode="python", exclude_unset=True)
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)):
        return isinstance(right, (int, float)) and left == right
    if isinstance(left, str):
        return isinstance(right, str) and left == right
    if isinstance(left, list):
        return (isinstance(right, list) and len(left) == len(right)
                and all(json_equal(a, b) for a, b in zip(left, right)))
    if isinstance(left, dict):
        return (isinstance(right, dict) and left.keys() == right.keys()
                and all(json_equal(value, right[key]) for key, value in left.items()))
    return False
