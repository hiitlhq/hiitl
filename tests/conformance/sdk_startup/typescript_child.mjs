import fs, {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
const [root,dir]=process.argv.slice(2),c=JSON.parse(readFileSync(join(dir,'case.json'))),payload=JSON.parse(readFileSync(join(dir,'payload.json')));
const producerEvents=[];let phase='imports';
// The runtime's own clock, never `performance`: its first read loads perf_hooks, which would prepay before the SDK
// is imported what the SDK's first call pays (HTL-45 ac769270 item 2).
const clock = process.argv.includes('--producers') ? () => 0 : () => Number(process.hrtime.bigint()) / 1e6;
const schemaObserver=process.argv.includes('--producers')?(await import('./schema_producers.mjs')).schemaProducers(producerEvents):undefined;
const realFunction=globalThis.Function;
if(process.argv.includes('--producers'))globalThis.Function=new Proxy(realFunction,{
 construct(target,args,newTarget){
  const stack=new Error().stack;
  producerEvents.push({phase:/Sync(?:Engine|Client)\./.test(stack)?'first_sync_cycle':phase,producer:'Function',stack,body:String(args.at(-1)).slice(0,160)});
  return Reflect.construct(target,args,newTarget);
 }
});
const loadedBefore=process.moduleLoadList.length;let start=clock();const clockLoads=process.moduleLoadList.slice(loadedBefore);
const {HIITL}=await import(pathToFileURL(join(root,'typescript/packages/sdk/dist/client.js')));
const imports_ms=clock()-start,requests=[];
schemaObserver?.read('imports');
let policyReads=0;
const realRead=fs.readFileSync;
fs.readFileSync=function(file,...args){if([join(dir,'policy.json'),join(dir,'policy.yaml')].includes(String(file)))policyReads++;return realRead.call(this,file,...args);};
globalThis.fetch=async(input,init)=>{
 const p=new URL(String(input)).pathname;requests.push(p);let body;
 if(p==='/v1/evaluate'){const call=JSON.parse(init.body);body={action_id:call.action_id,decision:'BLOCK',allowed:false,reason_codes:['STARTUP_GUARD'],policy_version:'v1.0.0',timing:{total_ms:0}};}
 else if(['none','json','yaml'].includes(c.source))return new Response(JSON.stringify({detail:{error:'UNAUTHORIZED',message:'fixture offline'}}),{status:401});
 else if(p.endsWith('/policies'))body=payload;
 else if(p.endsWith('/routes'))body={routes:[],etag:'startup'};
 else if(p.endsWith('/kill-switches'))body={kill_switches:[],server_time:'2026-11-16T00:00:00Z'};
 else body={accepted:0,duplicates:0,errors:[]};
 return new Response(JSON.stringify(body),{status:200,headers:{'content-type':'application/json'}});
};
let options={org_id:'org_startup000000000000',environment:'dev',agent_id:'startup',mode:c.evaluation,audit_db_path:join(dir,'audit.db')};
if(['json','yaml'].includes(c.source))options.policy_path=join(dir,'policy.'+c.source);
if(['hybrid','hosted'].includes(c.mode))Object.assign(options,{api_key:'local-startup-fixture-key',server_url:'https://fixture.invalid',cache_dir:join(dir,'cache'),cold_start_behavior:c.cold_start});
if(c.mode==='hosted')Object.assign(options,{evaluation:'remote',signature_key:'local-startup-fixture-signature-key'});
let profiler;
if(process.argv.includes('--profile')) {
 const {Session}=await import('node:inspector');profiler=new Session();profiler.connect();
 profiler.post('Profiler.enable');profiler.post('Profiler.setSamplingInterval',{interval:100});
}
const row={transport:'in-process fixed HTTP wire fixture; no network/hosted service time',imports_ms,clock_loads:clockLoads};let client;
try{
 phase='construction';start=clock();client=new HIITL(options);row.construction_ms=clock()-start;row.resolved_mode=client.mode;
 schemaObserver?.read('construction');
 row.construction_policy_reads=policyReads;row.startup_wait_ms=0;
 phase='first_sync_cycle';
 const cold=c.mode==='hybrid'&&['none','pull'].includes(c.source);
 const waitInCall=cold&&c.cold_start==='fail-closed'&&c.startup==='immediate';
 let readyAt;
 if(waitInCall)client._initialSyncPromise.then(()=>{readyAt=clock();});
 if(c.startup==='settled'||(cold&&!waitInCall)){start=clock();await client._initialSyncPromise;row.startup_wait_ms=clock()-start;}
 schemaObserver?.read('first_sync_cycle');
 for(const name of ['first','repeated']){
  phase=name;const readsBefore=policyReads;if(profiler)profiler.post('Profiler.start');start=clock();const decision=await client.evaluate({action:'guarded',parameters:{amount:100}});
  const end=clock(),wall=end-start;
  if(profiler)profiler.post('Profiler.stop',(error,data)=>{if(error)throw error;row[name+'_cpu_profile']=data.profile;});
  const wait=name==='first'&&waitInCall?Math.max(0,(readyAt??start)-start):0;
  row[name+'_wall_ms']=wall;row[name+'_ms']=wall-wait;
  if(name==='first'&&waitInCall){row.startup_wait_ms=wait;row.startup_wait_location='first evaluate';row.startup_completed=readyAt!==undefined;}
  row[name+'_policy_reads']=policyReads-readsBefore;row[name+'_decision']={decision:decision.decision,policy_version:decision.policy_version,reason_codes:decision.reason_codes,cache_status:decision.cache_status,timing:decision.timing};
  schemaObserver?.read(name);
 }
}catch(error){row.error=error.constructor.name+': '+error.message;}
finally{phase='first_sync_cycle';if(client){await client._initialSyncPromise;client.close();}schemaObserver?.read(phase);schemaObserver?.close();globalThis.Function=realFunction;}
if(process.argv.includes('--producers'))row.producer_events=producerEvents;
if(profiler)profiler.disconnect();
row.requests=requests;
console.log('HTL45_SAMPLE '+JSON.stringify(row));
