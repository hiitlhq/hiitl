import {vi,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
const {roots}=vi.hoisted(()=>({roots:[] as any[]}));
vi.mock('../../../core/src/numeric-domain.js',async original=>{
 const actual=await original<any>();return {...actual,assertNumericDomain:(value:any,...args:any[])=>{if(value!==null && typeof value==='object')roots.push(value);return actual.assertNumericDomain(value,...args);}};
});
vi.mock('@hiitl/core',()=>import('../../../core/src/index.js'));
import {HIITL} from '../../src/client.js';
import {HostedClient} from '../../src/http-client.js';
import {createHostedConfig} from '../../src/config.js';
import {EnvelopeValidationError} from '../../src/exceptions.js';
import {NUMERIC_BOUND} from '@hiitl/core';
const rows=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_remedies/cases.json'),'utf8')).cases.filter((r:any)=>r.format==='envelope');
const env=rows[0].control;
const decision={action_id:'act_01234567890123456789',decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};
const options=(dir:string)=>({environment:'dev' as const,org_id:env.org_id,agent_id:'fixture',api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',audit_db_path:join(dir,'audit.db')});
it.each(rows)('exported hosted $id keeps envelope refusal',async(row:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-owned-')),client:any=new HostedClient(createHostedConfig(options(dir)));
 client._pushFirst=async()=>undefined;client._ask=async()=>[{status:200,data:decision},undefined];
 try{expect((await client.evaluate(row.control)).allowed).toBe(true);const data=structuredClone(row.control);let at=data;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 let error:any;try{await client.evaluate(data);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(EnvelopeValidationError);expect(error.message).toContain('<root>'+row.path.map((p:any)=>'['+JSON.stringify(p)+']').join(''));expect(error.message).toContain('JSON '+row.type);expect(error.message).toContain(String(NUMERIC_BOUND));expect(error.message).not.toContain('pass the value as text');
 }finally{client.close();rmSync(dir,{recursive:true,force:true});}
});
it.each(['public_sdk','hosted_component'])('%s admits each supplied hosted tree once',async entry=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-owned-'));
 const client:any=entry==='public_sdk'?new HIITL({...options(dir),evaluation:'remote',signature_key:'local-fixture-signing-secret'}):new HostedClient(createHostedConfig(options(dir)));
 const hosted=entry==='public_sdk'?client.hostedClient:client;hosted._pushFirst=async()=>undefined;hosted._ask=async()=>[{status:200,data:decision},undefined];
 try{roots.length=0;const answer=await(entry==='public_sdk'?client.evaluate({action:'read',parameters:{probe:1}}):client.evaluate(structuredClone(env)));expect(answer.allowed).toBe(true);expect(roots).toHaveLength(2);}
 finally{client.close();rmSync(dir,{recursive:true,force:true});}
});
it.each(['target','parameters'])('verifier cannot mutate admitted %s',async member=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-owned-')),file=join(dir,'policy.json'),supplied={probe:1};
 const policy={name:'owned',version:'v1.0.0',description:'owned',scope:{org_id:env.org_id,environment:'dev'},rules:[{name:'original',description:'original',priority:1,conditions:{field:member+'.probe',operator:'equals',value:1},decision:'ALLOW',reason_code:'ORIGINAL'}]};writeFileSync(file,JSON.stringify(policy));
 const client:any=new HIITL({sync:false,mode:'RESPECT_POLICY',policy_path:file,audit_db_path:join(dir,'audit.db'),principal_verifier:()=>{supplied.probe=NUMERIC_BOUND;return{sub:'verified'};}});
 try{const result=await client.evaluate({action:'read',principal_token:'fixture',[member]:supplied});expect(result.allowed).toBe(true);expect(result.reason_codes).toEqual(['ORIGINAL']);expect(client.auditLogger.getUnsynced().at(-1).envelope[member].probe).toBe(1);expect(supplied.probe).toBe(NUMERIC_BOUND);}
 finally{client.close();rmSync(dir,{recursive:true,force:true});}
});

import {HostedModeConfigSchema} from '../../src/config.js';
import {ConfigurationError} from '../../src/exceptions.js';
import {z} from 'zod';
const hostedNumbers=Object.entries(z.toJSONSchema(HostedModeConfigSchema,{io:"input",unrepresentable:"any"}).properties??{}).filter(([,declaration]:any)=>['number','integer'].includes(declaration.type));
it.each(hostedNumbers)('direct hosted constructor admits mutable supplied %s',(member,declaration:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-hosted-options-')),settings=createHostedConfig(options(dir));
 try{new HostedClient(settings).close();(settings as any)[member]=NUMERIC_BOUND;let error:any;try{new HostedClient(settings);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(ConfigurationError);expect(error.message).toContain('<root>["'+member+'"]');expect(error.message).toContain('JSON '+declaration.type);expect(error.message).toContain(String(NUMERIC_BOUND));expect(error.message).not.toContain('pass the value as text');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
