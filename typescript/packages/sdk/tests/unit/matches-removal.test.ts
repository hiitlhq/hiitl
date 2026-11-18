/** HTL-45 8613a7bc: a policy file naming `matches` is refused at load, naming it and the operators to use.
 * Design: tests/conformance/TEST_DESIGN.md (the `matches` refusal). The policy is conformance test_020's. */
import {it,expect,afterEach} from 'vitest';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';import yaml from 'js-yaml';
import {PolicyLoader} from '../../src/policy-loader.js';import {PolicyLoadError} from '../../src/exceptions.js';
const root=resolve(__dirname,'../../../../..');
const testCase=JSON.parse(readFileSync(join(root,'tests/conformance/cases/refusals/test_020_a_policy_naming_matches_is_refused_at_load.json'),'utf8'));
const dirs:string[]=[];afterEach(()=>{dirs.splice(0).forEach(d=>rmSync(d,{recursive:true,force:true}));});
for(const wire of ['json','yaml'])it(`a ${wire} policy file naming matches is refused at load, naming it and the operators to use`,()=>{
 const dir=mkdtempSync(join(tmpdir(),'matches-removal-'));dirs.push(dir);const path=join(dir,`policy.${wire}`);
 writeFileSync(path,wire==='json'?JSON.stringify(testCase.policy_set):yaml.dump(testCase.policy_set));
 let refusal:unknown;try{new PolicyLoader(path).load();}catch(e){refusal=e;}
 expect(refusal).toBeInstanceOf(PolicyLoadError);
 const quoted=new Set([...String((refusal as Error).message).matchAll(/'(\w+)'/g)].map(m=>m[1]));
 expect(testCase.expected_refusal.names.filter((name:string)=>!quoted.has(name)),(refusal as Error).message).toEqual([]);
});
