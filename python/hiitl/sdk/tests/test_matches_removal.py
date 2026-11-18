"""HTL-45 8613a7bc: a policy file naming `matches` is refused at load, naming it and the operators to use.

Design: tests/conformance/TEST_DESIGN.md (the `matches` refusal). The policy is conformance test_020's; the
operators to use are read from policy_format.md's sentence, never typed here.
"""
import json
from pathlib import Path
import re

import pytest
import yaml

from hiitl.sdk.exceptions import PolicyLoadError
from hiitl.sdk.policy_loader import PolicyLoader

ROOT = Path(__file__).resolve().parents[4]
CASE = json.loads((ROOT / 'tests/conformance/cases/refusals/'
                   'test_020_a_policy_naming_matches_is_refused_at_load.json').read_text())
SENTENCE = re.search(r'^\*\*`matches` is removed.*$', (ROOT / 'docs/specs/policy_format.md').read_text(), re.M)


def test_the_case_names_the_operators_the_spec_says_to_use():
    assert SENTENCE, 'policy_format.md no longer carries the sentence removing `matches`'
    replacements = re.findall(r'`(\w+)`', SENTENCE.group(0).split('operators to use in its place:')[1])
    assert replacements and CASE['expected_refusal']['names'] == ['matches', *replacements]


@pytest.mark.parametrize('wire', ['json', 'yaml'])
def test_a_policy_file_naming_matches_is_refused_at_load(wire, tmp_path):
    path = tmp_path / f'policy.{wire}'
    path.write_text(json.dumps(CASE['policy_set']) if wire == 'json' else yaml.safe_dump(CASE['policy_set']))
    with pytest.raises(PolicyLoadError) as caught:
        PolicyLoader(path).load()
    quoted = set(re.findall(r"'(\w+)'", str(caught.value)))
    assert [name for name in CASE['expected_refusal']['names'] if name not in quoted] == [], str(caught.value)
