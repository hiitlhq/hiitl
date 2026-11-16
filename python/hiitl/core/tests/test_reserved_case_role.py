"""A complete executable refusal has a different role from its admitted control."""
import copy
import json
from pathlib import Path

from hiitl.core.tests.conformance_roles import is_refusal_case

ROOT = Path(__file__).resolve().parents[4]
ROWS = json.loads((ROOT / 'tests/conformance/reserved_policy_values/cases.json').read_text())['cases']


def test_reserved_case_role_keeps_every_control_and_positive():
    assert any(row['accept'] for row in ROWS)
    assert any(not row['accept'] for row in ROWS)
    for row in ROWS:
        assert is_refusal_case(row) is (not row['accept'])
        assert not is_refusal_case(row['control'])
        assert not is_refusal_case(row['input'])


def test_reserved_role_requires_the_whole_executable_case():
    row = next(row for row in ROWS if not row['accept'])
    for key in row:
        partial = copy.deepcopy(row)
        del partial[key]
        assert not is_refusal_case(partial)
    assert not is_refusal_case({**row, 'unread': True})
    for key, value in [('id', None), ('cause', None), ('path', ['field', True]),
                       ('path', 'field'), ('control', None), ('input', None), ('accept', 0)]:
        assert not is_refusal_case({**row, key: value})
