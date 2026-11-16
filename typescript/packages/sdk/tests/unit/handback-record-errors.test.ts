/** Canonical declarations at the public record writer and hosted response entry. */
import {it,expect} from 'vitest';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import {AuditLogger} from '../../src/audit.js';
import {HostedClient} from '../../src/http-client.js';
import {createHostedConfig} from '../../src/config.js';
import {AuditLogError,ServerError} from '../../src/exceptions.js';
import {NUMERIC_BOUND} from '@hiitl/core';
const members=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_remedies/cases.json'),'utf8')).cases;
const env={schema_version:'v2.0',org_id:'org_1234567890abcdef',environment:'dev',agent_id:'fixture',action_id:'act_01234567890123456789',idempotency_key:'numeric',action:'read',operation:'execute',target:{},parameters:{},timestamp:'2026-11-14T00:00:00Z',signature:'0'.repeat(64)};
const decision={action_id:env.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};
function invalid(row:any){const value=structuredClone(row.control);let at=value;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;return value;}
function remedy(error:any,row:any,prefix:string[]=[]){expect(error.message).toContain('<root>'+[...prefix,...row.path].map(p=>'['+JSON.stringify(p)+']').join(''));expect(error.message).toContain('JSON '+row.type);expect(error.message).toContain(String(NUMERIC_BOUND));for(const limit of Object.values(row.range))expect(error.message).toContain(String(limit));expect(error.message).not.toContain('pass the value as text');}
it.each(members.filter((r:any)=>['envelope','decision'].includes(r.format)))('new record $id',(row:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-record-')),writer=new AuditLogger(join(dir,'audit.db'));
 const terms:any={envelope:structuredClone(env),decision:structuredClone(decision)};terms[row.format]=row.control;
 try{const event=writer.write(terms.envelope,terms.decision);expect(writer.verifyIntegrity(event)).toBe(true);const before=writer.getUnsynced();terms[row.format]=invalid(row);
 let error:any;try{writer.write(terms.envelope,terms.decision);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(AuditLogError);expect(error.reason).toBeUndefined();remedy(error,row,[row.format]);expect(writer.getUnsynced()).toEqual(before);
 }finally{writer.close();rmSync(dir,{recursive:true,force:true});}
});
it.each(members.filter((r:any)=>r.format==='decision'))('hosted reply $id',async(row:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-reply-')),client:any=new HostedClient(createHostedConfig({environment:'dev',agent_id:'fixture',org_id:env.org_id,api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',audit_db_path:join(dir,'audit.db')}));
 let data=structuredClone(row.control);client._pushFirst=async()=>undefined;client._ask=async()=>[{status:200,data},undefined];
 try{expect((await client.evaluate(env)).action_id).toBe(data.action_id);data=invalid(row);let error:any;try{await client.evaluate(env);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(ServerError);expect(error.status_code).toBe(200);expect(error.error_code).toBe('UNKNOWN_ERROR');remedy(error,row);
 }finally{client.close();rmSync(dir,{recursive:true,force:true});}
});
