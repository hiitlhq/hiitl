"""HTL-45 d0640d7a (gap 322): a policy file whose condition has no `value` is refused at load, at its `value` path.

Design: tests/conformance/TEST_DESIGN.md (gap 322). The policies are the refusal cases located at a `value` path; the
path each is refused at is the case's own, never typed here.
"""
import json
from pathlib import Path

import pytest
import yaml

from hiitl.sdk.exceptions import PolicyLoadError
from hiitl.sdk.policy_loader import PolicyLoader

ROOT = Path(__file__).resolve().parents[4]
CASES = [case for case in (json.loads(path.read_text())
                           for path in sorted((ROOT / 'tests/conformance/cases/refusals').glob('*.json')))
         if case['expected_refusal']['artifact'] == 'policy_set'
         and all(at.endswith('.value') for at in case['expected_refusal']['at'])]


def test_the_refusal_cases_at_a_value_path_are_read():
    assert CASES, 'no refusal case is located at a condition value path'


@pytest.mark.parametrize('wire', ['json', 'yaml'])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['test_id'][:8])
def test_a_policy_file_whose_condition_has_no_value_is_refused_at_its_value_path(case, wire, tmp_path):
    path = tmp_path / f'policy.{wire}'
    path.write_text(json.dumps(case['policy_set']) if wire == 'json' else yaml.safe_dump(case['policy_set']))
    with pytest.raises(PolicyLoadError) as caught:
        PolicyLoader(path).load()
    located = sorted({'.'.join(map(str, error['loc'])) for error in caught.value.__cause__.errors()})
    assert located == sorted(case['expected_refusal']['at']), str(caught.value)
