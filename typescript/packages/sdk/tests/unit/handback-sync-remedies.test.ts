/** The same canonical member corpus at every sync/cache entry in both SDKs. */
import {it,expect,vi} from 'vitest';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import {NUMERIC_BOUND} from '@hiitl/core';
import {SyncClient} from '../../src/sync-client.js';
import {SyncCache} from '../../src/sync-cache.js';
import {SyncError} from '../../src/exceptions.js';
const rows=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_sync/cases.json'),'utf8')).cases;
it.each(rows)('$id keeps the channel, path, and declared remedy',async(row:any)=>{
 const data=structuredClone(row.input),channel=row.channel,dir=mkdtempSync(join(tmpdir(),'htl43-sync-'));
 const fetchImpl=vi.fn(async()=>new Response(JSON.stringify(row.entry==='upload'?{accepted:1}:data),{status:200}));
 const client=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:'org_1234567890abcdef',environment:'dev',fetchImpl});
 let call:()=>Promise<unknown>;
 if(row.entry==='cache'){
  const cache:any=new SyncCache({cache_dir:dir,org_id:'org_1234567890abcdef',environment:'dev'});
  const method=({policy:'updatePolicies',routes:'updateRoutes',kill_switches:'updateKillSwitches'} as Record<string,string>)[channel];call=()=>cache[method](data);
 }else if(row.entry==='upload')call=()=>client.uploadTelemetry(data.records);
 else call=({policy:()=>client.downloadPolicies(),routes:()=>client.downloadRoutes(),kill_switches:()=>client.pollKillSwitches(),audit:()=>client.uploadAudit([],1)} as Record<string,()=>Promise<unknown>>)[channel];
 try{await call();let at=data;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 let error:any;try{await call();}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(SyncError);expect(error.channel).toBe(channel);
 expect(error.message).toContain('<root>'+row.path.map((p:any)=>'['+JSON.stringify(p)+']').join(''));
 expect(error.message).toContain('JSON '+row.type);expect(error.message).toContain(String(NUMERIC_BOUND));
 for(const limit of Object.values(row.range))expect(error.message).toContain(String(limit));expect(error.message).not.toContain('pass the value as text');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
