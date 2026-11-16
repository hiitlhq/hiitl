/** sync_engine.md numeric domain: admission before loss/effects; historical C stays. */
import {it,expect,vi} from 'vitest';
import {readFileSync,mkdtempSync,rmSync,readdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import Database from 'better-sqlite3';
import {PolicyEvaluator,Redaction,NumericDomainError} from '@hiitl/core';
import {AuditLogger} from '../../src/audit.js';
import {AuditLogError,ConfigurationError,SyncError,ServerError} from '../../src/exceptions.js';
import {SyncCache} from '../../src/sync-cache.js';
import {SyncClient} from '../../src/sync-client.js';
import {HostedClient} from '../../src/http-client.js';
import {createConfig,createHostedConfig,resolveSettings} from '../../src/config.js';
const root=resolve(__dirname,'../../../../../');
const B=JSON.parse(readFileSync(join(root,'tests/conformance/numeric_domain/cases.json'),'utf8')).bound;
const env:any={schema_version:'v2.0',org_id:'org_1234567890abcdef',environment:'dev',agent_id:'fixture',action_id:'act_01234567890123456789',idempotency_key:'numeric',action:'read',operation:'execute',target:{},parameters:{},timestamp:'2026-11-14T00:00:00Z',signature:'0'.repeat(64)};
const policy:any={name:'numeric',version:'v1.0.0',description:'numeric admission',scope:{org_id:env.org_id,environment:'dev'},rules:[]};
const decision:any={action_id:env.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};
it.each(['envelope','policy','enrichment'])('%s is admitted before evaluation',surface=>{
  const e=structuredClone(env),p=structuredClone(policy),extra:any={};
  expect(new PolicyEvaluator().evaluate(e,p).decision).toBe('BLOCK');
  if(surface==='envelope')e.parameters.probe=B;else if(surface==='policy')p.metadata={probe:B};else extra.route={probe:B};
  expect(()=>new PolicyEvaluator().evaluate(e,p,'RESPECT_POLICY',extra)).toThrow(/probe.*text/);
});
it.each(['envelope','decision','held_result','result','redacted'])('audit %s is refused before insertion',surface=>{
  const dir=mkdtempSync(join(tmpdir(),'hiitl-numeric-audit-'));
  const path=join(dir,'audit.db');const store=new AuditLogger(path,surface==='redacted'?Redaction.declared(['parameters.probe']):undefined);
  try{
    const e=structuredClone(env),d=structuredClone(decision);const event=store.write(e,d);
    expect(store.verifyIntegrity(event)).toBe(true);
    let call:()=>unknown;
    if(surface==='envelope'||surface==='redacted'){e.parameters.probe=B;call=()=>store.write(e,d);}
    else if(surface==='decision'){d.timing.total_ms=NaN;call=()=>store.write(e,d);}
    else if(surface==='held_result')call=()=>store.holdResult(env.action_id,{probe:B});
    else call=()=>store.writeResult(store.lifecycle(env.org_id,'dev',env.action_id)[0],{status:'succeeded',probe:B});
    let error:any;try{call();}catch(caught){error=caught;}expect(error).toBeInstanceOf(AuditLogError);expect(error.message).toMatch(surface==='decision'?/JSON number/:['held_result','result'].includes(surface)?/not declared/:/text/);expect(store.count()).toBe(1);expect(store.heldResults()).toEqual([]);
  }finally{store.close();rmSync(dir,{recursive:true,force:true});}
});
it('stored historical bytes and hash remain verifiable',()=>{
  const c=JSON.parse(readFileSync(join(root,'tests/conformance/audit_hash/case_001_fixed_record.json'),'utf8'));
  const dir=mkdtempSync(join(tmpdir(),'hiitl-numeric-history-')),path=join(dir,'old.db');const store=new AuditLogger(path);
  try{
    const event=store.write(env,decision);const db=new Database(path);
    db.prepare('UPDATE audit_log SET event_id=?, envelope=?, decision=?, content_hash=? WHERE event_id=?').run(c.event_id,JSON.stringify(c.envelope),JSON.stringify(c.decision),c.expected.content_hash,event);db.close();
    expect(store.get(c.event_id)?.content_hash).toBe(c.expected.content_hash);
    expect(store.verifyIntegrity(c.event_id)).toBe(true);
    expect(()=>store.write(c.envelope,c.decision)).toThrow(AuditLogError);
  }finally{store.close();rmSync(dir,{recursive:true,force:true});}
});
it.each(['Policies','Routes','KillSwitches'])('cache %s refuses before memory/disk update',async channel=>{
  const dir=mkdtempSync(join(tmpdir(),'hiitl-numeric-cache-'));const cache:any=new SyncCache({cache_dir:dir,org_id:env.org_id,environment:'dev'});
  try{
    await expect(cache['update'+channel](channel==='Routes'?[{probe:B}]:{probe:B})).rejects.toThrow(/probe.*text/);
    expect(cache['get'+channel]()).toBeNull();expect(readdirSync(dir)).toEqual([]);
  }finally{rmSync(dir,{recursive:true,force:true});}
});
it('SDK integer duration reuses the admitted core integer domain',()=>{
  expect(createConfig({dedup_window_seconds:1}).dedup_window_seconds).toBe(1);
  expect(()=>createConfig({dedup_window_seconds:B})).toThrow(/dedup_window_seconds.*JSON integer/s);
});
it('whole configuration is checked before projection',()=>{
  expect(()=>resolveSettings({sync_config:{max_retries:B}} as any)).toThrow(ConfigurationError);
  expect(()=>resolveSettings({sync_config:{max_retries:B}} as any)).toThrow(/Unknown sync setting: 'max_retries'/);
  expect(()=>createConfig({unread:{probe:B}} as any)).toThrow(/probe.*text/);
});
it('hosted input refuses before push/send',async()=>{
  const client:any=new HostedClient(createHostedConfig({environment:'dev',org_id:env.org_id,agent_id:'fixture',api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid'}));
  const push=vi.spyOn(client,'_pushFirst').mockResolvedValue(undefined);
  const ask=vi.spyOn(client,'_ask').mockResolvedValue({status:200,data:decision});
  try{await expect(client.evaluate({...env,parameters:{probe:B}})).rejects.toThrow(/probe.*text/);expect(push).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();}
  finally{client.close();}
});
it('hosted response is admitted before unknown members are projected',async()=>{
  const client:any=Object.create(HostedClient.prototype);
  expect((await client._parseResponse(200,decision)).decision).toBe('ALLOW');
  await expect(client._parseResponse(200,{...decision,unread:{probe:B}})).rejects.toThrow(/probe.*text/);
});
it.each(['uploadAudit','uploadTelemetry'])('new sync %s input refuses before send',async method=>{
  const fetchImpl=vi.fn(async()=>new Response(JSON.stringify({accepted:1}),{status:200}));
  const client:any=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:env.org_id,environment:'dev',fetchImpl});
  await expect(client[method](method==='uploadAudit'?[]:[{probe:B}],method==='uploadAudit'?B:1)).rejects.toThrow(method==='uploadAudit'?/sync_sequence.*JSON integer/:/probe.*text/);expect(fetchImpl).not.toHaveBeenCalled();
});
it.each(['downloadPolicies','downloadRoutes','pollKillSwitches'])('sync %s reply is admitted before member projection',async method=>{
  const fetchImpl=vi.fn(async()=>new Response(JSON.stringify({policies:[],routes:[],kill_switches:[],unread:{probe:B}}),{status:200}));
  const client:any=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:env.org_id,environment:'dev',fetchImpl});
  await expect(client[method]()).rejects.toThrow(/probe.*text/);
});
it('configuration schema checks raw values before unknown-member projection',async()=>{
  const {LocalModeConfigSchema}=await import('../../src/config.js');
  expect(()=>LocalModeConfigSchema.parse({unknown:{probe:B}})).toThrow(/probe.*text/);
});
it.each(['sync','cache'])('direct %s constructor admits its numeric settings',surface=>{
  const call=surface==='sync'?()=>new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:env.org_id,environment:'dev',timeout:B}):()=>new SyncCache({cache_dir:tmpdir(),org_id:env.org_id,environment:'dev',max_stale_age:B});
  expect(call).toThrow(ConfigurationError);expect(call).toThrow(/JSON number/);
});
it('configuration safeParse reports numeric refusal without throwing',async()=>{
  const {LocalModeConfigSchema}=await import('../../src/config.js');
  let result:ReturnType<typeof LocalModeConfigSchema.safeParse>;
  expect(()=>{result=LocalModeConfigSchema.safeParse({unread:{probe:B}});}).not.toThrow();
  expect(result!.success).toBe(false);
  if(!result!.success){expect(result!.error.issues[0].path).toEqual(['unread','probe']);expect(result!.error.issues[0].message).toContain('text');}
});
