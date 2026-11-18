"""Fresh direct-core declaration producers; no SDK constructor pays for them."""
import ast, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
builders=set()
for source in (ROOT/'python/hiitl/core').glob('*.py'):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and any('lru_cache' in ast.unparse(d) for d in node.decorator_list):
            builders.add((str(source),node.name))
events=[];phase='imports'
def observe(frame,event,arg):
    code=frame.f_code
    if event=='call' and ((code.co_filename,code.co_name) in builders or code.co_name in ('model_json_schema','json_schema') and 'pydantic' in code.co_filename):
        events.append({'phase':phase,'producer':code.co_name,'file':code.co_filename,
                       'owner':str(frame.f_locals.get('cls',frame.f_locals.get('model','')))})
sys.setprofile(observe)
try:
    from hiitl.core.evaluator import PolicyEvaluator
    from hiitl.core.types import ENVELOPE_SCHEMA_VERSION
    phase='construction';evaluator=PolicyEvaluator()
    policy=json.loads((Path(__file__).parent/'policy.json').read_text())
    envelope=dict(schema_version=ENVELOPE_SCHEMA_VERSION,org_id=policy['scope']['org_id'],environment=policy['scope']['environment'],agent_id='startup',
                  action_id='act_01HQZ6X8Z9P5ABCDEFGHIJK',idempotency_key='idem_core_startup',action='guarded',operation='execute',
                  target={},parameters={'amount':100},timestamp='2026-11-16T00:00:00Z',signature='a'*64)
    phase='first';first=evaluator.evaluate(envelope,policy)
    phase='repeated';repeated=evaluator.evaluate(envelope,policy)
finally: sys.setprofile(None)
print('HTL45_CORE_PRODUCERS '+json.dumps({'events':events,'first':str(first.decision),'repeated':str(repeated.decision)}))
