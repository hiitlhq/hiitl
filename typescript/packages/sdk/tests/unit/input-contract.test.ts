/** Real JSON/YAML file loaders consume the same independent canonical answers. */
import { mkdtempSync,writeFileSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { dump } from 'js-yaml';
import { expect,it,vi } from 'vitest';
import { PolicyLoader } from '../../src/policy-loader.js';
import { RouteLoader } from '../../src/route-loader.js';
import { PolicyLoadError,RouteLoadError } from '../../src/exceptions.js';
import { inputCases,issuePaths } from '../../../../test-support/input-contract.js';

const rows=inputCases.filter(row=>row.format!=='envelope').flatMap(row=>(['json','yaml'] as const).map(wire=>({...row,wire})));
it.each(rows)('file loader reads the source-declared answer: $wire $id',row=>{
  const directory=mkdtempSync(join(tmpdir(),'hiitl-input-contract-'));
  vi.stubEnv('HTL41_ROUTE_FIXTURE','local-route-fixture');
  try {
    const name=row.format==='routes'?row.control.name:'policy';
    const file=join(directory,`${name}.${row.wire}`);
    const load=(value:unknown)=>{
      writeFileSync(file,row.wire==='json'?JSON.stringify(value):dump(value));
      return row.format==='routes'?new RouteLoader(directory).get(name):new PolicyLoader(file).load();
    };
    let controlError:unknown;try{load(row.control);}catch(error){controlError=error;}
    expect(controlError,`${row.id} valid control`).toBeUndefined();
    let error:unknown;let accepted=false;
    try{load(row.input);accepted=true;}catch(caught){error=caught;}
    expect(accepted,`${row.id} ${row.declaration}`).toBe(row.expected_accept);
    if(accepted)return;
    expect(error).toBeInstanceOf(row.format==='routes'?RouteLoadError:PolicyLoadError);
    const message=(error as Error).message;
    if(row.format==='policy' && row.wire==='yaml' && row.path.length===0)expect(message).toMatch(/root/i);
    else if(row.format==='policy') {
      const raw=message.match(/\n\n(\[[\s\S]*\])\n\nThe policy/);
      expect(raw,`${row.id}: ${message}`).not.toBeNull();
      if(raw)expect(issuePaths(JSON.parse(raw[1])),row.id).toContainEqual(row.path);
    } else if(row.path.length===0)expect(message).toMatch(/root/i);
    else if(row.kind==='unknown_field') {
      expect(message).toContain(row.path.slice(0,-1).join('.'));
      expect(message).toContain(String(row.path.at(-1)));
    } else expect(message).toContain(row.path.join('.'));
  } finally {vi.unstubAllEnvs();rmSync(directory,{recursive:true,force:true});}
});
