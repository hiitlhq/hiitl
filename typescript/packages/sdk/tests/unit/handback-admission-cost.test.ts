/** Same measured shapes through the actual SDK, its policy held from each place it is supplied. */
import {vi,it,expect} from 'vitest';
import {readFileSync,writeFileSync,mkdtempSync,rmSync,statSync,utimesSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
const {roots}=vi.hoisted(()=>({roots:[] as unknown[]}));
vi.mock('../../../core/src/numeric-domain.js',async original=>{
 const actual=await original<any>();return {...actual,assertNumericDomain:(value:unknown,...args:any[])=>{
  if(value!==null && typeof value==='object')roots.push(value);
  return actual.assertNumericDomain(value,...args);
 }};
});
vi.mock('@hiitl/core',()=>import('../../../core/src/index.js'));
import {HIITL} from '../../src/client.js';
import {SyncEngine} from '../../src/sync-engine.js';
const shapes=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/shapes.json'),'utf8'));
const held=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/baseline-held-typescript.json'),'utf8'));
const before=new Map(held.rows.map((row:any)=>[row.shape,row]));
// Each place the SDK's policy is supplied, and the before-record's row for it (sync_engine.md Numeric domain).
const sources={file:'sdk',pull:'sdk_pull',disk:'sdk_disk'} as const;
const call={action:'send_email',parameters:{subject:'x',body:'y'},target:{to:'alice@example.com'}};
/** A client holding the shape's policy through its own load or receipt; nothing stands in for its resolver. */
async function heldClient(source:keyof typeof sources,row:any,dir:string):Promise<HIITL>{
 const file=join(dir,'policy.json');writeFileSync(file,JSON.stringify(row.policy));
 const scope={mode:'RESPECT_POLICY' as const,org_id:row.envelope.org_id,environment:'dev' as const};
 if(source==='file')return new HIITL({sync:false,evaluation:'local',...scope,policy_path:file,audit_db_path:join(dir,'audit.db')});
 // No transport: the engine's start and first pull are stubbed, as the SDK's hybrid tests do; the pull lands through
 // the cache as the engine writes it, and a second client on the same cache starts warm from disk.
 vi.spyOn(SyncEngine.prototype,'start').mockImplementation(()=>{});
 vi.spyOn(SyncEngine.prototype,'initialSync').mockResolvedValue(false);
 const hybrid={api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',...scope,cache_dir:join(dir,'cache'),cold_start_behavior:'observe-silent' as const};
 const pulled=new HIITL({...hybrid,audit_db_path:join(dir,'pull.db')});await (pulled as any)._initialSyncPromise;
 await (pulled as any).syncCache.updatePolicies({policies:[{name:row.policy.name,active:true,content:JSON.parse(readFileSync(file,'utf8'))}]});
 if(source==='pull')return pulled;
 pulled.close();
 const warm=new HIITL({...hybrid,audit_db_path:join(dir,'disk.db')});await (warm as any)._initialSyncPromise;
 return warm;
}
const cases=shapes.flatMap((row:any)=>Object.keys(sources).map(source=>({name:row.name,source,row})));
// 88579bbd item 4 and sync_engine.md Numeric domain: the held policy was admitted where it was supplied, so a
// steady-state evaluate admits one supplied tree, the caller's call, and the held policy decides.
it.each(cases)('$name read from its $source policy admits only the caller\'s call',async({source,row}:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-held-'));
 const client=await heldClient(source,row,dir);
 try{
  await client.evaluate(call);
  roots.length=0;const decision=await client.evaluate(call);
  const prior=(before.get(row.name) as any)[sources[source as keyof typeof sources]];
  console.log('HTL43_ADMISSION',JSON.stringify({shape:row.name,source,before:prior.admission_roots,after:roots.length}));
  expect(decision.policy_version).toBe(row.policy.version);
  expect(roots.map((root:any)=>root.parameters)).toEqual([call.parameters]);
  expect(roots.length).toBeLessThan(prior.admission_roots);
 }finally{client.close();vi.restoreAllMocks();rmSync(dir,{recursive:true,force:true});}
});

// b88dd3e3: a held reading never outlives what it was read from. A changed file is read again (the loader's mtime
// cache), and a pull that lands replaces the cache's reading, a warm start's too; a kill-switch tick's part is row 240's
// (row240.test.ts). Mirrors test_handback_admission_cost.py.
const org=shapes[0].envelope.org_id;
const payments=(version:string,decision:string)=>({name:'payments',version,description:'payments',scope:{org_id:org,environment:'dev'},
 rules:[{name:'send',description:'send',priority:100,decision,reason_code:'SEND',conditions:{field:'action',operator:'equals',value:'send_email'}}]});
it.each(Object.keys(sources))('the %s policy is replaced where its source changes',async source=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-replaced-'));
 const first=payments('v1.0.0','ALLOW'),then=payments('v1.0.1','BLOCK');
 const client=await heldClient(source as keyof typeof sources,{policy:first,envelope:{org_id:org}},dir);
 try{
  const kept=await client.evaluate(call);
  if(source==='file'){
   const file=join(dir,'policy.json');writeFileSync(file,JSON.stringify(then));
   const later=new Date(statSync(file).mtimeMs+60_000);utimesSync(file,later,later);
  }else await (client as any).syncCache.updatePolicies({policies:[{name:then.name,active:true,content:then}]});
  const replaced=await client.evaluate(call);
  expect([kept,replaced].map(d=>[d.decision,d.policy_version])).toEqual([['ALLOW','v1.0.0'],['BLOCK','v1.0.1']]);
 }finally{client.close();vi.restoreAllMocks();rmSync(dir,{recursive:true,force:true});}
});

import {createConfig,createHostedConfig} from '../../src/config.js';
it.each(['client','hosted_client','local_config','hosted_config'])('%s admits its supplied settings once',entry=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-config-cost-'));
 const options={environment:'dev',agent_id:'fixture',org_id:'org_1234567890abcdef',audit_db_path:join(dir,'audit.db'),dedup_window_seconds:1};
 let client:HIITL|undefined;
 try{roots.length=0;
  if(entry==='client')client=new HIITL({...options,sync:false});
  else if(entry==='hosted_client')client=new HIITL({...options,evaluation:'remote',api_key:'local-contract-fixture-key',signature_key:'local-fixture-signing-secret',server_url:'https://fixture.invalid'});
  else if(entry==='local_config')createConfig(options);
  else createHostedConfig({...options,api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid'});
  expect(roots).toHaveLength(1);
 }finally{client?.close();rmSync(dir,{recursive:true,force:true});}
});
