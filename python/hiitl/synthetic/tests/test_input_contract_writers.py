"""HTL-43: synthetic owned output is a valid sparse canonical envelope."""
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from hiitl.synthetic.agent_loader import AgentPersona
from hiitl.synthetic.envelope_factory import EnvelopeFactory
from hiitl.synthetic import cli


def persona_data():
    return {
        'agent_id': 'agent', 'name': 'Agent', 'description': 'Sparse fixture',
        'behavior_profile': {'tools': ['send'], 'action_frequency': {'send': 1},
                             'parameter_distributions': {}},
        'sensitivity_flags': {},
    }


def test_factory_omits_absent_sensitivity():
    try:
        envelope = EnvelopeFactory(AgentPersona(persona_data()), seed=1).generate_one('send')
    except ValidationError as error:
        raise AssertionError(f'valid synthetic input was refused: {error}') from error
    assert 'sensitivity' not in envelope.model_fields_set
    assert envelope.parameters == {}


def test_cli_generated_json_obeys_canonical_envelope(tmp_path):
    (tmp_path / 'agent.json').write_text(json.dumps(persona_data()))
    output = tmp_path / 'envelopes.jsonl'
    args = argparse.Namespace(agents_dir=str(tmp_path), agent_id='agent', org_id='org_inputcontract0001', environment='dev',
                              seed=1, count=1, output=str(output))
    cli.cmd_generate(args)
    lines = output.read_text().splitlines()
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    schema = json.loads((Path(__file__).resolve().parents[4] / 'docs/specs/envelope_schema.json').read_text())
    errors = list(Draft202012Validator(schema).iter_errors(envelope))
    assert errors == [], [(list(error.path), error.message) for error in errors]
    assert envelope['parameters'] == {}
    assert 'sensitivity' not in envelope

