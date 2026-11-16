/** HTL-43: real file loaders, native option boundary and durable local record. */
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { dump } from 'js-yaml';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { EnvelopeSchema, PolicyEvaluator, envelopeVerifies, auditContentHash } from '@hiitl/core';
import type { Decision, Envelope } from '@hiitl/core';
import { PolicyLoader } from '../../src/policy-loader.js';
import { RouteLoader } from '../../src/route-loader.js';
import { HIITL } from '../../src/client.js';
import { EnvelopeValidationError } from '../../src/exceptions.js';
import { AuditLogger } from '../../src/audit.js';
import { ownData, envelopeInput, policyInput, routeInput } from '../../../../test-support/own-data.js';
import { readFileSync } from 'node:fs';

let directory:string;
function retained(actual:unknown,expected:Record<string,unknown>) {
  expect(Object.keys(actual as object).sort()).toStrictEqual(Object.keys(expected).sort());
  expect(Object.getPrototypeOf(actual)).toBe(Object.prototype);
  for(const key of Object.keys(expected))expect(Object.getOwnPropertyDescriptor(actual,key)).toStrictEqual({value:expected[key],writable:true,enumerable:true,configurable:true});
}
beforeEach(()=>{
  directory=mkdtempSync(join(tmpdir(),'hiitl-own-data-'));
  for(const key of Object.keys(process.env).filter(key=>key.startsWith('HIITL_')))vi.stubEnv(key,undefined);
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllEnvs();rmSync(directory,{recursive:true,force:true});});

it.each(['json','yaml'] as const)('keeps own data through both actual %s file loaders',format=>{
  const policy=policyInput(); const route=routeInput();
  const write=(name:string,value:unknown)=>{
    const path=join(directory,`${name}.${format}`);writeFileSync(path,format==='json'?JSON.stringify(value):dump(value));return path;
  };
  const loaded=new PolicyLoader(write('policy',policy)).load();
  write(route.name,route);
  // RouteLoader scans this directory; the policy file is not a route, so use a separate directory below.
  const routeDirectory=mkdtempSync(join(tmpdir(),'hiitl-own-route-'));
  let parsed:ReturnType<RouteLoader['get']>;
  try {
    writeFileSync(join(routeDirectory,`${route.name}.${format}`),format==='json'?JSON.stringify(route):dump(route));
    parsed=new RouteLoader(routeDirectory).get(route.name);
  } finally {rmSync(routeDirectory,{recursive:true,force:true});}
  retained(loaded.metadata,ownData());
  retained(loaded.rules[0].metadata,ownData());
  retained(loaded.rules[0].remediation?.details,ownData());
  retained(loaded.rules[0].tests?.[0].envelope.parameters,ownData());
  retained(parsed?.metadata,ownData());
  for(const value of [loaded.metadata,loaded.rules[0].metadata,loaded.rules[0].remediation?.details,parsed?.metadata]){
    expect(Object.hasOwn(value!,'__proto__')).toBe(true);expect(Object.getPrototypeOf(value)).toBe(Object.prototype);
  }
});

it('records the supplied own data and verifies its signature and content hash after SQLite readback',()=>{
  const client=new HIITL({sync:false,mode:'OBSERVE_ALL',org_id:'org_htl43own000000000',agent_id:'fixture-agent',environment:'prod',audit_db_path:join(directory,'audit.db'),signature_key:'fixture-signing-key'});
  try {
    const decision=client.evaluate({action:'fixture_action',target:ownData(),parameters:ownData()}) as Decision;
    const records=client.queryAudit({action_id:decision.action_id}) as Array<Record<string,any>>;
    expect(records).toHaveLength(1);
    const row={...records[0],envelope:JSON.parse(records[0].envelope),decision:JSON.parse(records[0].decision)};
    for(const member of ['target','parameters']){
      retained(row.envelope[member],ownData());
      expect(Object.hasOwn(row.envelope[member],'__proto__')).toBe(true);
      expect(Object.getPrototypeOf(row.envelope[member])).toBe(Object.prototype);
    }
    expect(envelopeVerifies('fixture-signing-key',row.envelope)).toBe(true);
    expect(row.content_hash).toBe(auditContentHash(row.event_id,row.envelope,row.decision));
    expect(Object.hasOwn(Object.prototype,'marker')).toBe(false);
  } finally {client.close();}
  const log=new AuditLogger(join(directory,'metadata.db'));
  try {
    const env=EnvelopeSchema.parse(envelopeInput({metadata:ownData()}));
    log.write(env,new PolicyEvaluator().evaluate(env,policyInput()));
    const row=log.getUnsynced()[0] as unknown as {envelope:Envelope};
    retained(row.envelope.metadata,ownData());
    expect(Object.getPrototypeOf(row.envelope.metadata)).toBe(Object.prototype);
  } finally {log.close();}
});

it('retains the declared native-call baseline: null defaults in five options, nested data null kept',()=>{
  const client=new HIITL({sync:false,mode:'OBSERVE_ALL',org_id:'org_htl43own000000000',agent_id:'fixture-agent',environment:'prod',audit_db_path:':memory:'});
  try {
    const seen:Envelope[]=[];
    vi.spyOn(client as any,'_decided').mockImplementation((env:Envelope)=>{seen.push(env);return {action_id:env.action_id,decision:'ALLOW',allowed:true,reason_codes:[],timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};});
    client.evaluate({action:'fixture_action',operation:null,target:null,parameters:null,agent_id:null,idempotency_key:null} as any);
    expect(seen).toHaveLength(1);
    expect({operation:seen[0].operation,target:seen[0].target,parameters:seen[0].parameters,agent_id:seen[0].agent_id}).toStrictEqual({operation:'execute',target:{},parameters:{},agent_id:'fixture-agent'});
    expect(seen[0].idempotency_key).toMatch(/^idem_[a-f0-9]{32}$/);
    client.evaluate({action:'fixture_action',parameters:{held:null}});
    expect(seen[1].parameters).toStrictEqual({held:null});
    expect(()=>client.evaluate({action:'fixture_action',confidence:null} as any)).toThrow(EnvelopeValidationError);
  } finally {client.close();}
});

it('refuses a supplied number before an extra native option can be projected away',()=>{
  const source=JSON.parse(readFileSync(new URL('../../../../../tests/conformance/numeric_domain/cases.json',import.meta.url),'utf8')) as {bound:number};
  const client=new HIITL({sync:false,mode:'OBSERVE_ALL',org_id:'org_htl43own000000000',agent_id:'fixture-agent',environment:'prod',audit_db_path:':memory:'});
  try {
    const evaluated=vi.spyOn(client as any,'_decided');
    expect(()=>client.evaluate({action:'fixture_action',extra:{nested:[source.bound]}} as any)).toThrow(/extra/);
    expect(()=>client.evaluate({action:'fixture_action',extra:{nested:[source.bound]}} as any)).toThrow(/not declared/i);
    expect(evaluated).not.toHaveBeenCalled();
    expect(client.queryAudit({})).toStrictEqual([]);
  } finally {client.close();}
});

it('the route loader reads all supplied numbers before its filename projection',()=>{
  const source=JSON.parse(readFileSync(new URL('../../../../../tests/conformance/numeric_domain/cases.json',import.meta.url),'utf8')) as {bound:number};
  const route=routeInput();const path=join(directory,`${route.name}.json`);
  writeFileSync(path,JSON.stringify(route));expect(new RouteLoader(directory).get(route.name)?.name).toBe(route.name);
  writeFileSync(path,JSON.stringify({...route,name:'different-name',metadata:{held:source.bound}}));
  expect(()=>new RouteLoader(directory).get(route.name)).toThrow(/metadata.*held/);
  expect(()=>new RouteLoader(directory).get(route.name)).toThrow(/text/i);
});

it('refuses a supplied result number before result options are projected or a store is read',async()=>{
  const source=JSON.parse(readFileSync(new URL('../../../../../tests/conformance/numeric_domain/cases.json',import.meta.url),'utf8')) as {bound:number};
  const client=new HIITL({sync:false,mode:'OBSERVE_ALL',org_id:'org_htl43own000000000',agent_id:'fixture-agent',environment:'prod',audit_db_path:':memory:'});
  try {
    const held=vi.spyOn((client as any).auditLogger,'lifecycle');
    await expect(client.recordResult('act_fixture000000000000','succeeded',{extra:{held:source.bound}} as any)).rejects.toThrow(/extra.*held/);
    await expect(client.recordResult('act_fixture000000000000','succeeded',{extra:{held:source.bound}} as any)).rejects.toThrow(/not declared/i);
    expect(held).not.toHaveBeenCalled();
    expect(client.queryAudit({})).toStrictEqual([]);
  } finally {client.close();}
});
