/**
 * HTL-43 gap 303, decided by the record (b88dd3e3): "the clock starts where `evaluate()` starts, in both cores. The
 * admission of the call's tree is counted in `ingest_ms` and in `total_ms`" (decision_response.md timing schema). A
 * controlled clock moves only while the admitter walks a tree the call supplied, by the cell's own step, so the reported
 * times are the step times the walks, exactly. Mirrors python/hiitl/core/tests/test_handback_admission_timing.py.
 */
import {vi,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
const {clock}=vi.hoisted(()=>({clock:{now:100}}));
const STEP=125;
vi.mock('../../src/numeric-domain.js',async original=>{
 const actual=await original<any>();return {...actual,assertNumericDomain:(value:unknown,path:(string|number)[]=[],...args:any[])=>{
  // Each supplied tree's walk, at its root; the core walks the envelope, the policy and a route's answer.
  if(value!==null && typeof value==='object' && path.length===1 && ['envelope','policy','enrichment'].includes(String(path[0])))clock.now+=STEP;
  return actual.assertNumericDomain(value,path,...args);
 }};
});
import {PolicyEvaluator} from '../../src/evaluator.js';
const shapes=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/shapes.json'),'utf8'));
const cases=shapes.flatMap((row:any)=>[undefined,{check:{score:2}}].map(enrichment=>({name:row.name,routed:Boolean(enrichment),row,enrichment})));
it.each(cases)('$name (route answer: $routed) times the admission of each supplied tree',({row,enrichment}:any)=>{
 const now=vi.spyOn(performance,'now').mockImplementation(()=>clock.now);
 try{
  const walks=enrichment?3:2;
  expect(new PolicyEvaluator().evaluate(row.envelope,row.policy,'RESPECT_POLICY',enrichment).timing).toEqual({ingest_ms:walks*STEP,evaluation_ms:0,total_ms:walks*STEP});
 }finally{now.mockRestore();}
});
