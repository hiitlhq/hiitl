/** aa0cf726 / 88579bbd: public entry, documented refusal, located cause. */
import {it,expect} from 'vitest';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import yaml from 'js-yaml';
import {HIITL} from '../../src/client.js';
import {PolicyLoader} from '../../src/policy-loader.js';
import {ConfigurationError,EnvelopeValidationError,LifecycleError,PolicyLoadError} from '../../src/exceptions.js';
import {NUMERIC_BOUND} from '@hiitl/core';
const typed=(error:any,path:(string|number)[],kind:string,limits:number[]=[])=>{
 expect(error.message).toContain('<root>'+path.map(p=>'['+JSON.stringify(p)+']').join(''));
 expect(error.message).toContain(kind);expect(error.message).toContain(String(NUMERIC_BOUND));
 for(const limit of limits)expect(error.message).toContain(String(limit));
 expect(error.message).not.toContain('pass the value as text');
};
for(const name of ['dedup_window_seconds','timeout','max_retries'])it(`constructor numeric ${name}`,()=>{
 let error:any;try{new HIITL({[name]:NUMERIC_BOUND,sync:false});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(ConfigurationError);
 typed(error,[name],name==='timeout'?'number':'integer',name==='timeout'?[0.1,30]:name==='max_retries'?[0,10]:[]);
});
for(const format of ['json','yaml'])for(const path of [['metadata','probe'],['rules',0,'priority']])it(`policy ${format} ${path.join('.')}`,()=>{
 const data:any={name:'numeric',version:'v1.0.0',description:'numeric',scope:{org_id:'org_1234567890abcdef',environment:'dev'},rules:[{name:'r',description:'r',priority:1,conditions:{all_of:[]},decision:'BLOCK',reason_code:'R'}],metadata:{probe:1}};
 const dir=mkdtempSync(join(tmpdir(),'htl43-public-')),file=join(dir,'policy.'+format);
 const write=()=>writeFileSync(file,format==='json'?JSON.stringify(data):yaml.dump(data));
 try{write();expect(new PolicyLoader(file).load().name).toBe(data.name);
 let parent=data;for(const part of path.slice(0,-1))parent=parent[part];parent[path.at(-1)!]=NUMERIC_BOUND;write();
 let error:any;try{new PolicyLoader(file).load();}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(PolicyLoadError);expect(error.reason).toBe('POLICY_VALIDATION_ERROR');
 if(path.at(-1)==='priority')typed(error,path,'integer');else{expect(error.message).toContain('<root>["metadata"]["probe"]');expect(error.message).toContain('pass the value as text');}
 expect(error.message).not.toContain('syntax errors');expect(error.message).not.toContain('readable');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
for(const mode of ['local','hybrid','hosted'])it(`public result ${mode}`,async()=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-public-'));
 const start=vi.spyOn(SyncEngine.prototype,'start').mockImplementation(()=>{}),stop=vi.spyOn(SyncEngine.prototype,'stop').mockResolvedValue(undefined),initial=vi.spyOn(SyncEngine.prototype,'initialSync').mockResolvedValue(true);
 vi.stubGlobal('fetch',vi.fn(async(url:any,init:any)=>{
  const body=JSON.parse(init.body);const data=new URL(String(url)).pathname.endsWith('/evaluate')?{action_id:body.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}}:{execution_result:body};
  return new Response(JSON.stringify(data),{status:200});
 }));
 const client:any=new HIITL({sync:mode!=='local',api_key:mode!=='local'?'local-contract-fixture-key':undefined,evaluation:mode==='hosted'?'remote':'local',signature_key:'local-fixture-signing-secret',server_url:'https://fixture.invalid',org_id:'org_1234567890abcdef',environment:'dev',cache_dir:join(dir,'cache'),audit_db_path:join(dir,'audit.db')});
 try{expect(client.mode).toBe(mode);const decision=await client.evaluate({action:'read'});
 expect((await client.recordResult(decision.action_id,'succeeded',{duration_ms:1})).execution_result.duration_ms).toBe(1);
 let error:any;try{await client.recordResult(decision.action_id,'succeeded',{duration_ms:NUMERIC_BOUND});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(LifecycleError);expect(error.reason).toBe('RESULT_INVALID');typed(error,['duration_ms'],'number',[0]);
 }finally{client.close();start.mockRestore();stop.mockRestore();initial.mockRestore();vi.unstubAllGlobals();rmSync(dir,{recursive:true,force:true});}
});

const evaluations=[{options:{parameters:{probe:NUMERIC_BOUND}},path:['parameters','probe'],kind:undefined},{options:{confidence:NUMERIC_BOUND},path:['confidence'],kind:'number'},{options:{cost_estimate:{api_calls:NUMERIC_BOUND}},path:['cost_estimate','api_calls'],kind:'integer'}];
it.each(evaluations)('evaluate $path',async({options,path,kind})=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-public-'));const client=new HIITL({sync:false,audit_db_path:join(dir,'audit.db')});
 try{expect((await client.evaluate({action:'read'})).allowed).toBe(true);let error:any;try{await client.evaluate({action:'read',...options});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(EnvelopeValidationError);if(kind)typed(error,path,kind);else{expect(error.message).toContain('<root>["parameters"]["probe"]');expect(error.message).toContain('pass the value as text');}
 }finally{client.close();rmSync(dir,{recursive:true,force:true});}
});

it.each([false,true])('verifier claims are admitted before projection: %s',async bad=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-claims-')),file=join(dir,'policy.json');
 const policy={name:'identity',version:'v1.0.0',description:'identity',scope:{org_id:'org_1234567890abcdef',environment:'dev'},rules:[{name:'identity',description:'identity',priority:2,conditions:{field:'principal.sub',operator:'exists',value:false},decision:'BLOCK',reason_code:'NO_ID'},{name:'allow',description:'allow',priority:1,conditions:{all_of:[]},decision:'ALLOW',reason_code:'OK'}]};
 writeFileSync(file,JSON.stringify(policy));const client=new HIITL({sync:false,mode:'RESPECT_POLICY',policy_path:file,audit_db_path:join(dir,'claims.db'),principal_verifier:()=>({sub:'verified',unread:{probe:bad?NUMERIC_BOUND:1}})});
 try{expect((await client.evaluate({action:'read',principal_token:'fixture'})).decision).toBe(bad?'BLOCK':'ALLOW');}
 finally{client.close();rmSync(dir,{recursive:true,force:true});}
});

import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {vi} from 'vitest';
import {RouteLoader} from '../../src/route-loader.js';
import {RouteLoadError,SyncError} from '../../src/exceptions.js';
import {SyncClient} from '../../src/sync-client.js';
import {ENV_SETTINGS} from '../../src/config.js';
const members=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_remedies/cases.json'),'utf8')).cases;
for(const format of ['json','yaml'])it.each(members.filter((r:any)=>['policy','routes'].includes(r.format)))(`each ${format} numeric member $id`,(row:any)=>{
 vi.stubEnv('HTL41_ROUTE_FIXTURE','local-fixture');
 const data=structuredClone(row.control),dir=mkdtempSync(join(tmpdir(),'htl43-member-')),file=join(dir,data.name+'.'+format);
 const write=()=>writeFileSync(file,format==='json'?JSON.stringify(data):yaml.dump(data));
 const load=()=>row.format==='policy'?new PolicyLoader(file).load():new RouteLoader(dir).get(data.name);
 try{write();expect(load()?.name).toBe(data.name);let at=data;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;write();
 let error:any;try{load();}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(row.format==='policy'?PolicyLoadError:RouteLoadError);
 expect(error.reason).toBe(row.format==='policy'?'POLICY_VALIDATION_ERROR':undefined);
 typed(error,row.path,row.type,Object.values(row.range));
 }finally{rmSync(dir,{recursive:true,force:true});vi.unstubAllEnvs();}
});
// ENV_SETTINGS is the source taxonomy, with its constructor path (no separately grown list).
for(const [,option,kind] of ENV_SETTINGS.filter(([,p,k])=>p.startsWith('sync_config.')&&k==='number'))it(`supplied constructor ${option}`,()=>{
 const name=option.split('.')[1];let error:any;
 try{new HIITL({sync:false,sync_config:{[name]:NUMERIC_BOUND}});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(ConfigurationError);
 typed(error,['sync_config',name],['telemetry_sync_interval','telemetry_buffer_size'].includes(name)?'integer':'number');
});
for(const [channel,method] of [['policy','downloadPolicies'],['routes','downloadRoutes'],['kill_switches','pollKillSwitches']])it(`sync reply numeric ${channel}`,async()=>{
 const data:any={policies:[],routes:[],kill_switches:[]};const client:any=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:'org_1234567890abcdef',environment:'dev',fetchImpl:vi.fn(async()=>new Response(JSON.stringify(data),{status:200}))});
 await client[method]();data.metadata={probe:NUMERIC_BOUND};let error:any;try{await client[method]();}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(SyncError);expect(error.channel).toBe(channel);
 expect(error.message).toContain('<root>["metadata"]["probe"]');expect(error.message).toContain('pass the value as text');
});

import {SyncEngine} from '../../src/sync-engine.js';
import {SyncCache} from '../../src/sync-cache.js';
import {HostedClient} from '../../src/http-client.js';
import {createHostedConfig} from '../../src/config.js';
for(const [channel,update,get] of [['policy','updatePolicies','getPolicies'],['routes','updateRoutes','getRoutes'],['kill_switches','updateKillSwitches','getKillSwitches']])it(`cache numeric ${channel}`,async()=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-cache-')),cache:any=new SyncCache({cache_dir:dir,org_id:'org_1234567890abcdef',environment:'dev'});
 const control=channel==='routes'?[]:channel==='policy'?{policies:[]}:{kill_switches:[],policy_set:null};
 try{await cache[update](control);const prior=structuredClone(cache[get]());let error:any;
 try{await cache[update](channel==='routes'?[{metadata:{probe:NUMERIC_BOUND}}]:{metadata:{probe:NUMERIC_BOUND}});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(SyncError);expect(error.channel).toBe(channel);
 expect(error.message).toContain('<root>'+(channel==='routes'?'[0]':'')+'["metadata"]["probe"]');expect(error.message).toContain('pass the value as text');
 expect(cache[get]()).toEqual(prior);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
it.each(['duration_ms','probe'])('exported hosted result %s',async member=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-result-'));const client:any=new HostedClient(createHostedConfig({environment:'dev',agent_id:'fixture',org_id:'org_1234567890abcdef',api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',audit_db_path:join(dir,'audit.db')}));
 client._pushFirst=()=>{throw Error('refused input reached the drain');};
 try{let error:any;try{await client.recordResult('act_'+'a'.repeat(20),{status:'succeeded',[member]:NUMERIC_BOUND});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(LifecycleError);expect(error.reason).toBe('RESULT_INVALID');
 if(member==='duration_ms')typed(error,[member],'number',[0]);else{expect(error.message).toContain('<root>["probe"]');expect(error.message).toContain('not declared');}
 }finally{client.close();rmSync(dir,{recursive:true,force:true});}
});

it.each([['sync','timeout'],['sync','max_retries'],['cache','max_stale_age']])('component %s numeric constructor %s',(component,member)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-options-'));
 const construct=(value:number)=>component==='sync'?new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:'org_1234567890abcdef',environment:'dev',[member]:value}):new SyncCache({cache_dir:dir,org_id:'org_1234567890abcdef',environment:'dev',[member]:value});
 try{construct(1);let error:any;try{construct(NUMERIC_BOUND);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(ConfigurationError);typed(error,[member],'number');
 }finally{rmSync(dir,{recursive:true,force:true});}
});

it.each(['status','error'])('result %s names its nonnumeric declaration',async member=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-result-kind-')),client=new HIITL({sync:false,audit_db_path:join(dir,'audit.db')});
 try{let error:any;try{await client.recordResult('act_01234567890123456789',member==='status'?NUMERIC_BOUND as any:'failed',member==='error'?{error:NUMERIC_BOUND as any}:{});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(LifecycleError);expect(error.reason).toBe('RESULT_INVALID');expect(error.message).toContain('<root>["'+member+'"]');expect(error.message).toContain('requires a JSON string');expect(error.message).not.toContain('pass the value as text');}
 finally{client.close();rmSync(dir,{recursive:true,force:true});}
});

for(const mode of ['local','hybrid','hosted'])it.each(members.filter((r:any)=>r.format==='envelope'))(`public evaluate ${mode} numeric $id`,async(row:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-public-evaluate-'));
 const start=vi.spyOn(SyncEngine.prototype,'start').mockImplementation(()=>{}),stop=vi.spyOn(SyncEngine.prototype,'stop').mockResolvedValue(undefined),initial=vi.spyOn(SyncEngine.prototype,'initialSync').mockResolvedValue(true);
 vi.stubGlobal('fetch',vi.fn(async(_url:any,init:any)=>{const body=JSON.parse(init.body);return new Response(JSON.stringify({action_id:body.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}}),{status:200});}));
 const client:any=new HIITL({sync:mode!=='local',api_key:mode!=='local'?'local-contract-fixture-key':undefined,evaluation:mode==='hosted'?'remote':'local',signature_key:'local-fixture-signing-secret',server_url:'https://fixture.invalid',org_id:'org_1234567890abcdef',environment:'dev',cache_dir:join(dir,'cache'),audit_db_path:join(dir,'audit.db')});
 const options:any={action:'read',[row.path[0]]:structuredClone(row.control[row.path[0]])};
 try{expect(client.mode).toBe(mode);expect((await client.evaluate(options)).allowed).toBe(true);let at=options;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 let error:any;try{await client.evaluate(options);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(EnvelopeValidationError);expect(error.reason).toBeUndefined();typed(error,row.path,row.type,Object.values(row.range));
 }finally{client.close();start.mockRestore();stop.mockRestore();initial.mockRestore();vi.unstubAllGlobals();rmSync(dir,{recursive:true,force:true});}
});

it('principal_token keeps the native argument declaration',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-native-argument-')),client=new HIITL({sync:false,audit_db_path:join(dir,'audit.db'),principal_verifier:()=>({sub:'fixture'})});
 try{expect((await client.evaluate({action:'read',principal_token:'fixture'})).allowed).toBe(true);let error:any;try{await client.evaluate({action:'read',principal_token:NUMERIC_BOUND as any});}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(EnvelopeValidationError);expect(error.message).toContain('<root>["principal_token"]');expect(error.message).toContain('requires a JSON string');expect(error.message).not.toContain('not declared');
 }finally{client.close();rmSync(dir,{recursive:true,force:true});}
});
