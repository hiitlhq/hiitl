/** Raw model roots apply the shared numeric declaration before any projection/default. */
import { readFileSync } from 'node:fs';
import { expect,it } from 'vitest';
import { EnvelopeSchema,PolicySetSchema,DecisionSchema } from '../../src/types.js';
import { RouteSchema } from '../../src/route-types.js';
import { envelopeInput,policyInput,routeInput } from '../../../../test-support/own-data.js';
const corpus=JSON.parse(readFileSync(new URL('../../../../../tests/conformance/numeric_domain/cases.json',import.meta.url),'utf8')) as {cases:{id:string;kind:string;input:string;expected_accept:boolean}[]};
const forms=[
  {name:'envelope',schema:EnvelopeSchema,input:(v:unknown)=>envelopeInput({parameters:{held:[v]}}),path:['parameters','held',0]},
  {name:'policy',schema:PolicySetSchema,input:(v:unknown)=>({...policyInput(),metadata:{held:[v]}}),path:['metadata','held',0]},
  {name:'route',schema:RouteSchema,input:(v:unknown)=>({...routeInput(),metadata:{held:[v]}}),path:['metadata','held',0]},
  {name:'decision',schema:DecisionSchema,input:(v:unknown)=>({action_id:'act_fixture000000000000',decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0},escalation_context:{held:[v]}}),path:['escalation_context','held',0]},
];
for(const form of forms)for(const row of corpus.cases)it(`${form.name} root reads held numeric case ${row.id}`,()=>{
  const value=row.kind==='native'?Number(row.input):JSON.parse(row.input);
  const result=form.schema.safeParse(form.input(value));
  expect(result.success).toBe(row.expected_accept);
  if(!result.success){expect(result.error.issues.map(issue=>issue.path)).toContainEqual(form.path);expect(result.error.message).toMatch(/pass.*text/i);}
});
