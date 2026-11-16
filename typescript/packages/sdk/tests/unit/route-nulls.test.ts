/** HTL-41: exercise the actual file loader, including its root-object boundary. */
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it, vi } from 'vitest';
import { dump } from 'js-yaml';
import { RouteLoader, RouteLoadError } from '../../src/route-loader.js';

const corpus=JSON.parse(readFileSync(new URL('../../../../../tests/conformance/typed_members/route-null-cases.json',import.meta.url),'utf8')) as ReturnType<typeof import('../../../../../tests/conformance/typed_members/generate.mjs').routeCorpus>;
function load(value:unknown,name:string,format:'json'|'yaml') {
  const directory=mkdtempSync(join(tmpdir(),'hiitl-route-null-'));
  vi.stubEnv('HTL41_ROUTE_FIXTURE','local-route-fixture');
  try {
    writeFileSync(join(directory,`${name}.${format}`),format==='json' ? JSON.stringify(value) : dump(value));
    return new RouteLoader(directory).get(name);
  } finally {
    vi.unstubAllEnvs();
    rmSync(directory,{recursive:true,force:true});
  }
}

it.each(corpus.cases.flatMap(row=>(['json','yaml'] as const).map(format=>({...row,format}))))('the file loader enforces the null answer: $format $id', row=>{
  expect(load(row.control,row.control.name,row.format)).toStrictEqual(row.control);
  if(row.expected_accept) {
    expect(load(row.input,row.control.name,row.format)).toStrictEqual(row.input);
  } else {
    expect(()=>load(row.input,row.control.name,row.format)).toThrow(RouteLoadError);
    expect(()=>load(row.input,row.control.name,row.format)).toThrow(row.path.length ? row.path.join('.') : /route.*root/i);
  }
});

it.each(corpus.untyped_controls.flatMap(row=>(['json','yaml'] as const).map(format=>({...row,format}))))('the file loader preserves untyped nulls: $format $id', row=>{
  expect(load(row.input,row.input.name,row.format)).toStrictEqual(row.input);
});
