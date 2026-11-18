"""Read the shared route inputs; expected null answers come from the source schema."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / 'tests/conformance/typed_members/route-null-cases.json'


def corpus():
    return json.loads(DATA.read_text())


def replace_with_null(control, path):
    value = copy.deepcopy(control)
    if not path:
        return None
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    # Reading first ensures an omitted member is never mistaken for explicit null.
    parent[path[-1]]
    parent[path[-1]] = None
    return value


def assert_named_path(error, path):
    """Inspect structured errors, never the input repr included in str(error)."""
    from pydantic import ValidationError
    current = error
    while current is not None:
        if isinstance(current, ValidationError):
            name = '.'.join(map(str, path)) or '<root>'
            token = re.compile(r'(?<![\w.])' + re.escape(name) + r'(?![\w.])')
            errors = current.errors()
            assert any(tuple(item['loc']) == tuple(path) or token.search(item['msg'])
                       for item in errors), {'path': path, 'errors': errors}
            return
        current = current.__cause__
    # The YAML parser refuses a null document before model construction. It still
    # identifies the entire document as the failed mapping rather than a child.
    assert path == [] and '<root>' in str(error)
