/** d001d308: ordinary builds retain samples; a release must assert them. */
import {it, expect, afterEach} from 'vitest';
import {mkdtempSync, readFileSync, readdirSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';
import * as latency from '../../../../test-support/latency.js';
const original = {...process.env};
const dirs: string[] = [];
afterEach(() => {process.env = {...original}; for(const d of dirs.splice(0)) rmSync(d,{recursive:true,force:true});});
it('records an ordinary population but asserts the same p95 at release', () => {
  expect(typeof latency.recordLatency).toBe('function');
  const dir=mkdtempSync(join(tmpdir(),'latency-gate-'));dirs.push(dir);
  process.env.HIITL_LATENCY_RECORD_DIR=dir;delete process.env.HIITL_RELEASE_LATENCY;
  const samples=Array(latency.latencySampleCount()).fill(latency.latencyTarget('local'));
  let row!: ReturnType<typeof latency.recordLatency>;
  expect(()=>{row=latency.recordLatency('probe',samples,'local');}).not.toThrow();
  expect(row.samples_ms).toEqual(samples);expect(row.asserted).toBe(false);
  expect(readdirSync(dir)).toHaveLength(1);
  expect(JSON.parse(readFileSync(join(dir,readdirSync(dir)[0]),'utf8'))).toEqual(row);
  process.env.HIITL_RELEASE_LATENCY='1';
  expect(()=>latency.recordLatency('probe',samples,'local')).toThrow(/p95/);
  expect(JSON.parse(readFileSync(join(dir,readdirSync(dir)[0]),'utf8')).asserted).toBe(true);
});
it('requires a sample record at release',()=>{
  expect(typeof latency.recordLatency).toBe('function');
  process.env.HIITL_RELEASE_LATENCY='1';delete process.env.HIITL_LATENCY_RECORD_DIR;
  expect(()=>latency.recordLatency('probe',Array(latency.latencySampleCount()).fill(0),'local')).toThrow(/record directory/);
});
for(const bad of [NaN,Infinity,-1]) it(`refuses invalid measurement ${bad}`,()=>{
  expect(typeof latency.recordLatency).toBe('function');
  expect(()=>latency.recordLatency('probe',Array(latency.latencySampleCount()).fill(bad),'local')).toThrow(/finite nonnegative/);
});
it('retains every population before failing a release',()=>{
  const dir=mkdtempSync(join(tmpdir(),'latency-gate-'));dirs.push(dir);
  process.env.HIITL_LATENCY_RECORD_DIR=dir;process.env.HIITL_RELEASE_LATENCY='1';
  const n=latency.latencySampleCount(),bound=latency.latencyTarget('local');
  expect(()=>latency.recordLatencies([['first',Array(n).fill(bound),'local'],['repeated',Array(n).fill(0),'local']])).toThrow(/p95/);
  expect(readdirSync(dir)).toHaveLength(2);
});

// HTL-17 19d576ee: an in-process cell is read at the warmup and count its catalogue entry declares.
const cells: {case: string, target: latency.LatencyTarget, warmup: number, count: number}[] = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../../../../tests/conformance/sdk_startup/timing_cells.json', import.meta.url)), 'utf8')).node;
const inProcess = cells.reduce((a, c) => c.warmup > a.warmup ? c : a);
it('reads each catalogued in-process run at its declared warmup and count', () => {
  expect(typeof latency.latencyRun).toBe('function');
  // A refused read is compared as a value, so it fails the expectation rather than escaping it.
  const read = (caseId: string) => { try { return latency.latencyRun(caseId); } catch (error) { return String(error); } };
  for (const cell of cells) expect(read(cell.case)).toEqual({warmup: cell.warmup, count: cell.count});
  expect(latency.latencyRun('probe')).toEqual({warmup: 0, count: latency.latencySampleCount()});
});
it('refuses a catalogued case that declares no run', () => {
  expect(typeof latency.latencyRun).toBe('function');
  const n = latency.latencySampleCount();
  for (const cell of [{case:'x',target:'core',stages:['suite']}, {case:'x',target:'core',stages:['suite'],warmup:0,count:n-1}])
    expect(() => latency.latencyRun('x', [cell])).toThrow(/declares no in-process run/);
});
it('refuses a dropped warmup or another count', () => {
  expect(typeof latency.latencyRun).toBe('function');
  delete process.env.HIITL_RELEASE_LATENCY; delete process.env.HIITL_LATENCY_RECORD_DIR;
  const {warmup, count} = latency.latencyRun(inProcess.case), n = latency.latencySampleCount();
  expect(() => latency.recordLatency(inProcess.case, Array(count).fill(0), inProcess.target, [])).toThrow(/declared run/);
  expect(() => latency.recordLatency(inProcess.case, Array(count - 1).fill(0), inProcess.target, Array(warmup).fill(0))).toThrow(/declared run/);
  expect(() => latency.recordLatency('probe', Array(n + 1).fill(0), 'local')).toThrow(/declared run/);
  expect(() => latency.recordLatency('probe', Array(n).fill(0), 'local', [0])).toThrow(/declared run/);
  expect(latency.recordLatency(inProcess.case, Array(count).fill(0), inProcess.target, Array(warmup).fill(0)).warmup_ms).toEqual(Array(warmup).fill(0));
});
it('reads the p95 over the run, not its warmup', () => {
  expect(typeof latency.latencyRun).toBe('function');
  const dir=mkdtempSync(join(tmpdir(),'latency-gate-'));dirs.push(dir);
  process.env.HIITL_LATENCY_RECORD_DIR=dir;process.env.HIITL_RELEASE_LATENCY='1';
  const {warmup, count} = latency.latencyRun(inProcess.case), bound = latency.latencyTarget(inProcess.target);
  let row: {p95_ms?: number} = {};
  expect(() => { row = latency.recordLatency(inProcess.case, Array(count).fill(0), inProcess.target, Array(warmup).fill(bound * 2)); }).not.toThrow();
  expect(row.p95_ms).toBe(0);
  expect(() => latency.recordLatencies([[inProcess.case, Array(count).fill(0), inProcess.target, Array(warmup).fill(bound * 2)]])).not.toThrow();
  expect(() => latency.recordLatency(inProcess.case, Array(count).fill(bound), inProcess.target, Array(warmup).fill(0))).toThrow(/p95/);
});
for(const bad of [NaN,Infinity,-1]) it(`refuses invalid warmup time ${bad}`,()=>{
  expect(typeof latency.latencyRun).toBe('function');
  const {warmup, count} = latency.latencyRun(inProcess.case);
  expect(() => latency.recordLatency(inProcess.case, Array(count).fill(0), inProcess.target, Array(warmup).fill(bad))).toThrow(/finite nonnegative warmup/);
});
