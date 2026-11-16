import {it,expect} from 'vitest';
import {PolicyEvaluator} from '../../src/evaluator.js';
import {OperatorKindError} from '../../src/operator-kinds.js';
import {dateData} from '../../../../test-support/date-text.js';
it.each(dateData.cases)('source date operator answer: $id',(row:any)=>{
  const run=()=>new PolicyEvaluator().evaluate(row.envelope,row.policy,'RESPECT_POLICY');
  if(row.expected==='error')expect(run).toThrow(OperatorKindError);else expect(run().allowed).toBe(row.expected);
});
