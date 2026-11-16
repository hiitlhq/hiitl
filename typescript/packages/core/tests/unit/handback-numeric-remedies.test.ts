import {it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {EnvelopeSchema,PolicySetSchema,DecisionSchema} from '../../src/types.js';
import {RouteSchema} from '../../src/route-types.js';
import {NUMERIC_BOUND} from '../../src/numeric-domain.js';
const schemas:any={envelope:EnvelopeSchema,policy:PolicySetSchema,routes:RouteSchema,decision:DecisionSchema};
const rows=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_remedies/cases.json'),'utf8')).cases;
it.each(rows)('$id refusal names the owning declaration',(row:any)=>{
 const schema=schemas[row.format];expect(schema.safeParse(row.control).success).toBe(true);
 const value=structuredClone(row.control);let at=value;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 const result=schema.safeParse(value);expect(result.success).toBe(false);
 const message=result.error.issues.map((issue:any)=>issue.message).join(' ');
 expect(message).toContain('<root>'+row.path.map((p:any)=>'['+JSON.stringify(p)+']').join(''));
 expect(message).toContain('JSON '+row.type);expect(message).toContain(String(NUMERIC_BOUND));
 for(const limit of Object.values(row.range))expect(message).toContain(String(limit));
 expect(message).not.toContain('pass the value as text');
});

const otherRows=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_remedies/cases.json'),'utf8')).other_cases;
it.each(otherRows)('$id does not direct a closed or typed member to text',(row:any)=>{
 const schema=schemas[row.format];expect(schema.safeParse(row.control).success).toBe(true);
 const value=structuredClone(row.control);let at=value;for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 const result=schema.safeParse(value);expect(result.success).toBe(false);
 const message=result.error.issues.map((issue:any)=>issue.message).join(' ');
 expect(message).toContain('<root>'+row.path.map((p:any)=>'['+JSON.stringify(p)+']').join(''));
 expect(message).not.toContain('pass the value as text');
 expect(message).toContain(row.type==='undeclared'?'not declared':'requires a JSON ');
});

import {PolicyEvaluator} from '../../src/evaluator.js';
import {NumericDomainError} from '../../src/numeric-domain.js';
it.each(rows.filter((r:any)=>['envelope','policy'].includes(r.format)))('$id evaluator reads owning input',(row:any)=>{
 const terms:any={envelope:structuredClone(rows.find((r:any)=>r.format==='envelope').control),policy:structuredClone(rows.find((r:any)=>r.format==='policy').control)};terms[row.format]=structuredClone(row.control);
 new PolicyEvaluator().evaluate(terms.envelope,terms.policy);
 let at=terms[row.format];for(const part of row.path.slice(0,-1))at=at[part];at[row.path.at(-1)]=NUMERIC_BOUND;
 let error:any;try{new PolicyEvaluator().evaluate(terms.envelope,terms.policy);}catch(caught){error=caught;}
 expect(error).toBeInstanceOf(NumericDomainError);expect(error.path).toEqual([row.format,...row.path]);expect(error.message).toContain('JSON '+row.type);expect(error.message).not.toContain('pass the value as text');
});
