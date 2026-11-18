import { readFileSync } from 'node:fs';
export interface InputCase {format:'envelope'|'policy'|'routes';id:string;declaration:string;path:(string|number)[];control:any;input:any;expected_accept:boolean;kind:string;subtype?:string}
export const inputCases=(JSON.parse(readFileSync(new URL('../../tests/conformance/input_contract/cases.json',import.meta.url),'utf8')) as {cases:InputCase[]}).cases;

/** Union errors are nested; unknown-key issues locate their containing object and name the child separately. */
export function issuePaths(issues:any[],prefix:(string|number)[]=[]):(string|number)[][] {
  return issues.flatMap(issue=>{
    const path=[...prefix,...issue.path];
    if(issue.code==='invalid_union')return issue.errors.flatMap((branch:any[])=>issuePaths(branch,path));
    if(issue.code==='unrecognized_keys')return issue.keys.map((key:string)=>[...path,key]);
    return [path];
  });
}
