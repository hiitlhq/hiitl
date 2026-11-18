/** 88579bbd: numeric admission changes parsing, not exported object methods. */
import {it,expect} from 'vitest';
import {z} from 'zod';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {EnvelopeSchema,PolicySetSchema,DecisionSchema,RouteSchema,NUMERIC_BOUND} from '@hiitl/core';
import {LocalModeConfigSchema,HostedModeConfigSchema} from '../../src/config.js';
const root=resolve(__dirname,'../../../../../');
const read=(p:string)=>JSON.parse(readFileSync(resolve(root,p),'utf8'));
const env=read('tests/conformance/cases/references/test_143_field_reference_equals_compares_two_fields.json').envelope;
const controls:Record<string,unknown>={EnvelopeSchema:env,PolicySetSchema:{name:'surface',version:'v1.0.0',description:'surface',scope:{org_id:env.org_id,environment:'dev'},rules:[]},DecisionSchema:{action_id:env.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}},RouteSchema:read('tests/conformance/typed_members/witnesses.json').witnesses[0].input,LocalModeConfigSchema:{},HostedModeConfigSchema:{environment:'dev',agent_id:'fixture',org_id:env.org_id,api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid'}};
const schemas={EnvelopeSchema,PolicySetSchema,DecisionSchema,RouteSchema,LocalModeConfigSchema,HostedModeConfigSchema};
for(const [name,exported] of Object.entries(schemas))it(`${name} keeps object methods and pre-projection admission`,async()=>{
 const schema=exported as any;
 expect(schema).toBeInstanceOf(z.ZodObject);
 expect(typeof schema.shape).toBe('object');
 expect(typeof schema.extend).toBe('function');
 expect(typeof schema.pick).toBe('function');
 const control=controls[name] as Record<string,unknown>;
 expect(schema.safeParse(control).success).toBe(true);
 // These three owning schemas already have whole-object refinements. Zod
 // refuses pick on them; preserving that restriction preserves the object API.
 if(['PolicySetSchema','DecisionSchema','RouteSchema'].includes(name))expect(()=>schema.pick({})).toThrow('refinements');
 else{
  const picked=schema.pick({});expect(picked.parse({})).toEqual({});
  expect(picked.safeParse({unread:NUMERIC_BOUND}).success).toBe(false);
  expect((await picked.safeParseAsync({unread:NUMERIC_BOUND})).success).toBe(false);
  expect(z.object({nested:picked}).safeParse({nested:{unread:NUMERIC_BOUND}}).success).toBe(false);
 }
 const extended=schema.extend({numeric_probe:z.number()});
 expect(extended.safeParse({...control,numeric_probe:1}).success).toBe(true);
 expect(extended.safeParse({...control,numeric_probe:NUMERIC_BOUND}).success).toBe(false);
 expect(schema.safeParse({...control,unread:NUMERIC_BOUND}).success).toBe(false);
 expect((await schema.safeParseAsync({...control,unread:NUMERIC_BOUND})).success).toBe(false);
 expect(z.object({nested:schema}).safeParse({nested:{...control,unread:NUMERIC_BOUND}}).success).toBe(false);
 const response=extended.safeParse({...control,numeric_probe:NUMERIC_BOUND});
 expect(response.error?.issues[0].path).toEqual(['numeric_probe']);
 expect(response.error?.issues[0].message).toContain('number');
 expect(response.error?.issues[0].message).not.toContain('pass the value as text');
});
