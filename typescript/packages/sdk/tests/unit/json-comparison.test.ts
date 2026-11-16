import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';import {join} from 'node:path';
import {dump} from 'js-yaml';import {expect,it} from 'vitest';
import {PolicyEvaluator} from '@hiitl/core';import {PolicyLoader} from '../../src/policy-loader.js';
import {comparisonData,comparisonInputs,comparisonOutcome,modelObjects} from '../../../../test-support/json-comparison.js';
it.each(comparisonData.cases.flatMap(row=>['json','yaml'].map(wire=>({...row,wire}))))('file comparison answer: $wire $id',row=>{
  const {policy,envelope}=comparisonInputs(row),directory=mkdtempSync(join(tmpdir(),'hiitl-comparison-'));
  try {
    const file=join(directory,`policy.${row.wire}`);
    writeFileSync(file,row.wire==='json'?JSON.stringify(policy):dump(policy));
    const loaded=new PolicyLoader(file).load();
    expect(comparisonOutcome(new PolicyEvaluator().evaluate(envelope,loaded))).toStrictEqual(row.expected);
  } finally {rmSync(directory,{recursive:true,force:true});}
});

it.each(modelObjects.flatMap(row=>['json','yaml'].map(wire=>({...row,wire}))))('file model objects compare supplied members: $wire $field $left $right',row=>{
  const {policy,envelope}=comparisonInputs({...row,operator:'equals'}),directory=mkdtempSync(join(tmpdir(),'hiitl-comparison-model-'));
  envelope[row.field]=row.left;policy.rules[0].conditions.field=row.field;
  try {
    const file=join(directory,`policy.${row.wire}`);
    writeFileSync(file,row.wire==='json'?JSON.stringify(policy):dump(policy));
    expect(new PolicyEvaluator().evaluate(envelope,new PolicyLoader(file).load()).allowed).toBe(row.same);
  } finally {rmSync(directory,{recursive:true,force:true});}
});
