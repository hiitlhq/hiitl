import {expect,it} from 'vitest';
import {PolicyEvaluator} from '../../src/evaluator.js';
import {comparisonData,comparisonInputs,comparisonOutcome,modelObjects} from '../../../../test-support/json-comparison.js';

it.each(comparisonData.cases)('declared comparison answer: $id',row=>{
  const {policy,envelope}=comparisonInputs(row);
  expect(comparisonOutcome(new PolicyEvaluator().evaluate(envelope,policy))).toStrictEqual(row.expected);
});
it.each(comparisonData.operators.flatMap(operator=>[false,true].map(missing=>({operator,missing}))))('comparison retains null/absent gate: $operator $missing',row=>{
  const {policy,envelope}=comparisonInputs({...row,left:null,right:['in','not_in'].includes(row.operator)?[null]:null});
  if(row.missing)delete envelope.parameters.probe;
  expect(comparisonOutcome(new PolicyEvaluator().evaluate(envelope,policy))).toStrictEqual({decision:'BLOCK',allowed:false,reason_codes:['NO_MATCHING_RULE']});
});
const recursive=[
  {left:JSON.parse('{"__proto__":{"constructor":[null,true,0.1]}}'),right:JSON.parse('{"__proto__":{"constructor":[null,true,0.1]}}'),same:true},
  {left:JSON.parse('{"__proto__":1}'),right:{},same:false},
  {left:{constructor:1},right:{toString:1},same:false},
  {left:[1,2],right:[2,1],same:false},{left:[1],right:[1,1],same:false},{left:1,right:1.0,same:true},
  {left:'A',right:'a',same:false},
  {left:{a:[null,{x:true}]},right:{a:[null,{x:1}]},same:false},
];
it.each(recursive)('recursive values and own keys: $left $right',row=>{
  const {policy,envelope}=comparisonInputs({...row,operator:'equals'});
  expect(new PolicyEvaluator().evaluate(envelope,policy).allowed).toBe(row.same);
  envelope.parameters.other=row.right;policy.rules[0].conditions.value={$field:'parameters.other'};
  expect(new PolicyEvaluator().evaluate(envelope,policy).allowed).toBe(row.same);
});

it.each(modelObjects)('declared model objects compare supplied members: $field $left $right',row=>{
  const {policy,envelope}=comparisonInputs({...row,operator:'equals'});
  envelope[row.field]=row.left;policy.rules[0].conditions.field=row.field;
  expect(new PolicyEvaluator().evaluate(envelope,policy).allowed).toBe(row.same);
});
