import {readFileSync} from 'node:fs';
import {comparisonInputs} from './json-comparison.js';
export const operandData=JSON.parse(readFileSync(new URL('../../tests/conformance/operator_kinds/cases.json',import.meta.url),'utf8'));
export function operandInputs(row:any){
  const result=comparisonInputs(row);
  if(row.reference){result.policy.rules[0].conditions.value={$field:'parameters.other'};result.envelope.parameters.other=row.right;}
  return result;
}
export function evaluateAnswer(evaluator:any,envelope:any,policy:any):{actual:any,error?:Error}{
  try{return {actual:{stage:'decision',matched:evaluator.evaluate(envelope,policy).allowed}};}
  catch(error){return {actual:{stage:(error as Error).name==='OperatorKindError'?'operand':(error as Error).name},error:error as Error};}
}

/** Snapshot each own JSON object's prototype by its data path, including arrays and schema maps. */
export function prototypeSnapshot(value:unknown,path:(string|number)[]=[]):Array<{path:(string|number)[],prototype:object|null,array:boolean}> {
  if(value===null || typeof value!=='object')return [];
  const own={path,prototype:Object.getPrototypeOf(value),array:Array.isArray(value)};
  return [own,...Object.entries(value).flatMap(([key,child])=>prototypeSnapshot(child,[...path,Array.isArray(value)?Number(key):key]))];
}
