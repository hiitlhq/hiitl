import {it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import yaml from 'js-yaml';
import {PolicyLoader} from '../../src/policy-loader.js';
import {PolicyLoadError} from '../../src/exceptions.js';
import {evaluate} from '@hiitl/core';
const root=resolve(__dirname,'../../../../../');
const rows=JSON.parse(readFileSync(join(root,'tests/conformance/reserved_policy_values/cases.json'),'utf8')).cases;
for(const format of ['json','yaml'])it.each(rows)(`reserved policy ${format}: $id`,(row:any)=>{
 const dir=mkdtempSync(join(tmpdir(),'htl43-reserved-')),path=join(dir,'policy.'+format);
 const write=(data:unknown)=>writeFileSync(path,format==='json'?JSON.stringify(data):yaml.dump(data));
 try{write(row.control);expect(new PolicyLoader(path).load().name).toBe(row.control.name);write(row.input);
 if(row.accept)expect(new PolicyLoader(path).load().name).toBe(row.input.name);
 else{let error:any;try{new PolicyLoader(path).load();}catch(caught){error=caught;}expect(error).toBeInstanceOf(PolicyLoadError);expect(error.reason).toBe('POLICY_VALIDATION_ERROR');expect(error.message).toContain('$');}
 }finally{rmSync(dir,{recursive:true,force:true});}
});

for (const format of ['json', 'yaml']) it(`compiled provenance keeps exact source and form rules: ${format}`, () => {
  const witness = JSON.parse(readFileSync(join(root, 'tests/conformance/input_contract/policy-witnesses.json'), 'utf8'))
    .witnesses.find((row: any) => row.id === 'legacy-placeholder-bounds').input;
  const source = structuredClone(witness), entry = source.metadata.rate_limits[0];
  const dir = mkdtempSync(join(tmpdir(), 'htl43-provenance-')), path = join(dir, 'policy.' + format);
  const load = (data: unknown) => {
    writeFileSync(path, format === 'json' ? JSON.stringify(data) : yaml.dump(data));
    return new PolicyLoader(path).load();
  };
  try {
    let compiled: ReturnType<typeof load> | undefined, reloaded: ReturnType<typeof load> | undefined;
    expect(() => { compiled = load(source); reloaded = load(JSON.parse(JSON.stringify(compiled))); }).not.toThrow();
    expect(source).toEqual(witness);
    const encoded = JSON.parse(JSON.stringify(compiled));
    expect(encoded.metadata).not.toHaveProperty('rate_limits');
    const envelope = JSON.parse(readFileSync(join(root, 'tests/conformance/cases/references/test_143_field_reference_equals_compares_two_fields.json'), 'utf8')).envelope;
    Object.assign(envelope, source.scope);
    for (const policy of [compiled!, reloaded!]) {
      const rule = policy.rules.find(rule => rule.name === 'metadata.rate_limits[0]')!;
      expect(rule.metadata!.compiled_from).toEqual({path: rule.name, entry});
      expect(rule.rate_limit!.limit).toEqual(entry.limit);
      expect(rule.rate_limit!.window_seconds).toEqual(entry.window_seconds);
      const decision = evaluate(envelope, {...policy, rules: [rule]});
      expect(decision.matched_rules ?? []).toEqual([]);
      expect(decision.rate_limit_rules ?? []).toEqual([]);
    }
    const calibrated = structuredClone(encoded);
    calibrated.rules = [calibrated.rules.at(-1)];
    Object.assign(calibrated.rules[0].rate_limit, {limit: 10, window_seconds: 60});
    expect(evaluate(envelope, load(calibrated)).rate_limit_rules!.map(rule => rule.rule_name)).toEqual(['metadata.rate_limits[0]']);

    for (const stage of ['source', 'copy']) for (const member of ['limit', 'window_seconds'])
      for (const marker of ['$field', '$declared', '$uncalibrated']) for (const sibling of [false, true]) {
        const data = structuredClone(stage === 'source' ? source : encoded);
        const held = stage === 'source' ? data.metadata.rate_limits[0] : data.rules.at(-1).metadata.compiled_from.entry;
        held[member] = {[marker]: 'the bound'};
        if (sibling) held[member].note = 'not a form';
        if (marker === '$uncalibrated' && !sibling) expect(load(data).name).toBe(witness.name);
        else {
          let error: any; try { load(data); } catch (caught) { error = caught; }
          expect(error).toBeInstanceOf(PolicyLoadError);
          expect(error.reason).toBe('POLICY_VALIDATION_ERROR');
          expect(error.message).toContain(marker);
        }
      }
    for (const misplaced of ['set-copy', 'rule-entry', 'copy-note', 'entry-note']) {
      const data = structuredClone(encoded), metadata = data.rules.at(-1).metadata;
      if (misplaced === 'set-copy') { data.metadata.compiled_from = metadata.compiled_from; delete metadata.compiled_from; }
      else if (misplaced === 'rule-entry') { metadata.entry = metadata.compiled_from.entry; delete metadata.compiled_from; }
      else if (misplaced === 'copy-note') metadata.compiled_from.note = {$uncalibrated: 'not a bound'};
      else metadata.compiled_from.entry.note = {$uncalibrated: 'not a bound'};
      let error: any; try { load(data); } catch (caught) { error = caught; }
      expect(error).toBeInstanceOf(PolicyLoadError);
      expect(error.reason).toBe('POLICY_VALIDATION_ERROR');
      expect(error.message).toContain('$uncalibrated');
    }
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
