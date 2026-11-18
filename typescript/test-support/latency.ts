/** Timing Metadata owns the statistic; telemetry_schema owns interpolation. */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { declaredNumber } from './declarations.js';
const source = readFileSync(fileURLToPath(new URL('../../docs/specs/decision_response.md', import.meta.url)), 'utf8');
export const latencyPercentile = declaredNumber(source,
  /^If the p(\d+) of evaluation or round-trip latency is at or over/m, 'latency statistic') / 100;
export function latencySampleCount(): number {
  let n = 1;
  while (Math.ceil(latencyPercentile * n) === n) n++;
  return n;
}
export function latencyStatistic(samples: number[]): number {
  if (samples.length < latencySampleCount()) throw new Error('Insufficient samples for the declared latency statistic');
  const ordered = [...samples].sort((a,b) => a-b);
  const position = (ordered.length-1) * latencyPercentile, lower = Math.floor(position), upper = Math.ceil(position);
  return ordered[lower] + (position-lower) * (ordered[upper]-ordered[lower]);
}

export type LatencyTarget = 'core' | 'local' | 'hosted';
export function latencyTarget(target: LatencyTarget): number {
  const patterns = {
    core: /^- \*\*Typical core evaluation\*\*: < ([\d.]+)ms for typical policies\.$/m,
    local: /^- \*\*Pure local mode\*\*: Single-digit milliseconds \(< ([\d.]+)ms\)$/m,
    hosted: /^- \*\*Pure hosted mode\*\*: Low tens of milliseconds \(< ([\d.]+)ms, region-dependent\)$/m,
  };
  if (!patterns[target]) throw new Error(`Undeclared latency target: ${target}`);
  return declaredNumber(source, patterns[target], `latency ${target}`);
}

/** HTL-17 19d576ee: an in-process cell runs the warmup and count it had before HTL-45, as its catalogue entry
 * declares; any other population (a fresh process's) is the sample count above, with no warmup. */
export type LatencyRun = {warmup: number, count: number};
const timingCells = JSON.parse(readFileSync(fileURLToPath(
  new URL('../../tests/conformance/sdk_startup/timing_cells.json', import.meta.url)), 'utf8')).node;
export function latencyRun(caseId: string, cells: {case: string, warmup?: unknown, count?: unknown}[] = timingCells): LatencyRun {
  const declared = cells.filter(cell => cell.case === caseId);
  if (declared.length > 1) throw new Error(`${caseId} is catalogued more than once`);
  if (!declared.length) return {warmup: 0, count: latencySampleCount()};
  const {warmup, count} = declared[0];
  if (!(Number.isInteger(warmup) && Number.isInteger(count) && (warmup as number) >= 0 && (count as number) >= latencySampleCount()))
    throw new Error(`${caseId} declares no in-process run in the timing catalogue`);
  return {warmup: warmup as number, count: count as number};
}
/** Each call timed on its own, in order. */
export function timeCalls(calls: number, call: () => unknown): number[] {
  return Array.from({length: calls}, () => { const start = performance.now(); call(); return performance.now() - start; });
}

import {mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
export function recordLatency(caseId: string, samples: number[], target: LatencyTarget, warmup: number[] = []) {
  if (!samples.every(x => typeof x === 'number' && Number.isFinite(x) && x >= 0))
    throw new Error('Expected finite nonnegative latency samples');
  if (!warmup.every(x => typeof x === 'number' && Number.isFinite(x) && x >= 0))
    throw new Error('Expected finite nonnegative warmup times');
  const run = latencyRun(caseId);
  if (warmup.length !== run.warmup || samples.length !== run.count)
    throw new Error(`${caseId}: recorded ${warmup.length} warmup and ${samples.length} calls; its declared run is ${run.warmup} and ${run.count}`);
  const measured = latencyStatistic(samples), bound = latencyTarget(target);
  const asserted = process.env.HIITL_RELEASE_LATENCY === '1';
  const directory = process.env.HIITL_LATENCY_RECORD_DIR;
  if (asserted && !directory) throw new Error('Release timing requires a record directory');
  const row = {case: caseId, target, warmup_ms: warmup, samples_ms: samples, p95_ms: measured, asserted,
    language: 'node', runtime: process.versions.node, stage: process.env.HIITL_LATENCY_STAGE ?? 'suite',
    export_commit: process.env.HIITL_LATENCY_EXPORT_COMMIT ?? null,
    machine: JSON.parse(process.env.HIITL_LATENCY_MACHINE ?? '{}')};
  if (directory) {
    mkdirSync(directory, {recursive: true});
    const key = JSON.stringify([row.language,row.runtime,row.stage,caseId]);
    writeFileSync(join(directory,createHash('sha256').update(key).digest('hex')+'.latency.json'), JSON.stringify(row)+'\n');
  }
  console.log('hiitl.latency '+JSON.stringify(row));
  if (asserted && !(measured < bound)) throw new Error(`${caseId}: p95 ${measured} ms is at/over target ${bound} ms`);
  return row;
}

export function recordLatencies(populations: [string, number[], LatencyTarget, number[]?][]): void {
  const failures: string[] = [];
  for (const [caseId, samples, target, warmup] of populations) {
    try { recordLatency(caseId, samples, target, warmup); }
    catch (error) { failures.push(String(error)); }
  }
  if (failures.length) throw new Error(failures.join('\n'));
}
