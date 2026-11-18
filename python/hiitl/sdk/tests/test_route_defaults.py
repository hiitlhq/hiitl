"""Gap 272: the actual SDK loader supplies the declared complete context."""
import json
import pytest
from hiitl.core.route_types import resolve_escalation_context
from hiitl.core.tests.route_defaults_support import all_cases, expected_context
from hiitl.sdk.route_loader import RouteLoader

@pytest.mark.parametrize('case', all_cases(), ids=lambda c:c['id'])
def test_loaded_route_defaults_and_complete_context(case, tmp_path, monkeypatch):
    monkeypatch.setenv('HTL39_ROUTE_FIXTURE', 'local-route-fixture')
    (tmp_path / (case['input']['name'] + '.json')).write_text(json.dumps(case['input']))
    route = RouteLoader(str(tmp_path)).get(case['input']['name'])
    assert route.model_dump(mode='json', exclude_none=True) == case['expected']
    assert json.loads(json.dumps(resolve_escalation_context(route))) == expected_context(case['expected'])
