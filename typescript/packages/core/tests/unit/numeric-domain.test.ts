/** HTL43 d82fe0f5; independent source-derived held-number corpus. */
import {createHash,createHmac} from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canonicalJson, canonicalHash, auditContentHash, envelopeSignedForm, envelopeSignature, envelopeHash, envelopeVerifies } from '../../src/canonical.js';
import * as core from '../../src/index.js';

type Case = { id:string; kind:string; input:string; expected_accept:boolean; canonical:string|null };
const corpus = JSON.parse(readFileSync(resolve(__dirname, '../../../../../tests/conformance/numeric_domain/cases.json'),'utf8')) as {bound:number;cases:Case[]};
const value = (row:Case):unknown => row.kind === 'native' ? Number(row.input) : JSON.parse(row.input);
const wraps = [
  {name:'root',wrap:(v:unknown)=>v,path:[]},
  {name:'object',wrap:(v:unknown)=>({plain:true,sample:v}),path:['sample']},
  {name:'array-object',wrap:(v:unknown)=>({outer:[{ok:null},{sample:v}]}),path:['outer',1,'sample']},
];
for (const form of wraps) describe(form.name,()=>{
  it.each(corpus.cases)('$id admits the supplied held value',(row)=>{
    const v=form.wrap(value(row));
    if(row.expected_accept){
      let expected=row.canonical;
      if(form.name==='object')expected='{"plain":true,"sample":'+expected+'}';
      if(form.name==='array-object')expected='{"outer":[{"ok":null},{"sample":'+expected+'}]}';
      core.assertNumericDomain(v);
      expect(canonicalJson(v)).toBe(expected);
    }else{
      let error:unknown;
      try{core.assertNumericDomain(v);}catch(e){error=e;}
      expect(error).toBeInstanceOf(Error);
      expect((error as Error & {path:unknown}).path).toEqual(form.path);
      expect(String(error).toLowerCase()).toContain('text');
    }
  });
});
// 93d/5203 supersedes hash/sign admission, preserving the original C bytes.
const historical=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/audit_hash/case_001_fixed_record.json'),'utf8'));
const canonical=historical.expected.canonical_envelope as string;
const signed=canonical.replace(',"signature":"'+historical.envelope.signature+'"','');
const secret='local-fixture-key';
const signature=createHmac('sha256',secret).update(signed).digest('hex');
const calls={
  canonicalHash:{call:()=>canonicalHash(historical.envelope),expected:createHash('sha256').update(canonical).digest('hex')},
  auditContentHash:{call:()=>auditContentHash(historical.event_id,historical.envelope,historical.decision),expected:historical.expected.content_hash},
  envelopeSignedForm:{call:()=>envelopeSignedForm(historical.envelope),expected:signed},
  envelopeSignature:{call:()=>envelopeSignature(secret,historical.envelope),expected:signature},
  envelopeHash:{call:()=>envelopeHash(historical.envelope),expected:createHash('sha256').update(signed).digest('hex')},
};
it.each(Object.entries(calls))('%s computes the historical form',(_name,{call,expected})=>{
  expect(call).not.toThrow();
  expect(call()).toBe(expected);
  expect(envelopeVerifies(secret,{...historical.envelope,signature})).toBe(true);
});
it('the pure numeric guard preserves own open data and reports the exact path',()=>{
  const api=core as unknown as {assertNumericDomain?:(value:unknown,path?:Array<string|number>)=>void};
  expect(typeof api.assertNumericDomain).toBe('function');
  const original=JSON.parse('{"__proto__":[true,null,"9007199254740993",{"fraction":0.1}]}');
  const before=JSON.stringify(original);
  expect(api.assertNumericDomain!(original)).toBeUndefined();
  expect(JSON.stringify(original)).toBe(before);
  let error:unknown;
  try{api.assertNumericDomain!(JSON.parse('{"__proto__":['+corpus.bound+']}'),['input']);}catch(e){error=e;}
  expect(error).toBeInstanceOf(core.NumericDomainError);
  expect((error as {path:unknown}).path).toEqual(['input','__proto__',0]);
});

it.each(corpus.cases)('$id uses the same integer domain',row=>{
  const held=value(row);
  const admitted=row.expected_accept && typeof held==='number' && Number.isInteger(held);
  const parsed=core.integer().safeParse(held);
  expect(parsed.success).toBe(admitted);
  if(parsed.success)expect(parsed.data===held).toBe(true);
});
it.each(['envelope','decision',...core.AUDIT_FURTHER])('%s supplied audit term is admitted before hashing',member=>{
  const data:any={envelope:{},decision:{}};data[member]={probe:corpus.bound};
  const {envelope,decision,...further}=data;let error:any;
  try{core.assertNumericDomain(data);}catch(e){error=e;}
  expect(error).toBeInstanceOf(core.NumericDomainError);
  expect(error.path).toEqual([member,'probe']);
});
it.each(['envelope','decision',...core.AUDIT_FURTHER])('%s historical audit term is computed under C',member=>{
  const data:any={envelope:{},decision:{}};data[member]={probe:corpus.bound};
  const fixed='{"probe":'+String(corpus.bound)+'}';
  const terms=['evt_numeric',member==='envelope'?fixed:'{}',member==='decision'?fixed:'{}'];
  if((core.AUDIT_FURTHER as readonly string[]).includes(member))terms.push(fixed);
  const expected=createHash('sha256').update(terms.join(':')).digest('hex');
  const {envelope,decision,...further}=data;let actual:unknown;
  expect(()=>{actual=auditContentHash('evt_numeric',envelope,decision,further);}).not.toThrow();
  expect(actual).toBe(expected);
});
