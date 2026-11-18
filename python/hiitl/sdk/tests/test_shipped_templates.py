"""HTL-45 8613a7bc item 3: a shipped template's allowlist admits its hosts and no lookalike of them.

Design: tests/conformance/shipped_templates/TEST_DESIGN.md. The template is read as a customer copies it: its
starter policies in the table's policy set, loaded by the SDK and evaluated under RESPECT_POLICY.
"""
import copy
import json
from pathlib import Path

import pytest

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.sdk.policy_loader import PolicyLoader, load_yaml

ROOT = Path(__file__).resolve().parents[4]
TABLE = json.loads((ROOT / 'tests/conformance/shipped_templates/cases.json').read_text())


def starter_policies():
    with open(ROOT / TABLE['template']) as stream:
        return load_yaml(stream)['starter_policies']


def decided(url, tmp_path):
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps({**TABLE['policy_set'], 'rules': starter_policies()}))
    envelope = copy.deepcopy(TABLE['envelope'])
    envelope['parameters'][TABLE['field']] = url
    return PolicyEvaluator().evaluate(envelope, PolicyLoader(path).load(), 'RESPECT_POLICY')


@pytest.mark.parametrize('url', TABLE['allowed'])
def test_an_allowlisted_destination_is_allowed_by_its_rule(url, tmp_path):
    rule = next(rule for rule in starter_policies() if rule['name'] == TABLE['rule'])
    decision = decided(url, tmp_path)
    assert (decision.decision, decision.reason_codes) == ('ALLOW', [rule['reason_code']])


@pytest.mark.parametrize('url', TABLE['not_allowed'])
def test_a_lookalike_destination_is_not_allowed(url, tmp_path):
    decision = decided(url, tmp_path)
    assert decision.allowed is False, (decision.decision, decision.reason_codes)
