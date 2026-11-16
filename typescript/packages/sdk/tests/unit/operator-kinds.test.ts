import {expect,it,afterEach} from 'vitest';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import yaml from 'js-yaml';
import {PolicyEvaluator, ERROR_MESSAGES} from '@hiitl/core';
import {PolicyLoader} from '../../src/policy-loader.js';
import {HIITL} from '../../src/client.js';
import {operandData,operandInputs,evaluateAnswer,prototypeSnapshot} from '../../../../test-support/operator-kinds.js';
const dirs:string[]=[];const clients:HIITL[]=[];
afterEach(()=>{clients.splice(0).forEach(c=>c.close());dirs.splice(0).forEach(d=>rmSync(d,{recursive:true,force:true}));});
function file(policy:any,wire:string){const dir=mkdtempSync(join(tmpdir(),'operator-kind-'));dirs.push(dir);const path=join(dir,`policy.${wire}`);writeFileSync(path,wire==='json'?JSON.stringify(policy):yaml.dump(policy));return path;}
for(const wire of ['json','yaml'])it.each(operandData.cases)(`file operand answer ${wire}: $id`,row=>{
  const {policy,envelope}=operandInputs(row);let loaded;
  try{loaded=new PolicyLoader(file(policy,wire)).load();}
  catch(error){expect(row.expected).toEqual({stage:'load'});expect(String(error)).toContain(row.operator);expect(String(error)).toContain('parameters.probe');return;}
  const {actual,error}=evaluateAnswer(new PolicyEvaluator(),envelope,loaded);expect(actual).toEqual(row.expected);
  if(error){expect(error.message).toContain(row.operator);expect(error.message).toContain('parameters.probe');if(row.reference)expect(error.message).toContain('parameters.other');}
});
it.each(['RESPECT_POLICY','OBSERVE_ALL'])('public refusal records the named operator and fields: %s',mode=>{
  const row={operator:'greater_than',left:'private-operand-value',right:1,reference:true};const {policy,envelope}=operandInputs(row);
  const client=new HIITL({org_id:envelope.org_id,environment:envelope.environment,agent_id:envelope.agent_id,policy_path:file(policy,'json'),audit_db_path:':memory:',mode:mode as any});clients.push(client);
  const decision=client.evaluate({action:envelope.action,parameters:envelope.parameters}) as any;
  expect([decision.decision,decision.allowed,decision.reason_codes,decision.error?.code]).toEqual(['POLICY_ERROR',false,['POLICY_EVALUATION_FAILED'],'POLICY_ERROR']);
  expect(decision.error.message).toContain('greater_than');expect(decision.error.message).toContain('parameters.probe');expect(decision.error.message).toContain('parameters.other');expect(decision.error.message).not.toContain(row.left);
  const records=(client as any).auditLogger.getUnsynced(10);expect(records.map((r:any)=>r.decision.decision)).toEqual(['POLICY_ERROR']);expect(records[0].decision.error.message).toBe(decision.error.message);
});

for(const source of ['local','hybrid','tick'])for(const generic of [false,true])it(`each evaluation entry maps only typed failures: ${source}/${generic}`,()=>{
  const row={operator:'greater_than',left:'private-operand-value',right:1,reference:true};const {policy,envelope}=operandInputs(row);
  const h=new HIITL({org_id:envelope.org_id,environment:envelope.environment,agent_id:envelope.agent_id,policy_path:file(policy,'json'),audit_db_path:':memory:',mode:'RESPECT_POLICY'});clients.push(h);const client=h as any;
  if(source!=='local')client.syncCache={tickPart:()=>source==='tick'?policy:null,getPolicySet:()=>policy,cacheStatus:()=>'synced'};
  if(generic)client.evaluator.evaluate=()=>{throw new Error('private-operand-value');};
  const decision=client.evaluate({action:envelope.action,parameters:envelope.parameters});
  expect([decision.decision,decision.allowed,decision.reason_codes]).toEqual(['POLICY_ERROR',false,['POLICY_EVALUATION_FAILED']]);
  if(generic)expect(decision.error.message).toBe(ERROR_MESSAGES.POLICY_EVALUATION_FAILED);
  else {expect(decision.error.message).toContain('greater_than');expect(decision.error.message).toContain('parameters.probe');expect(decision.error.message).toContain('parameters.other');}
  expect(decision.error.message).not.toContain('private-operand-value');
  expect(client.auditLogger.getUnsynced(10).map((r:any)=>r.decision.error.message)).toEqual([decision.error.message]);
});

it('route answer kind failure is recorded after actual reevaluation',async()=>{
  const {policy,envelope}=operandInputs({operator:'greater_than',left:0,right:1,reference:false});
  policy.rules[0].conditions.field='external.check.score';policy.rules[0].priority=800;
  policy.rules.push({...structuredClone(policy.rules[0]),name:'ask',priority:500,decision:'ROUTE',route:'check',conditions:{field:'action',operator:'equals',value:envelope.action}});
  const h=new HIITL({org_id:envelope.org_id,environment:envelope.environment,agent_id:envelope.agent_id,policy_path:file(policy,'json'),audit_db_path:':memory:',mode:'RESPECT_POLICY'});clients.push(h);const client=h as any;
  client.routeLoader={get:()=>({name:'check',direction:'bidirectional',response_schema:{required_fields:['score']}})};
  const asked:any[]=[];client._askRoute=async(_route:any,payload:any)=>{asked.push(payload);return {score:'private-operand-value'};};
  const decision=await client.evaluate({action:envelope.action,parameters:{}});
  expect(asked).toHaveLength(1);
  expect([decision.decision,decision.allowed,decision.reason_codes]).toEqual(['POLICY_ERROR',false,['POLICY_EVALUATION_FAILED']]);
  expect(decision.error.message).toContain('greater_than');expect(decision.error.message).toContain('external.check.score');expect(decision.error.message).not.toContain('private-operand-value');
  expect(client.auditLogger.getUnsynced(10).map((r:any)=>r.decision.error.message)).toEqual([decision.error.message]);
});

for(const [names,selected] of [[['A','a'],'A'],[['é','e\u0301'],'e\u0301'],[['😀','\ue000'],'\ue000']] as const)for(const reverse of [false,true])it(`multiple failures use code point order: ${names}/${reverse}`,()=>{
  const {policy,envelope}=operandInputs({operator:'greater_than',left:'invalid',right:1,reference:false});
  const conditions=names.map(name=>({field:'parameters.'+name,operator:'greater_than',value:1}));if(reverse)conditions.reverse();policy.rules[0].conditions={all_of:conditions};
  const h=new HIITL({org_id:envelope.org_id,environment:envelope.environment,agent_id:envelope.agent_id,policy_path:file(policy,'json'),audit_db_path:':memory:',mode:'RESPECT_POLICY'});clients.push(h);
  const decision=h.evaluate({action:envelope.action,parameters:Object.fromEntries(names.map(name=>[name,'invalid']))}) as any;
  expect([decision.decision,decision.allowed]).toEqual(['POLICY_ERROR',false]);
  expect(decision.error.message).toBe(`Operator \`greater_than\` has an operand of the wrong declared kind at field \`parameters.${selected}\`. Correct the field value or policy to use the operator’s declared operand kinds.`);
});

for(const wire of ['json','yaml'])for(const reference of [false,true])it.each(operandData.schema_cases)(`referenced parameter schema uses literal grammar ${wire}/${reference}: $id`,schema=>{
  const row={operator:'conforms_to',left:schema.left,right:schema.schema,reference};const {policy,envelope}=operandInputs(row);
  const expected=!reference&&!schema.valid_schema?{stage:'load'}:!schema.valid_schema&&schema.schema!==null?{stage:'operand'}:{stage:'decision',matched:schema.valid_schema?schema.matched:false};
  let loaded;try{loaded=new PolicyLoader(file(policy,wire)).load();}catch{expect(expected).toEqual({stage:'load'});return;}
  const graph={envelope,policy:loaded};const before=JSON.stringify(graph);const prototypes=prototypeSnapshot(graph);
  for(const entry of prototypes)expect(entry.prototype).toBe(entry.array?Array.prototype:Object.prototype);
  const {actual,error}=evaluateAnswer(new PolicyEvaluator(),envelope,loaded);expect(actual).toEqual(expected);
  expect(JSON.stringify(graph)).toBe(before);const after=prototypeSnapshot(graph);
  expect(after.map(entry=>entry.path)).toEqual(prototypes.map(entry=>entry.path));
  after.forEach((entry,index)=>expect(entry.prototype).toBe(prototypes[index].prototype));
  if(error){expect(error.message).toContain('conforms_to');expect(error.message).toContain('parameters.probe');expect(error.message).toContain('parameters.other');}
});

for(const wire of ['json','yaml'])it.each([{cost:{},expected:{stage:'decision',matched:true}},{cost:{dollars:1},expected:{stage:'operand'}}])(`declared object reference can be a schema ${wire}: $cost`,({cost,expected})=>{
  const {policy,envelope}=operandInputs({operator:'conforms_to',left:{},right:{},reference:true});policy.rules[0].conditions.value={$field:'cost_estimate'};envelope.cost_estimate=cost;
  const {actual,error}=evaluateAnswer(new PolicyEvaluator(),envelope,new PolicyLoader(file(policy,wire)).load());expect(actual).toEqual(expected);
  if(error){expect(error.message).toContain('conforms_to');expect(error.message).toContain('parameters.probe');expect(error.message).toContain('cost_estimate');}
});
