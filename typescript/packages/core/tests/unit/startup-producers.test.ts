/** A directly constructed core cannot borrow an SDK's parser preparation. */
import {it,expect} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
// @ts-expect-error test-only source builder has no declaration file
import {buildCurrent} from '../../../../../tests/conformance/sdk_startup/build_current.mjs';

it('a fresh core evaluator builds no parser on its call path',()=>{
  const root=resolve(__dirname,'../../../../..'),fixture=join(root,'tests/conformance/sdk_startup');
  const built=mkdtempSync(join(tmpdir(),'htl45-core-startup-'));
  try {
    buildCurrent(root,built,['core']);
    const child=spawnSync(process.execPath,[join(fixture,'core_producer.mjs'),built,fixture],{encoding:'utf8'});
    expect(child.status,child.stdout+child.stderr).toBe(0);
    const rows=child.stdout.split('\n').filter(s=>s.startsWith('HTL45_CORE_PRODUCERS '));expect(rows).toHaveLength(1);
    const row=JSON.parse(rows[0].slice('HTL45_CORE_PRODUCERS '.length));
    console.log('HTL45_CORE_PRODUCERS',JSON.stringify(row));
    expect(row.events.filter((e:any)=>!['imports','construction'].includes(e.phase))).toEqual([]);
    expect(row.events.some((e:any)=>e.phase==='construction')).toBe(true);
    expect([row.first,row.repeated]).toEqual(['BLOCK','BLOCK']);
  } finally {rmSync(built,{recursive:true,force:true});}
});
