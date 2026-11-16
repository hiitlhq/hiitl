import {readFileSync} from 'node:fs';
export interface ComparisonCase {id:string;operator:any;left:unknown;right:unknown;expected:{decision:string;allowed:boolean;reason_codes:string[]}}
export const comparisonData=JSON.parse(readFileSync(new URL('../../tests/conformance/json_comparison/cases.json',import.meta.url),'utf8')) as {operators:string[];cases:ComparisonCase[];base:{policy:any;envelope:any}};
export function comparisonInputs(row:Pick<ComparisonCase,'operator'|'left'|'right'>) {
  const {policy,envelope}=structuredClone(comparisonData.base);
  policy.rules[0].conditions.operator=row.operator;policy.rules[0].conditions.value=structuredClone(row.right);
  envelope.parameters.probe=structuredClone(row.left);
  return {policy,envelope};
}
export const comparisonOutcome=(d:{decision:string;allowed:boolean;reason_codes:string[]})=>({decision:d.decision,allowed:d.allowed,reason_codes:d.reason_codes});

export const modelObjects=[
  {field:'cost_estimate',left:{tokens:1},right:{tokens:1},same:true},
  {field:'cost_estimate',left:{tokens:1},right:{tokens:2},same:false},
  {field:'cost_estimate',left:{},right:{},same:true},
  {field:'principal',left:{sub:'user',verified_by:'sdk_verifier'},right:{verified_by:'sdk_verifier',sub:'user'},same:true},
  {field:'principal',left:{sub:'user',verified_by:'sdk_verifier'},right:{sub:'other',verified_by:'sdk_verifier'},same:false},
];
