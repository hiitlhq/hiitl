"""Typed remedies are read from every canonical numeric declaration."""
import copy,json
from pathlib import Path
import pytest
from pydantic import ValidationError
from hiitl.core.types import Envelope,PolicySet,Decision
from hiitl.core.route_types import Route
from hiitl.core.numeric_domain import NUMERIC_BOUND
ROOT=Path(__file__).resolve().parents[4]
ROWS=json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['cases']
MODELS={'envelope':Envelope,'policy':PolicySet,'routes':Route,'decision':Decision}
@pytest.mark.parametrize('row',ROWS,ids=lambda r:r['id'])
def test_numeric_refusal_names_the_owning_type_and_range(row):
 model=MODELS[row['format']];model.model_validate(row['control'])
 value=copy.deepcopy(row['control']);at=value
 for part in row['path'][:-1]:at=at[part]
 at[row['path'][-1]]=NUMERIC_BOUND
 with public_error(ValidationError)as caught:model.model_validate(value)
 message=' '.join(item['msg'] for item in caught.value.errors())
 assert '<root>'+''.join('['+json.dumps(p)+']'for p in row['path'])in message
 assert 'JSON '+row['type']in message and str(NUMERIC_BOUND)in message
 for limit in row['range'].values():assert f'{limit:g}'in message
 assert 'pass the value as text'not in message

OTHER_ROWS=json.loads((ROOT/'tests/conformance/numeric_remedies/cases.json').read_text())['other_cases']
@pytest.mark.parametrize('row',OTHER_ROWS,ids=lambda r:r['id'])
def test_only_open_data_is_directed_to_text(row):
 model=MODELS[row['format']];model.model_validate(row['control'])
 value=copy.deepcopy(row['control']);at=value
 for part in row['path'][:-1]:at=at[part]
 at[row['path'][-1]]=NUMERIC_BOUND
 with public_error(ValidationError) as caught:model.model_validate(value)
 message=' '.join(item['msg'] for item in caught.value.errors())
 assert '<root>'+''.join('['+json.dumps(p)+']'for p in row['path'])in message
 assert 'pass the value as text'not in message
 assert ('not declared' if row['type']=='undeclared' else 'requires a JSON ')in message

from hiitl.core.tests.handback_assertions import public_error

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.core.numeric_domain import NumericDomainError
from hiitl.sdk.tests.test_numeric_boundaries import ENV,POL
@pytest.mark.parametrize('row',[r for r in ROWS if r['format']in ('envelope','policy')],ids=lambda r:r['id'])
def test_evaluator_numeric_remedy_reads_owning_input_declaration(row):
 terms={'envelope':copy.deepcopy(ENV),'policy':copy.deepcopy(POL)};terms[row['format']]=copy.deepcopy(row['control'])
 PolicyEvaluator().evaluate(**terms)
 at=terms[row['format']]
 for part in row['path'][:-1]:at=at[part]
 at[row['path'][-1]]=NUMERIC_BOUND
 with public_error(NumericDomainError)as caught:PolicyEvaluator().evaluate(**terms)
 assert caught.value.path==(row['format'],*row['path'])
 assert 'JSON '+row['type']in str(caught.value)
 assert 'pass the value as text'not in str(caught.value)
