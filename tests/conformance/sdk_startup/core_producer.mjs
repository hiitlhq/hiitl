import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {schemaProducers} from './schema_producers.mjs';
const [root,fixture]=process.argv.slice(2);
const policy=JSON.parse(readFileSync(join(fixture,'policy.json'),'utf8'));
const events=[];let phase='imports';const actual=globalThis.Function;
const schemaObserver=schemaProducers(events);
globalThis.Function=new Proxy(actual,{construct(target,args,newTarget){
  events.push({phase,producer:'Function',stack:new Error().stack});
  return Reflect.construct(target,args,newTarget);
}});
try {
  const {PolicyEvaluator,ENVELOPE_SCHEMA_VERSION}=await import(pathToFileURL(join(root,'typescript/packages/core/dist/index.js')));
  schemaObserver.read('imports');
  phase='construction';const evaluator=new PolicyEvaluator();
  schemaObserver.read('construction');
  const envelope={schema_version:ENVELOPE_SCHEMA_VERSION,org_id:policy.scope.org_id,environment:policy.scope.environment,agent_id:'startup',
    action_id:'act_01HQZ6X8Z9P5ABCDEFGHIJK',idempotency_key:'idem_core_startup',action:'guarded',operation:'execute',
    target:{},parameters:{amount:100},timestamp:'2026-11-16T00:00:00Z',signature:'a'.repeat(64)};
  phase='first';const first=evaluator.evaluate(envelope,policy);
  schemaObserver.read('first');
  phase='repeated';const repeated=evaluator.evaluate(envelope,policy);
  schemaObserver.read('repeated');
  console.log('HTL45_CORE_PRODUCERS '+JSON.stringify({events,first:first.decision,repeated:repeated.decision}));
} finally {schemaObserver.close();globalThis.Function=actual;}
