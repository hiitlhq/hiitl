import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DATA=json.loads((ROOT/'tests/conformance/date_text/cases.json').read_text())
ORIGINAL=json.loads((ROOT/'tests/conformance/date_text/lexical-original.json').read_text())
LEXICAL=[row for row in ORIGINAL if not row.get('native')]
def at(value,path):
    for key in path:value=value[key] if isinstance(value,(dict,list)) else getattr(value,key)
    return value

HASHES=json.loads((ROOT/'tests/conformance/date_text/hash-vectors.json').read_text())['cases']
