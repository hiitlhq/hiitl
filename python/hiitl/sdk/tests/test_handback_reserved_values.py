"""88579bbd: the owning policy sentence, exercised through both real formats."""
import copy,json
from pathlib import Path
import pytest,yaml
from hiitl.sdk.policy_loader import PolicyLoader
from hiitl.sdk.exceptions import PolicyLoadError
from hiitl.core.types import Envelope,PolicySet
ROOT=Path(__file__).resolve().parents[4]
ROWS=json.loads((ROOT/'tests/conformance/reserved_policy_values/cases.json').read_text())['cases']
@pytest.mark.parametrize('row',ROWS,ids=lambda r:r['id'])
@pytest.mark.parametrize('format',['json','yaml'])
def test_policy_reserved_forms(row,format,tmp_path):
 path=tmp_path/('policy.'+format)
 write=lambda data:path.write_text(json.dumps(data)if format=='json'else yaml.safe_dump(data))
 write(row['control']);assert PolicyLoader(path).load().name==row['control']['name']
 write(row['input'])
 if row['accept']:assert PolicyLoader(path).load().name==row['input']['name']
 else:
  with public_error(PolicyLoadError)as error:PolicyLoader(path).load()
  assert error.value.reason=='POLICY_VALIDATION_ERROR'
  assert '$' in str(error.value)

def test_documented_envelope_round_trip_keeps_caller_markers():
 raw=json.loads((ROOT/'tests/conformance/cases/references/test_143_field_reference_equals_compares_two_fields.json').read_text())['envelope']
 raw['parameters']={key:{'kept':None}for key in ['$field','$declared','$uncalibrated']}
 env=Envelope.model_validate(raw)
 for mode in ['python','json']:
  restored=Envelope.model_validate(env.model_dump(mode=mode,exclude_none=True))
  assert restored.model_dump(mode='json',exclude_none=True)==env.model_dump(mode='json',exclude_none=True)
  assert restored.parameters==raw['parameters']
 assert 'model_dump(exclude_none=True)'in(ROOT/'python/CHANGELOG.md').read_text()

from hiitl.core.tests.handback_assertions import public_error


@pytest.mark.parametrize('format', ['json', 'yaml'])
def test_compiled_provenance_keeps_exact_source_and_form_rules(format, tmp_path):
    """951c24a0: the source and its declared copy read the same forms, never new operands."""
    from hiitl.core.evaluator import evaluate
    from hiitl.core.lint import lint, promotion_refusal

    witness = next(row for row in json.loads(
        (ROOT / 'tests/conformance/input_contract/policy-witnesses.json').read_text()
    )['witnesses'] if row['id'] == 'legacy-placeholder-bounds')['input']
    source = copy.deepcopy(witness)
    entry = source['metadata']['rate_limits'][0]
    path = tmp_path / ('provenance.' + format)

    def load(data):
        path.write_text(json.dumps(data) if format == 'json' else yaml.safe_dump(data))
        return PolicyLoader(path).load()

    try:
        compiled = load(source)
        encoded = compiled.model_dump(mode='json', exclude_none=True)
        reloaded = load(encoded)
    except PolicyLoadError as error:
        pytest.fail(f'The admitted source and serialized provenance must load: {error}')
    assert source == witness
    assert 'rate_limits' not in encoded['metadata']
    envelope = json.loads((ROOT / 'tests/conformance/cases/references/test_143_field_reference_equals_compares_two_fields.json').read_text())['envelope']
    envelope.update(source['scope'])
    for policy in (compiled, reloaded):
        rule = next(rule for rule in policy.rules if rule.name == 'metadata.rate_limits[0]')
        assert rule.metadata['compiled_from'] == {'path': rule.name, 'entry': entry}
        assert rule.rate_limit.limit == entry['limit']
        assert rule.rate_limit.window_seconds == entry['window_seconds']
        only = policy.model_copy(update={'rules': [rule]})
        decision = evaluate(envelope, only)
        assert not decision.matched_rules
        assert not decision.rate_limit_rules
        assert any(f.code == 'UNCALIBRATED' and f.rule == rule.name for f in lint(only))
        assert promotion_refusal(only, rule.name)[0] == 'RULE_UNCALIBRATED'

    # Only the typed bound is consumed. Provenance remains intact when it is set.
    calibrated = copy.deepcopy(encoded)
    calibrated['rules'] = [calibrated['rules'][-1]]
    calibrated['rules'][0]['rate_limit'].update(limit=10, window_seconds=60)
    live = load(calibrated)
    assert [rule.rule_name for rule in evaluate(envelope, live).rate_limit_rules] == ['metadata.rate_limits[0]']
    assert not any(f.code == 'UNCALIBRATED' for f in lint(live))
    assert promotion_refusal(live, 'metadata.rate_limits[0]') is None

    for stage in ('source', 'copy'):
        for member in ('limit', 'window_seconds'):
            for marker in ('$field', '$declared', '$uncalibrated'):
                for sibling in (False, True):
                    data = copy.deepcopy(source if stage == 'source' else encoded)
                    held = data['metadata']['rate_limits'][0] if stage == 'source' else data['rules'][-1]['metadata']['compiled_from']['entry']
                    held[member] = {marker: 'the bound'}
                    if sibling:
                        held[member]['note'] = 'not a form'
                    if marker == '$uncalibrated' and not sibling:
                        assert load(data).name == witness['name']
                    else:
                        with public_error(PolicyLoadError) as error:
                            load(data)
                        assert error.value.reason == 'POLICY_VALIDATION_ERROR'
                        assert marker in str(error.value)

    for misplaced in ('set-copy', 'rule-entry', 'copy-note', 'entry-note'):
        data = copy.deepcopy(encoded)
        metadata = data['rules'][-1]['metadata']
        if misplaced == 'set-copy':
            data['metadata']['compiled_from'] = metadata.pop('compiled_from')
        elif misplaced == 'rule-entry':
            metadata['entry'] = metadata.pop('compiled_from')['entry']
        elif misplaced == 'copy-note':
            metadata['compiled_from']['note'] = {'$uncalibrated': 'not a bound'}
        else:
            metadata['compiled_from']['entry']['note'] = {'$uncalibrated': 'not a bound'}
        with public_error(PolicyLoadError) as error:
            load(data)
        assert error.value.reason == 'POLICY_VALIDATION_ERROR'
        assert '$uncalibrated' in str(error.value)
