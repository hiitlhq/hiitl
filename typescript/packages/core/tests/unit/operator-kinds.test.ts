import {expect,it} from 'vitest';
import {PolicyEvaluator} from '../../src/evaluator.js';
import {PolicySetSchema} from '../../src/types.js';
import {operandData,operandInputs,evaluateAnswer} from '../../../../test-support/operator-kinds.js';

it.each(operandData.cases)('source operand answer: $id',row=>{
  const {policy,envelope}=operandInputs(row);const parsed=PolicySetSchema.safeParse(policy);
  if(!parsed.success){expect(row.expected).toEqual({stage:'load'});expect(String(parsed.error)).toContain(row.operator);expect(String(parsed.error)).toContain('parameters.probe');return;}
  const {actual,error}=evaluateAnswer(new PolicyEvaluator(),envelope,parsed.data);
  expect(actual).toEqual(row.expected);
  if(error){expect(error.message).toContain('Correct the field value or policy to use the operator’s declared operand kinds.');expect(error.message).toContain(row.operator);expect(error.message).toContain('parameters.probe');if(row.reference)expect(error.message).toContain('parameters.other');}
});

const trees=['all_of','any_of','none_of'].flatMap(logical=>[false,true].flatMap(reverse=>[false,true].flatMap(nested=>[false,true].map(settled=>({logical,reverse,nested,settled})))));
it.each(trees)('tree settlement: $logical $reverse $nested $settled',row=>{
  const {policy,envelope}=operandInputs({operator:'greater_than',left:'private-operand-value',right:1,reference:false});
  let bad=policy.rules[0].conditions;
  if(row.nested)bad={any_of:[bad,{field:'action',operator:'equals',value:'never-this-action'}]};
  const settle=row.logical!=='all_of';const truth=row.settled?settle:!settle;
  const good={field:'action',operator:'equals',value:truth?envelope.action:'never-this-action'};
  const children=[bad,good];if(row.reverse)children.reverse();policy.rules[0].conditions={[row.logical]:children};
  const {actual,error}=evaluateAnswer(new PolicyEvaluator(),envelope,policy);
  expect(actual).toEqual(row.settled?{stage:'decision',matched:row.logical==='any_of'}:{stage:'operand'});
  if(error){expect(error.message).toContain('greater_than');expect(error.message).toContain('parameters.probe');expect(error.message).not.toContain('private-operand-value');}
});
