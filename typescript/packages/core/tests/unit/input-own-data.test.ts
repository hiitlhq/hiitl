/** HTL-43: accepted own data survives every real core read/copy without changing prototypes. */
import { expect, it } from 'vitest';
import { EnvelopeSchema, PolicySetSchema, DecisionSchema } from '../../src/types.js';
import { RouteSchema } from '../../src/route-types.js';
import { PolicyEvaluator } from '../../src/evaluator.js';
import { resolveFieldPath } from '../../src/utils.js';
import { canonicalJson, envelopeSignature, envelopeVerifies } from '../../src/canonical.js';
import { Redaction, KEY_BYTES } from '../../src/redaction.js';
import { payload, answerFields } from '../../src/routing.js';
import { ownData, envelopeInput, policyInput, routeInput } from '../../../../test-support/own-data.js';

function retained(actual: unknown, expected: Record<string, unknown>) {
  // Compare own descriptors: matcher constructor heuristics must not reinterpret an own constructor data value.
  expect(Object.keys(actual as object).sort()).toStrictEqual(Object.keys(expected).sort());
  expect(Object.getPrototypeOf(actual)).toBe(Object.prototype);
  for (const key of Object.keys(expected)) {
    expect(Object.getOwnPropertyDescriptor(actual, key)).toStrictEqual({value:expected[key],writable:true,enumerable:true,configurable:true});
  }
}

it.each(['target','parameters','metadata'])('keeps every supplied Envelope %s key as own data', member => {
  const data=ownData(); const before=JSON.stringify(data);
  const parsed=EnvelopeSchema.parse(envelopeInput({[member]:data}));
  retained(parsed[member as 'target'|'parameters'|'metadata'],data);
  expect(JSON.stringify(data)).toBe(before);
  expect(Object.hasOwn(Object.prototype,'marker')).toBe(false);
});

it('keeps policy records, nested test data and rate-compilation leftovers', () => {
  const input=policyInput();
  Object.defineProperty(input.metadata,'rate_limits',{value:[{limit:2,window_seconds:60,scope:'org'}],enumerable:true});
  const parsed=PolicySetSchema.parse(input);
  retained(parsed.metadata,ownData());
  retained(parsed.rules[0].metadata,ownData());
  retained(parsed.rules[0].remediation?.details,ownData());
  retained(parsed.rules[0].tests?.[0].envelope.parameters,ownData());
  expect(parsed.rules.map(rule=>rule.name)).toStrictEqual(['hold','metadata.rate_limits[0]']);
  expect(parsed.rules[1].metadata?.compiled_from).toStrictEqual({path:'metadata.rate_limits[0]',entry:{limit:2,window_seconds:60,scope:'org'}});
});

it('keeps an optional native undefined metadata value absent while refusing null data',()=>{
  const omitted=policyInput();delete (omitted as Partial<typeof omitted>).metadata;
  const absent=PolicySetSchema.parse(omitted);
  const result=PolicySetSchema.safeParse({...omitted,metadata:undefined});
  expect(result.success).toBe(true);
  if(result.success)expect(result.data).toStrictEqual({...absent,metadata:undefined});
  expect(PolicySetSchema.safeParse({...omitted,metadata:null}).success).toBe(false);
});

it('preserves own context and enrichment keys through the decision model',()=>{
  const enrichment=Object.fromEntries(Object.keys(ownData()).map(key=>[key,ownData()]));
  const result=DecisionSchema.safeParse({action_id:'act_fixture000000000000',decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0},escalation_context:ownData(),enrichment});
  expect(result.success).toBe(true);
  if(!result.success)return;
  retained(result.data.escalation_context,ownData());
  retained(result.data.enrichment,enrichment);
  for(const key of Object.keys(enrichment))retained(result.data.enrichment?.[key],ownData());
});

it('keeps open route metadata and typed map names without a reserved-name exception', () => {
  retained(RouteSchema.parse(routeInput()).metadata,ownData());
  const input={name:'own-map',version:'v1.0.0',direction:'inbound',timing:'async',inbound:{permissions:{can_signal:true},payload_mapping:{metadata:Object.fromEntries(Object.keys(ownData()).map(key=>[key,'$.written']))}}};
  const parsed=RouteSchema.parse(input);
  retained(parsed.inbound?.payload_mapping?.metadata,input.inbound.payload_mapping.metadata);
  input.inbound.payload_mapping.metadata.__proto__=17 as unknown as string;
  const refused=RouteSchema.safeParse(input);
  expect(refused.success).toBe(false);
  if(!refused.success)expect(refused.error.issues.map(issue=>issue.path)).toContainEqual(['inbound','payload_mapping','metadata','__proto__']);
});

it('reads own names through evaluation and leaves inherited names absent', () => {
  const input=envelopeInput({parameters:ownData()});
  const parsed=EnvelopeSchema.parse(input);
  for(const key of Object.keys(ownData()))expect(resolveFieldPath(parsed,`parameters.${key}.marker`)).toBe('written');
  expect(new PolicyEvaluator().evaluate(input,policyInput()).decision).toBe('BLOCK');
  const inherited=Object.create({marker:'inherited'});
  expect(resolveFieldPath({parameters:inherited},'parameters.marker')).toBeNull();
  expect(Object.getPrototypeOf(input.parameters)).toBe(Object.prototype);
});

it('preserves own data through route copies, canonicalization, signing and JSON', () => {
  const env=EnvelopeSchema.parse(envelopeInput({target:ownData(),parameters:ownData(),metadata:ownData()}));
  const route={...routeInput(),context:{fields:[{field_path:'parameters.__proto__'}]},response_schema:{required_fields:['__proto__'],optional_fields:['toString']}};
  retained(payload(route,'hold',env).fields as Record<string,unknown>,{'parameters.__proto__':ownData().__proto__});
  retained(answerFields(route,ownData()),Object.fromEntries(['__proto__','toString'].map(key=>[key,ownData()[key]])));
  const written=JSON.parse(canonicalJson(env));
  retained(written.parameters,ownData());
  const signed={...env,signature:envelopeSignature('fixture-signing-key',env)};
  expect(envelopeVerifies('fixture-signing-key',JSON.parse(JSON.stringify(signed)))).toBe(true);
  retained(JSON.parse(JSON.stringify(signed)).parameters,ownData());
  expect(Object.hasOwn(Object.prototype,'marker')).toBe(false);
});

it('preserves action and parameter names through redaction declaration and record copies', () => {
  const declaration=JSON.parse('{"__proto__":["__proto__"]}') as Record<string,string[]>;
  const redaction=Redaction.declared([],declaration).keyed(new Uint8Array(KEY_BYTES).fill(7));
  retained(redaction.recordedParameters,declaration);
  const env=EnvelopeSchema.parse(envelopeInput({action:'__proto__',parameters:ownData()}));
  const [stored]=redaction.record(env,{decision:'ALLOW'});
  expect(Object.hasOwn(stored.parameters,'__proto__')).toBe(true);
  expect(stored.parameters.__proto__).toStrictEqual(ownData().__proto__);
  expect(Object.getPrototypeOf(stored.parameters)).toBe(Object.prototype);
  retained(env.parameters,ownData());
});
