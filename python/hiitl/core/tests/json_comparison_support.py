"""Shared source-derived operator answers; no production comparator supplies them."""
from pathlib import Path
from copy import deepcopy
import json
ROOT=Path(__file__).resolve().parents[4]
DATA=json.loads((ROOT/'tests/conformance/json_comparison/cases.json').read_text())

def inputs(row):
    policy=deepcopy(DATA['base']['policy']); envelope=deepcopy(DATA['base']['envelope'])
    policy['rules'][0]['conditions'].update(operator=row['operator'],value=deepcopy(row['right']))
    envelope['parameters']['probe']=deepcopy(row['left'])
    return policy,envelope

def outcome(decision):
    return {'decision':str(decision.decision),'allowed':decision.allowed,'reason_codes':decision.reason_codes}
