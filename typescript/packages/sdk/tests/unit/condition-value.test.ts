/** HTL-45 d0640d7a (gap 322): a policy file whose condition has no `value` is refused at load, at its `value` path.
 * Design: tests/conformance/TEST_DESIGN.md (gap 322). The policies are the refusal cases located at a `value` path; the
 * path each is refused at is the case's own, never typed here. */
import {it,expect,afterEach} from 'vitest';
import {mkdtempSync,writeFileSync,readFileSync,readdirSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';import yaml from 'js-yaml';
import {PolicyLoader} from '../../src/policy-loader.js';import {PolicyLoadError} from '../../src/exceptions.js';
const root=resolve(__dirname,'../../../../..');const refusals=join(root,'tests/conformance/cases/refusals');
const cases=readdirSync(refusals).filter(f=>f.endsWith('.json')).sort().map(f=>JSON.parse(readFileSync(join(refusals,f),'utf8')))
 .filter(c=>c.expected_refusal.artifact==='policy_set'&&c.expected_refusal.at.every((at:string)=>at.endsWith('.value')));
const dirs:string[]=[];afterEach(()=>{dirs.splice(0).forEach(d=>rmSync(d,{recursive:true,force:true}));});
it('the refusal cases at a value path are read',()=>{expect(cases.length).toBeGreaterThan(0);});
for(const testCase of cases)for(const wire of ['json','yaml'])it(`${testCase.test_id.slice(0,8)}: a ${wire} policy file whose condition has no value is refused at its value path`,()=>{
 const dir=mkdtempSync(join(tmpdir(),'condition-value-'));dirs.push(dir);const path=join(dir,`policy.${wire}`);
 writeFileSync(path,wire==='json'?JSON.stringify(testCase.policy_set):yaml.dump(testCase.policy_set));
 let refusal:unknown;try{new PolicyLoader(path).load();}catch(e){refusal=e;}
 expect(refusal).toBeInstanceOf(PolicyLoadError);
 // The loader writes the schema's issues between its header and its guidance (policy-loader.ts)
 const message=String((refusal as Error).message);
 const issues=JSON.parse(message.slice(message.indexOf('\n\n[')+2,message.indexOf(']\n\nThe policy file')+1));
 const located=[...new Set(issues.map((issue:{path:(string|number)[]})=>issue.path.join('.')))].sort();
 expect(located,message).toEqual([...testCase.expected_refusal.at].sort());
});
