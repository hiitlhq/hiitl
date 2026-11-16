"""Every fixed source declaration is exercised against the actual core model."""
import pytest
from pydantic import ValidationError

from hiitl.core.route_types import Route
from hiitl.core.types import Envelope, PolicySet
from hiitl.core.tests.input_contract_support import cases
from hiitl.core.tests.route_null_support import assert_named_path

MODELS = {'envelope': Envelope, 'policy': PolicySet, 'routes': Route}


@pytest.mark.parametrize('case', cases(*MODELS), ids=lambda case: case['id'])
def test_each_source_input_contract(case):
    model = MODELS[case['format']]
    model.model_validate(case['control'])
    if case['expected_accept']:
        model.model_validate(case['input'])
    else:
        with pytest.raises(ValidationError) as caught:
            model.model_validate(case['input'])
        assert_named_path(caught.value, case['path'])

