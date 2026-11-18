/** Record existing shapes, serially with measure.py; no chosen timing limit.
 * Usage: node measure.mjs <source-root> <source-label> <shapes.json> <new-output-file>
 * Each shape is read through the core, and through the SDK with its policy held from each place it is supplied: the
 * policy file (sdk), a pull the cache receives (sdk_pull) and the cache on disk at a warm start (sdk_disk). Each row also
 * records the timing the decision itself reports (decision_response.md Timing Metadata; HTL-43 gap 303). */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {register} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
const [source,label,shapesFile,output]=process.argv.slice(2);
if(fs.existsSync(output))throw Error('Keep each measurement attempt');
// Admission work, read where it is done: every call of Core's numeric walk, and each walk entered from outside it.
const count='\n;{const walk=assertNumericDomain;let depth=0;assertNumericDomain=function(value,at){const work=globalThis.__admission;if(work){work.numeric_visits++;if(!depth&&value!==null&&typeof value==="object")work.admission_roots++;}depth++;try{return walk(value,at);}finally{depth--;}};}\n';
register('data:text/javascript,'+encodeURIComponent(`export async function load(url,context,next){const loaded=await next(url,context);if(!url.endsWith('/core/dist/numeric-domain.js'))return loaded;const text=typeof loaded.source==='string'?loaded.source:new TextDecoder().decode(loaded.source);return {...loaded,source:text+${JSON.stringify(count)}};}`));
const core=await import(pathToFileURL(path.join(source,'typescript/packages/core/dist/index.js')));
const {PolicyEvaluator}=core;
// The ruled linear interpolation, also used by the Python measurement.
const percentile=(samples,p)=>{const values=[...samples].sort((a,b)=>a-b),at=(values.length-1)*p,lo=Math.floor(at),hi=Math.ceil(at);return values[lo]+(at-lo)*(values[hi]-values[lo]);};
const {HIITL}=await import(pathToFileURL(path.join(source,'typescript/packages/sdk/dist/index.js')));
// No transport: the engine's start and first pull are stubbed, as the SDK's hybrid tests do; a pull lands through the
// cache as the engine writes it.
const {SyncEngine}=await import(pathToFileURL(path.join(source,'typescript/packages/sdk/dist/sync-engine.js')));
SyncEngine.prototype.start=function(){};SyncEngine.prototype.initialSync=async function(){return false;};
const shapes=JSON.parse(fs.readFileSync(shapesFile,'utf8'));
const iterations=1500,warmup=200,rows=[];
async function work(call){
 const counted={numeric_visits:0,admission_roots:0};globalThis.__admission=counted;
 try{await call();}finally{delete globalThis.__admission;}
 return counted;
}
{const probe=await work(()=>core.assertNumericDomain({a:[1]}));if(probe.admission_roots!==1||probe.numeric_visits!==3)throw Error('The walk is not counted: '+JSON.stringify(probe));}
async function measure(call){
 for(let n=0;n<warmup;n++)await call();
 const times=[],reported={ingest_ms:[],total_ms:[]};
 for(let n=0;n<iterations;n++){const start=performance.now();const decision=await call();times.push(performance.now()-start);for(const [key,values] of Object.entries(reported))values.push(decision.timing[key]);}
 const spread=values=>({p50_ms:percentile(values,.5),p95_ms:percentile(values,.95),p99_ms:percentile(values,.99)});
 return {...spread(times),reported:Object.fromEntries(Object.entries(reported).map(([key,values])=>[key,spread(values)])),...await work(call)};
}
async function through(client,version){
 const call=()=>client.evaluate({action:'send_email',parameters:{subject:'x',body:'y'},target:{to:'alice@example.com'}});
 try{await client._initialSyncPromise;if((await call()).policy_version!==version)throw Error('The held policy does not decide');return await measure(call);}
 finally{client.close();}
}
for(const row of shapes){
 const evaluator=new PolicyEvaluator();const measuredCore=await measure(()=>evaluator.evaluate(row.envelope,row.policy));
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'htl43-benchmark-')),file=path.join(directory,'policy.json');fs.writeFileSync(file,JSON.stringify(row.policy));
 try{
  const sdk=await through(new HIITL({sync:false,evaluation:'local',mode:'RESPECT_POLICY',org_id:row.envelope.org_id,environment:'dev',policy_path:file,audit_db_path:path.join(directory,'audit.db')}),row.policy.version);
  const hybrid={api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',mode:'RESPECT_POLICY',org_id:row.envelope.org_id,environment:'dev',cache_dir:path.join(directory,'cache'),cold_start_behavior:'observe-silent'};
  const pulled=new HIITL({...hybrid,audit_db_path:path.join(directory,'pull.db')});await pulled._initialSyncPromise;
  await pulled.syncCache.updatePolicies({policies:[{name:row.policy.name,active:true,content:JSON.parse(fs.readFileSync(file,'utf8'))}]});
  const sdk_pull=await through(pulled,row.policy.version);
  const sdk_disk=await through(new HIITL({...hybrid,audit_db_path:path.join(directory,'disk.db')}),row.policy.version);
  rows.push({shape:row.name,core:measuredCore,sdk,sdk_pull,sdk_disk});
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
}
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const files=(dir,ext)=>fs.readdirSync(path.join(source,dir),{recursive:true}).filter(f=>f.endsWith(ext)).sort().map(f=>path.join(dir,f));
// The measured source and build as one digest over each file's hash, so the record names no path (E4)
const sourceFiles=Object.fromEntries(['core','sdk'].flatMap(p=>[...files(`typescript/packages/${p}/src`,'.ts'),...files(`typescript/packages/${p}/dist`,'.js')]).map(f=>[f,sha(fs.readFileSync(path.join(source,f)))]));
const source_manifest_sha256=sha(JSON.stringify(sourceFiles));
fs.writeFileSync(output,JSON.stringify({source:label,source_manifest_sha256,shapes_sha256:sha(fs.readFileSync(shapesFile)),measurement_driver_sha256:sha(fs.readFileSync(fileURLToPath(import.meta.url))),runtime:process.version,iterations,warmup,rows},null,2)+'\n');
console.log(JSON.stringify(rows.map(r=>({[r.shape]:Object.fromEntries(Object.entries(r).filter(([k])=>k!=='shape').map(([k,v])=>[k,v.admission_roots]))}))));
