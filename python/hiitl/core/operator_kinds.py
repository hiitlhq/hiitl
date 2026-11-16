"""Declared operand kinds and located failures (policy_format.md, Comparison Operators)."""
from pydantic import BaseModel


class OperatorKindError(ValueError):
    """Only authored operator/path information is suitable for the public refusal."""
    def __init__(self, operator, field="<value>", reference=None, requirement="declared kind"):
        self.operator = getattr(operator, "value", operator)
        self.field = field
        self.reference = reference
        self.requirement = requirement
        location = f"field `{field}`" + (f" and referenced field `{reference}`" if reference else "")
        super().__init__(f"Operator `{self.operator}` has an operand of the wrong {requirement} at {location}. Correct the field value or policy to use the operator’s declared operand kinds.")


def literal_kind_ok(operator, value):
    """Only kinds declared by the operator alone; contains depends on its left operand."""
    if operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if operator in ("starts_with", "ends_with", "matches"):
        return isinstance(value, str)
    if operator in ("in", "not_in"):
        return isinstance(value, list)
    if operator == "exists":
        return isinstance(value, bool)
    if operator == "conforms_to":
        return isinstance(value, dict)
    return True


def require_operand_kinds(left, operator, right):
    """Called after the existing null/reference gates; never inspect schema member values."""
    if not literal_kind_ok(operator, right):
        raise OperatorKindError(operator)
    valid = True
    if operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"):
        valid = valid and isinstance(left, (int, float)) and not isinstance(left, bool)
    elif operator in ("starts_with", "ends_with", "matches"):
        valid = valid and isinstance(left, str)
    elif operator in ("contains", "not_contains"):
        valid = isinstance(left, list) or isinstance(left, str) and isinstance(right, str)
    elif operator == "conforms_to":
        valid = valid and isinstance(left, (dict, BaseModel))
    if not valid:
        raise OperatorKindError(operator)
