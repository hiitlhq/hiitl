/**
 * HTL-43 gap 303, decided by the record (b88dd3e3): the SDK's reported timing counts the call's admission, on the held
 * policy's path, the kill-switch tick's path and the re-evaluation with a route's answer. A controlled clock moves only
 * while the admitter walks the call's tree, by the cell's own step. Mirrors
 * python/hiitl/core/tests/test_handback_admission_timing.py.
 */
import {vi,it,expect} from 'vitest';
import {readFileSync,writeFileSync,mkdtempSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
const {clock}=vi.hoisted(()=>({clock:{now:100}}));
const STEP=125;
vi.mock('../../../core/src/numeric-domain.js',async original=>{
 const actual=await original<any>();return {...actual,assertNumericDomain:(value:any,path:(string|number)[]=[],...args:any[])=>{
  // The SDK's walk of the caller's call, at its root.
  if(value!==null && typeof value==='object' && path.length===0 && typeof value.action==='string')clock.now+=STEP;
  return actual.assertNumericDomain(value,path,...args);
 }};
});
vi.mock('@hiitl/core',()=>import('../../../core/src/index.js'));
import {HIITL} from '../../src/client.js';
import {SyncEngine} from '../../src/sync-engine.js';
const shapes=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/shapes.json'),'utf8'));
const call={action:'send_email',parameters:{subject:'x',body:'y'},target:{to:'alice@example.com'}};
const timing={ingest_ms:STEP,evaluation_ms:0,total_ms:STEP};
/** A client holding the shape's policy through its own load or receipt, as handback-admission-cost.test.ts builds it. */
async function heldClient(source:string,row:any,dir:string):Promise<HIITL>{
 const file=join(dir,'policy.json');writeFileSync(file,JSON.stringify(row.policy));
 const scope={mode:'RESPECT_POLICY' as const,org_id:row.envelope.org_id,environment:'dev' as const};
 if(source==='file')return new HIITL({sync:false,evaluation:'local',...scope,policy_path:file,audit_db_path:join(dir,'audit.db')});
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
const clocked=()=>vi.spyOn(performance,'now').mockImplementation(()=>clock.now);

const held=shapes.flatMap((row:any)=>['file','pull','disk'].map(source=>({name:row.name,source,row})));
it.each(held)('$name read from its $source policy times the call\'s admission',async({source,row}:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-timing-'));
 const client=await heldClient(source,row,dir);const now=clocked();
 try{
  await client.evaluate(call);
  const decision=await client.evaluate(call);
  expect(decision.policy_version).toBe(row.policy.version);
  expect(decision.timing).toEqual(timing);
 }finally{now.mockRestore();client.close();vi.restoreAllMocks();rmSync(dir,{recursive:true,force:true});}
});

const org=shapes[0].envelope.org_id;
const rule=(name:string,decision:string,action:string,more:Record<string,unknown>={})=>({name,description:name,priority:100,decision,
 reason_code:name.toUpperCase().replace(/-/g,'_'),conditions:{field:'action',operator:'equals',value:action},...more});
const set=(version:string,...rules:any[])=>({name:'payments',version,description:'payments',scope:{org_id:org,environment:'dev'},rules});
const HELD=set('v1.0.0',rule('allow-pay','ALLOW','pay'),rule('allow-refund','ALLOW','refund'));
const PART=set('v1.0.1',rule('halt-payments','KILL_SWITCH','pay'));
/** A client whose cache holds `policy` and a kill-switch tick's part no pull has followed (row 240). */
function ticked(dir:string,policy:any,part:any):any{
 const file=join(dir,'policy.json');writeFileSync(file,JSON.stringify(policy));
 const client:any=new HIITL({mode:'RESPECT_POLICY',org_id:org,environment:'dev',policy_path:file,audit_db_path:join(dir,'audit.db')});
 client.syncCache={tickPart:()=>part,getPolicySet:()=>policy,cacheStatus:()=>'synced'};
 return client;
}

it.each([['pay','KILL_SWITCH','v1.0.1'],['refund','ALLOW','v1.0.0']])('on the tick\'s path, %s times the call\'s admission',async(action,decided,version)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-timing-'));
 const client=ticked(dir,HELD,PART);const now=clocked();
 try{
  const decision=await client.evaluate({action,parameters:{}});
  expect([decision.decision,decision.policy_version]).toEqual([decided,version]);
  expect(decision.timing).toEqual(timing);
 }finally{now.mockRestore();client.close();rmSync(dir,{recursive:true,force:true});}
});

it('the re-evaluation with a route\'s answer times the call\'s admission',async()=>{
 // policy_format.md 2.7: the route's answer re-enters evaluation; the re-evaluation's decision carries the call's span.
 const dir=mkdtempSync(join(tmpdir(),'htl43-timing-'));
 const asking=set('v1.0.0',rule('ask','ROUTE','pay',{priority:500,route:'check'}),
  {...rule('high-score','BLOCK','pay',{priority:800}),conditions:{field:'external.check.score',operator:'greater_than',value:1}});
 const client=ticked(dir,asking,null);
 client.routeLoader={get:()=>({name:'check',direction:'bidirectional',response_schema:{required_fields:['score']}})};
 const asked:any[]=[];client._askRoute=async(_route:any,payload:any)=>{asked.push(payload);return {score:2};};
 const now=clocked();
 try{
  const decision=await client.evaluate({action:'pay',parameters:{}});
  expect(asked).toHaveLength(1);
  expect([decision.decision,decision.reason_codes]).toEqual(['BLOCK',['HIGH_SCORE']]);
  expect(decision.timing).toEqual(timing);
 }finally{now.mockRestore();client.close();rmSync(dir,{recursive:true,force:true});}
});
