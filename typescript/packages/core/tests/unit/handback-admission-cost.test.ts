/** 88579bbd: the five measured shapes admit each supplied root exactly once. */
import {vi,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
const {roots}=vi.hoisted(()=>({roots:[] as unknown[]}));
vi.mock('../../src/numeric-domain.js',async original=>{
 const actual=await original<any>();return {...actual,assertNumericDomain:(value:unknown,...args:any[])=>{
  if(value!==null && typeof value==='object')roots.push(value);
  return actual.assertNumericDomain(value,...args);
 }};
});
import {PolicyEvaluator} from '../../src/evaluator.js';
const shapes=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/shapes.json'),'utf8'));
const measured=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/admission_cost/baseline-core-sdk-typescript.json'),'utf8'));
const history=new Map(measured.rows.map((row:any)=>[row.shape,row]));
it.each(shapes)('$name has only the two supplied input walks',(row:any)=>{
 roots.length=0;new PolicyEvaluator().evaluate(row.envelope,row.policy);
 const prior=(history.get(row.name) as any).core;
 console.log('HTL43_ADMISSION',JSON.stringify({shape:row.name,entry:'core',before:prior,admission_roots:roots.length}));
 expect(roots.length).toBeLessThan(prior.admission_roots);
 expect(roots).toHaveLength(2);
 expect(roots[0]).toBe(row.envelope);expect(roots[1]).toBe(row.policy);
});
