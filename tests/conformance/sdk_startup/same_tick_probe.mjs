import fs from 'node:fs';import {tmpdir} from 'node:os';import {join} from 'node:path';import {pathToFileURL} from 'node:url';
const [root,fixture,samples]=process.argv.slice(2);
const {HIITL}=await import(pathToFileURL(join(root,'typescript/packages/sdk/dist/client.js')));
globalThis.fetch=async()=>new Response(JSON.stringify({detail:'fixture offline'}),{status:401});
const policy=JSON.parse(fs.readFileSync(join(fixture,'policy.json'),'utf8')),rows=[];
for(const mode of ['local','hybrid'])for(const suffix of ['json','yaml']) {
 const dir=fs.mkdtempSync(join(tmpdir(),'htl45-tick-')),path=join(dir,'policy.'+suffix);
 const old={...policy,version:'v1.0.0',rules:[{...policy.rules[0],decision:'ALLOW'}]},fresh={...policy,version:'v2.0.0'};
 const beforeText=JSON.stringify(old),afterText=JSON.stringify(fresh);if(beforeText.length!==afterText.length)throw new Error('Rewrite must be same-size');
 fs.writeFileSync(path,beforeText);const epoch=new Date('2026-11-01T00:00:00Z');
 const options={policy_path:path,org_id:policy.scope.org_id,mode:'RESPECT_POLICY',audit_db_path:join(dir,'audit.db')};
 if(mode==='hybrid')Object.assign(options,{api_key:'local-startup-fixture-key',server_url:'https://fixture.invalid',cache_dir:join(dir,'cache')});
 const client=new HIITL(options);
 try {
  for(let sample=0;sample<Number(samples);sample++) {
   fs.writeFileSync(path,beforeText);fs.utimesSync(path,epoch,epoch);client.policyLoader.invalidateCache();client.policyLoader.load();
   const before=fs.statSync(path,{bigint:true});fs.writeFileSync(path,afterText);fs.utimesSync(path,epoch,epoch);const after=fs.statSync(path,{bigint:true});
   const fields=['dev','ino','size','mtimeNs','ctimeNs'],tied=fields.every(k=>before[k]===after[k]);
   const decision=await client.evaluate({action:'guarded',parameters:{amount:100}});
   rows.push({mode,format:suffix,sample,tied,before:Object.fromEntries(fields.map(k=>[k,String(before[k])])),
    after:Object.fromEntries(fields.map(k=>[k,String(after[k])])),decision:decision.decision,version:decision.policy_version});
  }
  if(client.auditLogger.getUnsynced(Number(samples)).some(r=>r.decision.decision!=='BLOCK'))throw new Error('The audit answer must match the new policy');
 } finally {await client._initialSyncPromise;client.close();fs.rmSync(dir,{recursive:true,force:true});}
}
console.log('HTL45_TICKS '+JSON.stringify(rows));
