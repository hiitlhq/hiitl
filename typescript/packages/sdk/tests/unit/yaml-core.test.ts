/** Gap263: one YAML1.2 Core corpus through actual policy/route file loaders. */
import { readFileSync, writeFileSync, unlinkSync, mkdtempSync, rmSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { tmpdir } from 'node:os';
import yaml from 'js-yaml';
import { it, expect, beforeAll, afterAll } from 'vitest';
import { PolicyEvaluator, ENVELOPE_SCHEMA_VERSION } from '@hiitl/core';
import { PolicyLoader, loadYaml } from '../../src/policy-loader.js';
import { RouteLoader } from '../../src/route-loader.js';
const root=resolve(__dirname,'../../../../../');
type Row={id:string;input:string;expected_accept:boolean;expected?:unknown};
const cases:Row[]=JSON.parse(readFileSync(join(root,'tests/conformance/yaml_core/cases.json'),'utf8')).cases;
const route=JSON.parse(readFileSync(join(root,'tests/conformance/typed_members/witnesses.json'),'utf8')).witnesses[0].input;
const policy={name:'scalar-policy',version:'v1.0.0',description:'YAML scalar contract',scope:{org_id:'org_1234567890abcdef',environment:'dev'},rules:[{name:'scalar-equality',description:'read declared scalar',priority:1,lifecycle_stage:'active',conditions:{field:'parameters.probe',operator:'equals',value:['SCALAR_VALUE']},decision:'ALLOW',reason_code:'SCALAR_EQUAL'}]};
const envelope={schema_version:ENVELOPE_SCHEMA_VERSION,org_id:'org_1234567890abcdef',environment:'dev',agent_id:'fixture',action_id:'act_01234567890123456789',idempotency_key:'scalar',action:'read',operation:'execute',target:{},parameters:{},timestamp:'2026-11-14T00:00:00Z',signature:'0'.repeat(64)};
function sameScalar(actual:unknown,expected:unknown):void{expect(typeof actual).toBe(typeof expected);expect(actual===expected).toBe(true);}
let original:string|undefined;
beforeAll(()=>{original=process.env.HTL41_ROUTE_FIXTURE;process.env.HTL41_ROUTE_FIXTURE='local-route-fixture';});
afterAll(()=>{if(original===undefined)delete process.env.HTL41_ROUTE_FIXTURE;else process.env.HTL41_ROUTE_FIXTURE=original;});
it.each(cases)('$id is read by the shared YAML reader',(row)=>{
  if(row.expected_accept){
    let parsed:unknown,error:unknown;
    try{parsed=(loadYaml('probe: '+row.input+'\n') as {probe:unknown}).probe;}catch(caught){error=caught;}
    expect(error,`declared accepted scalar ${row.id} was refused`).toBeUndefined();
    sameScalar(parsed,row.expected);
  }
  else expect(()=>loadYaml('probe: '+row.input+'\n')).toThrow(/text/);
});
for(const surface of ['policy','route'])it.each(cases)(surface+' $id has JSON control',(row)=>{
  const dir=mkdtempSync(join(tmpdir(),'hiitl-yaml-contract-'));
  try{
    const doc=structuredClone(surface==='policy'?policy:route);if(surface==='route')doc.metadata.probe='SCALAR_VALUE';
    const expected=row.expected_accept?row.expected:0;
    const controlDoc=structuredClone(doc);
    if(surface==='policy')controlDoc.rules[0].conditions.value=[expected];else controlDoc.metadata.probe=expected;
    let path=join(dir,doc.name+'.json');writeFileSync(path,JSON.stringify(controlDoc));
    const read=():any=>surface==='policy'?new PolicyLoader(path).load():new RouteLoader(dir).get(doc.name);
    const control=read();sameScalar(surface==='policy'?control.rules[0].conditions.value[0]:control.metadata.probe,expected);
    const env={...envelope,parameters:{probe:[expected]}};
    if(surface==='policy')expect(new PolicyEvaluator().evaluate(env,control).decision).toBe('ALLOW');
    unlinkSync(path);path=join(dir,doc.name+'.yaml');writeFileSync(path,yaml.dump(doc).replace('SCALAR_VALUE',row.input));
    if(!row.expected_accept){expect(read).toThrow(/(probe|value).*text/);return;}
    const result=read();
    if(surface==='policy'){
      sameScalar(result.rules[0].conditions.value[0],expected);
      expect(new PolicyEvaluator().evaluate(env,result).decision).toBe('ALLOW');
    }else sameScalar(result.metadata.probe,expected);
  }finally{rmSync(dir,{recursive:true,force:true});}
});

it.each([['!!int 017',17],['!!int 0o17',15],['!!float 1e3',1000],['!!bool TRUE',true],['!!null Null',null],['!!str on','on']])('explicit %s uses Core grammar',(raw,expected)=>{
  sameScalar((loadYaml('probe: '+raw) as {probe:unknown}).probe,expected);
});
it.each(['!!bool yes','!!int 1_000','!!int 1:20','!!int 0b10','!!float 1_0.0','!!null nope','!!timestamp 2026-11-14'])('explicit %s cannot restore old scalar rules',raw=>{
  expect(()=>loadYaml('probe: '+raw)).toThrow();
});
