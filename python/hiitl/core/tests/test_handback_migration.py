"""Gap299: the documented omission-preserving dump is a real public round trip."""
import ast,json,re
from pathlib import Path
import pytest
from hiitl.core.types import Envelope
from hiitl.core.tests.handback_assertions import public_error
from pydantic import ValidationError
ROOT=Path(__file__).resolve().parents[4]
ROWS=json.loads((ROOT/'tests/conformance/input_contract/envelope-witnesses.json').read_text())['witnesses']

def forms():
 notes=(ROOT/'python/CHANGELOG.md').read_text().split('### Migration notes',1)[1]
 calls=re.findall(r'`(env\.model_dump\([^`]*\))`',notes)
 assert calls, 'Migration notes must show the real omission-preserving call'
 return calls

@pytest.mark.parametrize('row',ROWS,ids=lambda row:row['id'])
def test_migration_notes_dump_forms_round_trip(row):
 env=Envelope.model_validate(row['input'])
 calls=forms()
 assert {False,True}=={'mode="json"'in call for call in calls}
 for text in calls:
  call=ast.parse(text,mode='eval').body
  assert isinstance(call,ast.Call) and ast.unparse(call.func)=='env.model_dump' and not call.args
  kwargs={k.arg:ast.literal_eval(k.value)for k in call.keywords}
  assert kwargs.get('exclude_none')is True
  restored=Envelope.model_validate(env.model_dump(**kwargs))
  assert restored.model_dump(mode='json',exclude_none=True)==env.model_dump(mode='json',exclude_none=True)

def test_default_dump_materializes_disallowed_nulls():
 env=Envelope.model_validate(ROWS[0]['input'])
 with public_error(ValidationError):Envelope.model_validate(env.model_dump())
