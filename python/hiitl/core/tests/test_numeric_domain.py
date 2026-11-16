"""HTL43 d82fe0f5: held numbers; supplied admission and unchanged historical C (93d/5203)."""
import importlib
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import pytest
from hiitl.core.canonical import (canonical_json, canonical_hash, audit_content_hash,
    envelope_signed_form, envelope_signature, envelope_hash, envelope_verifies)
from hiitl.core.numeric_domain import validate_numeric_domain

ROOT = Path(__file__).resolve().parents[4]
CORPUS = json.loads((ROOT/'tests/conformance/numeric_domain/cases.json').read_text())
CASES = CORPUS['cases']

def value(row):
    if row['kind'] == 'native': return float(row['input'])
    return json.loads(row['input'])

def wrapped(v, form):
    if form == 'root': return v, ()
    if form == 'object': return {'plain': True, 'sample': v}, ('sample',)
    return {'outer': [{'ok': None}, {'sample': v}]}, ('outer',1,'sample')

@pytest.mark.parametrize('row', CASES, ids=lambda r:r['id'])
@pytest.mark.parametrize('form', ['root','object','array-object'])
def test_supplied_boundary_reads_every_held_number(row, form):
    v, path = wrapped(value(row), form)
    if row['expected_accept']:
        validate_numeric_domain(v)
        actual = canonical_json(v)
        expected = row['canonical']
        if form == 'object': expected = '{"plain":true,"sample":'+expected+'}'
        if form == 'array-object': expected = '{"outer":[{"ok":null},{"sample":'+expected+'}]}'
        assert actual == expected
    else:
        with pytest.raises(ValueError) as e: validate_numeric_domain(v)
        assert getattr(e.value, 'path', None) == path
        assert 'text' in str(e.value).lower()

# 93d/5203: the former public hash/sign admission expectation is explicitly
# superseded. Fixed pre-rule bytes remain the oracle; new inputs are admitted above.
@pytest.mark.parametrize('name', ['canonical_hash','audit_content_hash','envelope_signed_form','envelope_signature','envelope_hash'])
def test_hash_and_sign_boundaries_compute_historical_form(name):
    case=json.loads((ROOT/'tests/conformance/audit_hash/case_001_fixed_record.json').read_text())
    envelope=case['envelope']; canonical=case['expected']['canonical_envelope']
    signed=canonical.replace(',"signature":"'+envelope['signature']+'"','')
    secret='local-fixture-key'
    expected_signature=hmac.new(secret.encode(),signed.encode(),hashlib.sha256).hexdigest()
    calls = {
        'canonical_hash': (lambda: canonical_hash(envelope), hashlib.sha256(canonical.encode()).hexdigest()),
        'audit_content_hash': (lambda: audit_content_hash(case['event_id'],envelope,case['decision']), case['expected']['content_hash']),
        'envelope_signed_form': (lambda: envelope_signed_form(envelope), signed),
        'envelope_signature': (lambda: envelope_signature(secret,envelope), expected_signature),
        'envelope_hash': (lambda: envelope_hash(envelope), hashlib.sha256(signed.encode()).hexdigest()),
    }
    call,expected=calls[name]
    error=None; actual=None
    try: actual=call()
    except Exception as caught: error=caught
    assert error is None, f"historical C must remain computable: {error}"
    assert actual==expected
    assert envelope_verifies(secret,{**envelope,'signature':expected_signature})

def test_pure_numeric_guard_preserves_open_data_and_reports_exact_path():
    assert importlib.util.find_spec('hiitl.core.numeric_domain') is not None, 'shared numeric guard is required'
    module = importlib.import_module('hiitl.core.numeric_domain')
    original = {'__proto__': [True, None, '9007199254740993', {'fraction':0.1}]}
    before = json.dumps(original)
    assert module.validate_numeric_domain(original) is None
    assert json.dumps(original) == before
    with pytest.raises(module.NumericDomainError) as e:
        module.validate_numeric_domain({'__proto__':[CORPUS['bound']]}, ('input',))
    assert e.value.path == ('input','__proto__',0)

def test_python_integer_is_refused_with_normal_path_before_float_conversion():
    from hiitl.core.numeric_domain import NumericDomainError, validate_numeric_domain
    error=None
    try:validate_numeric_domain({'huge':10**400})
    except Exception as caught:error=caught
    assert isinstance(error,NumericDomainError), 'oversized integer uses the normal named refusal, not conversion overflow'
    assert error.path==('huge',)

from hiitl.core.canonical import AUDIT_FURTHER
@pytest.mark.parametrize('member',['envelope','decision',*AUDIT_FURTHER])
def test_each_supplied_audit_term_is_admitted_before_hashing(member):
    data={'envelope':{},'decision':{}};data[member]={'probe':CORPUS['bound']}
    with pytest.raises(ValueError) as error:
        validate_numeric_domain(data)
    assert getattr(error.value,'path',None)==(member,'probe')

@pytest.mark.parametrize('member',['envelope','decision',*AUDIT_FURTHER])
def test_each_historical_audit_term_is_computed_under_c(member):
    """A hash term is history whichever member carries it; C admits this finite number."""
    data={'envelope':{},'decision':{}};data[member]={'probe':CORPUS['bound']}
    fixed='{\"probe\":'+str(CORPUS['bound'])+'}'
    terms=['evt_numeric',fixed if member=='envelope' else '{}',fixed if member=='decision' else '{}']
    if member in AUDIT_FURTHER:terms.append(fixed)
    expected=hashlib.sha256(':'.join(terms).encode()).hexdigest()
    error=None;actual=None
    try:actual=audit_content_hash('evt_numeric',data.pop('envelope'),data.pop('decision'),**data)
    except Exception as caught:error=caught
    assert error is None, f'every stored term uses unchanged C: {error}'
    assert actual==expected
