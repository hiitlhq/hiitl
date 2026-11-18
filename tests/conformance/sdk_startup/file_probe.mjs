import {mkdtempSync,readFileSync,writeFileSync,chmodSync,unlinkSync,utimesSync,existsSync,rmSync,renameSync} from 'node:fs';
import {join} from 'node:path';import {tmpdir} from 'node:os';import {pathToFileURL} from 'node:url';
for(const key of Object.keys(process.env))if(key.toUpperCase().startsWith('HIITL_'))delete process.env[key];
const {HIITL}=await import(pathToFileURL(join(process.argv[2],'typescript/packages/sdk/dist/client.js')));
globalThis.fetch=async()=>new Response(JSON.stringify({detail:'fixture offline'}),{status:401});
const policy={name:'startup',version:'v1.0.0',description:'A guarded action',scope:{org_id:'org_startup000000000000',environment:'dev'},rules:[{name:'guard',description:'Guard the action',priority:100,conditions:{field:'action',operator:'equals',value:'guarded'},decision:'ALLOW',reason_code:'STARTUP_GUARD'}]},rows=[];
for(const mode of ['local','hybrid'])for(const suffix of ['json','yaml'])for(const when of ['construction','after-construction'])for(const fault of ['missing','unreadable','unparsable','unparsable-same-mtime','valid-same-mtime','replacement-same-mtime']){
 if(when==='construction'&&/^(valid|replacement)/.test(fault))continue;
 const dir=mkdtempSync(join(tmpdir(),'htl45-error-')),p=join(dir,'policy.'+suffix);writeFileSync(p,JSON.stringify(policy));
 // Whole seconds preserve mtime exactly through Node's utimes interface.
 const epoch=new Date('2026-11-01T00:00:00Z');utimesSync(p,epoch,epoch);let client,answer,readable;
 const damage=()=>{
  if(fault==='missing')unlinkSync(p);else if(fault==='unreadable')chmodSync(p,0);else{
   const changed=structuredClone(policy);changed.version='v2.0.0';changed.rules[0].decision='BLOCK';
   const text=/^(valid|replacement)/.test(fault)?JSON.stringify(changed):'{not json';
   if(fault.startsWith('replacement')){const other=join(dir,'replacement');writeFileSync(other,text);utimesSync(other,epoch,epoch);renameSync(other,p);}
   else{writeFileSync(p,text);utimesSync(p,epoch,fault.endsWith('same-mtime')?epoch:new Date(epoch.getTime()+1000));}
  }
 };
 const readAttempt=()=>{try{readFileSync(p);return true;}catch{return false;}};
 try{
  if(when==='construction'){damage();readable=readAttempt();}
  const options={org_id:policy.scope.org_id,mode:'RESPECT_POLICY',policy_path:p,audit_db_path:join(dir,'audit.db')};
  if(mode==='hybrid')Object.assign(options,{api_key:'local-startup-fixture-key',server_url:'https://fixture.invalid',cache_dir:join(dir,'cache')});
  client=new HIITL(options);if(when==='after-construction'){damage();readable=readAttempt();}
  const d=await client.evaluate({action:'guarded'});answer={decision:d.decision,version:d.policy_version,reasons:d.reason_codes,record_decisions:client.auditLogger.getUnsynced(10).map(r=>r.decision.decision)};
 }catch(error){answer={error:error.constructor.name,reason:error.reason};}
 finally{if(existsSync(p))chmodSync(p,0o600);if(client){await client._initialSyncPromise;client.close();}rmSync(dir,{recursive:true,force:true});}
 rows.push({mode,format:suffix,when,fault,readable,...answer});
}
console.log('HTL45_FILES '+JSON.stringify(rows));
