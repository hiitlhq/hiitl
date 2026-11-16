"""HTL-39 independent Python reading of the shared source and input witnesses."""
import copy
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / 'tests/conformance/route_defaults'

def schema_from_markdown(text):
    sections = re.split(r'^### JSON Schema\s*$', text, flags=re.M)
    if len(sections) != 2:
        raise ValueError('expected one JSON Schema heading')
    match = re.search(r'^\s*```json\s*\n([\s\S]*?)\n```', sections[1], re.M)
    if not match:
        raise ValueError('missing JSON Schema fence')
    return json.loads(match[1])

ROUTE_SCHEMA = schema_from_markdown((ROOT / 'docs/specs/routes.md').read_text())
DECISION_SCHEMA = schema_from_markdown((ROOT / 'docs/specs/decision_response.md').read_text())
WITNESSES = json.loads((DATA / 'witnesses.json').read_text())['witnesses']

def _escape(key):
    return str(key).replace('~', '~0').replace('/', '~1')

def _read_document(file):
    return json.loads((ROOT / 'docs/specs' / file).read_text())

def _deref(root, node, address, documents=_read_document):
    references, seen = [], set()
    while '$ref' in node:
        ref = node['$ref']
        file, fragment = ref.split('#', 1)
        if not fragment.startswith('/') or (file and re.search(r'[/:]', file)):
            raise ValueError(f'unsupported reference {ref}')
        document = documents(file) if file else root
        address = f"{file or address.split('#')[0]}#{fragment}"
        if address in seen:
            raise ValueError(f'recursive schema at {address}')
        seen.add(address)
        node = document
        for part in fragment[1:].split('/'):
            node = node[part.replace('~1', '/').replace('~0', '~')]
        references.append((address, node))
        root = document
    return node, address, root, references

def defaults(root, documents=_read_document):
    rows, visited, referenced = [], set(), {}
    def walk(document, raw, path, raw_address, ancestors=()):
        node, address, owner, references = _deref(document, raw, raw_address, documents)
        referenced.update(references)
        if address in ancestors:
            raise ValueError(f'recursive schema at {address}')
        if 'default' in node:
            rows.append({'path': path, 'value': copy.deepcopy(node['default']), 'address': address})
            visited.add(address)
        for key, child in node.get('properties', {}).items():
            walk(owner, child, path + [key], f'{address}/properties/{_escape(key)}', (*ancestors, address))
        if 'items' in node:
            walk(owner, node['items'], path + ['*'], f'{address}/items', (*ancestors, address))
    walk(root, root, [], '#')
    def declarations(node, address='#'):
        if isinstance(node, dict):
            if 'default' in node and address not in visited:
                raise ValueError(f'unread default declaration {address}')
            for key, child in node.items():
                if key != 'default':
                    declarations(child, f'{address}/{_escape(key)}')
        elif isinstance(node, list):
            for index, child in enumerate(node):
                declarations(child, f'{address}/{index}')
    declarations(root)
    for address, target in referenced.items():
        declarations(target, address)
    return rows

def apply_defaults(root, value, raw=None):
    node, _, document, _ = _deref(root, root if raw is None else raw, '#')
    value = copy.deepcopy(value)
    if isinstance(value, list):
        return [apply_defaults(document, item, node.get('items', {})) for item in value]
    if isinstance(value, dict):
        for key, child in node.get('properties', {}).items():
            resolved, _, _, _ = _deref(document, child, '#')
            if key not in value and 'default' in resolved:
                value[key] = copy.deepcopy(resolved['default'])
            if key in value:
                value[key] = apply_defaults(document, value[key], child)
    return value

def _parents(value, path):
    if not path:
        return [(value, [])]
    key, *rest = path
    if key == '*':
        return [(parent, [i, *p]) for i, item in enumerate(value) for parent, p in _parents(item, rest)] if isinstance(value, list) else []
    return [(parent, [key, *p]) for parent, p in _parents(value[key], rest)] if isinstance(value, dict) and key in value else []

def omission_cases(root=ROUTE_SCHEMA, inputs=WITNESSES):
    rows = []
    for declaration in defaults(root):
        generated = []
        for witness in inputs:
            if witness.get('omit_defaults') is False:
                continue
            for parent, parent_path in _parents(witness['input'], declaration['path'][:-1]):
                if not isinstance(parent, dict):
                    continue
                value = copy.deepcopy(witness['input'])
                container = value
                for key in parent_path:
                    container = container[key]
                path = [*parent_path, declaration['path'][-1]]
                container.pop(path[-1], None)
                generated.append({'id': f"{'.'.join(declaration['path'])}@{witness['id']}:{'.'.join(map(str,parent_path))}", 'path':path, 'declaration':declaration['address'], 'input':value, 'expected':apply_defaults(root,value)})
        if not generated:
            raise ValueError(f"no omission witness for {'.'.join(declaration['path'])} ({declaration['address']})")
        rows.extend(generated)
    return rows

def expected_context(route, schema=DECISION_SCHEMA):
    result = {}
    for key, node in schema['properties']['escalation_context']['properties'].items():
        match = re.match(r"^The route's `([^`]+)`", node['description'])
        if not match:
            raise ValueError(f'unread context projection {key}')
        value = route
        for part in match[1].split('.'):
            if not isinstance(value, dict) or part not in value:
                break
            value = value[part]
        else:
            result[key] = copy.deepcopy(value)
    return result

def all_cases():
    return omission_cases() + [{'id':w['id'], 'input':copy.deepcopy(w['input']), 'expected':apply_defaults(ROUTE_SCHEMA,w['input'])} for w in WITNESSES]
