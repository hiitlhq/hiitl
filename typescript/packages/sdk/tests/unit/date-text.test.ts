import {it,expect,afterEach} from 'vitest';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join} from 'node:path';import yaml from 'js-yaml';
import {PolicyEvaluator,OperatorKindError,EnvelopeSchema,envelopeHash,envelopeSignature,envelopeVerifies,auditContentHash} from '@hiitl/core';
import {HIITL} from '../../src/client.js';import {PolicyLoader} from '../../src/policy-loader.js';
import {dateData,lexicalDates,dateHashes} from '../../../../test-support/date-text.js';
const dirs:string[]=[];const clients:HIITL[]=[];
afterEach(()=>{clients.splice(0).forEach(c=>c.close());dirs.splice(0).forEach(d=>rmSync(d,{recursive:true,force:true}));});
function file(policy:any,wire:string){const dir=mkdtempSync(join(tmpdir(),'date-text-'));dirs.push(dir);const path=join(dir,`policy.${wire}`);writeFileSync(path,wire==='json'?JSON.stringify(policy):yaml.dump(policy));return path;}
for(const wire of ['json','yaml'])it.each(dateData.cases)(`file date operator answer ${wire}: $id`,(row:any)=>{
 const policy=new PolicyLoader(file(row.policy,wire)).load();const run=()=>new PolicyEvaluator().evaluate(row.envelope,policy,'RESPECT_POLICY');
 if(row.expected==='error')expect(run).toThrow(OperatorKindError);else expect(run().allowed).toBe(row.expected);
});
it.each(lexicalDates)('original lexical SDK record signature hash and replay: $id',async(row:any)=>{
 const vector=dateHashes[row.id];const raw=structuredClone(vector.envelope);const secret='date-text-fixture';
 const h=new HIITL({org_id:raw.org_id,environment:raw.environment,agent_id:raw.agent_id,policy_path:file(row.policy,'json'),audit_db_path:':memory:',signature_key:secret,mode:'RESPECT_POLICY',enable_rate_limiting:false});clients.push(h);const client=h as any;
 const parsed=EnvelopeSchema.parse(raw);expect(parsed).toEqual(raw);expect(envelopeVerifies(secret,parsed)).toBe(true);
 const decision=await client._decided(parsed,undefined);expect([decision.decision,decision.allowed]).toEqual(['ALLOW',true]);expect(decision.envelope_hash).toBe(vector.envelope_hash);
 const stored=client.auditLogger.getUnsynced(10);expect(stored).toHaveLength(1);expect(stored[0].envelope).toEqual(raw);
 expect(stored[0].content_hash).toBe(auditContentHash(stored[0].event_id,stored[0].envelope,stored[0].decision));
 expect(new PolicyEvaluator().evaluate(stored[0].envelope,client.policyLoader.load(),'RESPECT_POLICY').allowed).toBe(true);
});
