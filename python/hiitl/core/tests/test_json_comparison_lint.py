"""Lint's finite-point proof uses policy_format.md's JSON-value comparison."""
import pytest
from hiitl.core.lint import dnf, implies, satisfiable

ALWAYS = {'parameters.probe'}


def atom(operator, value):
    return {'field': 'parameters.probe', 'operator': operator, 'value': value}


@pytest.mark.parametrize('operator,value,possible', [
    ('equals', 1, False), ('not_equals', 1, True),
    ('in', [1], False), ('not_in', [1], True),
])
def test_boolean_point_intersection_is_not_a_numeric_point(operator, value, possible):
    forms = dnf({'all_of': [atom('equals', True), atom(operator, value)]})
    assert [satisfiable(form, ALWAYS) for form in forms] == [possible]


@pytest.mark.parametrize('operator,value,contained', [
    ('equals', 1, False), ('not_equals', 1, True),
    ('in', [1], False), ('not_in', [1], True),
    ('in', [True, 1], True),
])
def test_boolean_point_implication_uses_json_kinds(operator, value, contained):
    assert implies(dnf(atom('equals', True)), dnf(atom(operator, value)), ALWAYS) is contained


def test_numeric_exclusion_keeps_a_boolean_witness():
    forms = dnf({'all_of': [atom('in', [True, 1]), atom('not_equals', 1)]})
    assert [satisfiable(form, ALWAYS) for form in forms] == [True]


def test_lint_keeps_unread_composite_points_opaque():
    assert dnf(atom('equals', {'nested': [True]})) is None
