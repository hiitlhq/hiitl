"""Core construction obeys the same one-time setup sentence as an SDK."""
import json,os,subprocess,sys
from pathlib import Path

def test_fresh_core_builds_no_declaration_on_its_call_path(record_property):
    root=Path(__file__).resolve().parents[4]
    env={**os.environ,'PYTHONPATH':str(root/'python'),'PYTHONDONTWRITEBYTECODE':'1'}
    child=subprocess.run([sys.executable,str(root/'tests/conformance/sdk_startup/core_producer.py')],env=env,capture_output=True,text=True)
    assert child.returncode==0,(child.stdout,child.stderr)
    lines=[line.removeprefix('HTL45_CORE_PRODUCERS ')for line in child.stdout.splitlines()if line.startswith('HTL45_CORE_PRODUCERS ')]
    assert len(lines)==1
    row=json.loads(lines[0]);record_property('core_producers',json.dumps(row))
    assert not [e for e in row['events']if e['phase']not in ('imports','construction')],row
    assert any(e['phase']=='construction'for e in row['events']),row
    assert [row['first'],row['repeated']]==['BLOCK','BLOCK']
