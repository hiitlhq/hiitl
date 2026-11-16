"""Fixed source-derived inputs shared by the real Python model/file readers."""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


@lru_cache
def corpus():
    return json.loads((ROOT / 'tests/conformance/input_contract/cases.json').read_text())


def cases(*formats):
    return [case for case in corpus()['cases'] if case['format'] in formats]

