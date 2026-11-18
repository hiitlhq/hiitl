from pathlib import Path
import json
from .json_comparison_support import inputs as comparison_inputs
ROOT=Path(__file__).resolve().parents[4]
DATA=json.loads((ROOT/'tests/conformance/operator_kinds/cases.json').read_text())

def inputs(row):
    policy,envelope=comparison_inputs(row)
    if row['reference']:
        policy['rules'][0]['conditions']['value']={'$field':'parameters.other'}
        envelope['parameters']['other']=row['right']
    return policy,envelope

def evaluated(evaluator,envelope,policy):
    try:return {'stage':'decision','matched':evaluator.evaluate(envelope,policy).allowed},None
    except Exception as error:
        return {'stage':'operand' if type(error).__name__=='OperatorKindError' else type(error).__name__},error

def assert_named(error,row):
    if type(error).__name__=='OperatorKindError':
        assert 'Correct the field value or policy to use the operator’s declared operand kinds.' in str(error)
    assert row['operator'] in str(error)
    assert 'parameters.probe' in str(error)
    if row['reference']:assert 'parameters.other' in str(error)
