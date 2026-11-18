/** HTL-45 8613a7bc item 3: a shipped template's allowlist admits its hosts and no lookalike of them.
 * Design: tests/conformance/shipped_templates/TEST_DESIGN.md. The template is read as a customer copies it: its
 * starter policies in the table's policy set, loaded by the SDK and evaluated under RESPECT_POLICY. */
import {it,expect,afterEach} from 'vitest';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';
import {PolicyEvaluator} from '@hiitl/core';
import {PolicyLoader,loadYaml} from '../../src/policy-loader.js';
const root=resolve(__dirname,'../../../../..');
const table=JSON.parse(readFileSync(join(root,'tests/conformance/shipped_templates/cases.json'),'utf8'));
const starterPolicies=()=>(loadYaml(readFileSync(join(root,table.template),'utf8')) as any).starter_policies;
const dirs:string[]=[];afterEach(()=>{dirs.splice(0).forEach(d=>rmSync(d,{recursive:true,force:true}));});
function decided(url:string){
 const dir=mkdtempSync(join(tmpdir(),'shipped-templates-'));dirs.push(dir);const path=join(dir,'policy.json');
 writeFileSync(path,JSON.stringify({...table.policy_set,rules:starterPolicies()}));
 const envelope=structuredClone(table.envelope);envelope.parameters[table.field]=url;
 return new PolicyEvaluator().evaluate(envelope,new PolicyLoader(path).load(),'RESPECT_POLICY');
}
it.each(table.allowed)('an allowlisted destination is allowed by its rule: %s',(url:any)=>{
 const rule=starterPolicies().find((r:any)=>r.name===table.rule);const decision=decided(url);
 expect([decision.decision,decision.reason_codes]).toEqual(['ALLOW',[rule.reason_code]]);
});
it.each(table.not_allowed)('a lookalike destination is not allowed: %s',(url:any)=>{
 const decision=decided(url);expect(decision.allowed,JSON.stringify([decision.decision,decision.reason_codes])).toBe(false);
});
