"""The declared input-case role shared by carried-artifact readers.

The case contract is in tests/conformance/input_contract/TEST_DESIGN.md.
Only a complete negative case gives its input to the refusal runner; this
predicate says nothing about excluding its control or any positive input.
"""


def is_refusal_case(node) -> bool:
    if not isinstance(node, dict):
        return False
    reserved_keys = {'id', 'input', 'control', 'accept', 'path', 'cause'}
    if node.keys() == reserved_keys:
        return (all(isinstance(node[key], str) for key in ('id', 'cause'))
                and all(isinstance(node[key], dict) for key in ('input', 'control'))
                and isinstance(node['path'], list)
                and all(isinstance(part, (str, int)) and not isinstance(part, bool) for part in node['path'])
                and node['accept'] is False)
    case_keys = {'format', 'id', 'declaration', 'path', 'control', 'input', 'expected_accept', 'kind'}
    return (case_keys <= node.keys() <= case_keys | {'subtype'}
            and node['format'] in ('envelope', 'policy', 'routes')
            and all(isinstance(node[key], str) for key in ('id', 'declaration', 'kind'))
            and isinstance(node['path'], list)
            and all(isinstance(part, (str, int)) and not isinstance(part, bool) for part in node['path'])
            and node['expected_accept'] is False)
