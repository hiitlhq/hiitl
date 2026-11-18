/** HTL-45: an isolated interpreter owns every first call; test order cannot prepay it.
 * See tests/conformance/sdk_startup/TEST_DESIGN.md for scope and the HTTP fixture qualification. */
import {it, expect, beforeAll, afterAll} from 'vitest';
import {readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {latencySampleCount, latencyStatistic, recordLatencies, type LatencyTarget} from '../../../../test-support/latency.js';
import {declaredNumber} from '../../../../test-support/declarations.js';
// @ts-expect-error test-only JavaScript builder has no declaration file
import {buildCurrent} from '../../../../../tests/conformance/sdk_startup/build_current.mjs';

const root = resolve(__dirname, '../../../../..');
const fixture = join(root, 'tests/conformance/sdk_startup');
const read = (name: string) => JSON.parse(readFileSync(join(fixture, name), 'utf8'));
const cases = read('cases.json');
const targets = readFileSync(join(root, 'docs/specs/decision_response.md'), 'utf8');
let built: string;
beforeAll(() => { built = mkdtempSync(join(tmpdir(), 'hiitl-startup-build-')); buildCurrent(root, built); }, 60000);
afterAll(() => { if (built) rmSync(built, {recursive: true, force: true}); });
function budget(mode: string): number {
  const patterns: Record<string, RegExp> = {
    local: /^- \*\*Pure local mode\*\*: Single-digit milliseconds \(< ([\d.]+)ms\)$/m,
    hosted: /^- \*\*Pure hosted mode\*\*: Low tens of milliseconds \(< ([\d.]+)ms, region-dependent\)$/m,
    hybrid: /^- \*\*Pure local mode\*\*: Single-digit milliseconds \(< ([\d.]+)ms\)$/m,
  };
  return declaredNumber(targets, patterns[mode], `decision_response.md ${mode} target`);
}

for (const testCase of cases) for (const observation of ['timing','producers']) {
  const c = testCase, name = Object.values(testCase).join('/');
  it(`${observation}: ${name}: every fresh process call meets its declared target`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'hiitl-fresh-process-'));
    const rows: any[] = [];
    try {
      for (let sample = 0; sample < (observation === 'timing' ? latencySampleCount() : 1); sample++) {
        const current = join(directory, String(sample)); mkdirSync(current);
        const policy = read('policy.json'), payload = read('policy-response.json');
        for (const suffix of ['json', 'yaml']) writeFileSync(join(current, `policy.${suffix}`), JSON.stringify(policy));
        writeFileSync(join(current, 'payload.json'), JSON.stringify(payload));
        writeFileSync(join(current, 'case.json'), JSON.stringify(testCase));
        if (c.source === 'disk') {
          const cache = join(current, 'cache', policy.scope.org_id, policy.scope.environment);
          mkdirSync(cache, {recursive: true}); const data = JSON.stringify(payload);
          writeFileSync(join(cache, 'policies.json'), data);
          writeFileSync(join(cache, 'policies.json.sha256'), createHash('sha256').update(data).digest('hex'));
          writeFileSync(join(cache, 'policies.etag'), payload.etag);
        }
        const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
          ['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT'].includes(key)));
        const child = spawnSync(process.execPath, [join(fixture, 'typescript_child.mjs'), built, current, ...(observation === 'producers' ? ['--producers'] : [])],
          {cwd: current, env, encoding: 'utf8'});
        const tagged = child.stdout.split('\n').filter(line => line.startsWith('HTL45_SAMPLE '));
        expect([child.status, tagged.length], child.stderr).toEqual([0, 1]);
        const row = JSON.parse(tagged[0].slice('HTL45_SAMPLE '.length));
        expect(row.error, JSON.stringify(row)).toBeUndefined();
        expect(row.resolved_mode).toBe(c.mode);
        expect(row.clock_loads, 'the clock prepays what the first call pays').toEqual([]); rows.push(row);
      }
      console.log('HTL45_MEASUREMENTS', JSON.stringify({case: testCase, samples: rows}));
      for (const row of rows) for (const call of ['first', 'repeated']) {
        if (row.startup_wait_location === 'first evaluate') expect(row.startup_completed).toBe(true);
        const decision = row[call + '_decision'];
        expect(decision.decision).toBe(c.mode === 'hosted' || c.evaluation === 'RESPECT_POLICY' ? 'BLOCK' : 'OBSERVE');
        if (c.source !== 'none') expect(decision.policy_version, JSON.stringify(row)).toBe('v1.0.0');
        if (['json', 'yaml'].includes(c.source)) {
          expect(row.construction_policy_reads, JSON.stringify(row)).toBeGreaterThan(0);
        }
      }
      if (observation === 'producers') {
        expect(rows.flatMap(row => row.producer_events).filter(e => !['imports','construction'].includes(e.phase))).toEqual([]);
        expect(rows.some(row => row.producer_events.length > 0)).toBe(true);
        return;
      }
      const populations: [string, number[], LatencyTarget][] = [];
      for (const call of ['first','repeated']) {
        populations.push([`fresh/${name}/${call}/call`, rows.map(row => row[call+'_ms']), c.mode === 'hosted' ? 'hosted' : 'local']);
        if (c.mode === 'hybrid') populations.push([`fresh/${name}/${call}/evaluation`,
          rows.map(row => row[call+'_decision'].timing.evaluation_ms), 'core']);
      }
      recordLatencies(populations);
    } finally { rmSync(directory, {recursive: true, force: true}); }
  }, 0); // No host-speed deadline on a generated timing population; the CI job owns its execution timeout.
}

it('file reading follows its source and records refusals', () => {
  const child = spawnSync(process.execPath, [join(fixture, 'file_probe.mjs'), built], {encoding: 'utf8'});
  expect(child.status, child.stderr).toBe(0);
  const rows = JSON.parse(child.stdout.split('\n').find(line => line.startsWith('HTL45_FILES '))!.slice('HTL45_FILES '.length));
  console.log('HTL45_FILE_OBSERVATIONS', JSON.stringify(rows));
  const failures = rows.filter((row: any) => {
    if (row.fault === 'unreadable' && row.readable) return row.decision !== 'ALLOW' || row.version !== 'v1.0.0' || JSON.stringify(row.record_decisions) !== JSON.stringify(['ALLOW']);
    if (row.when === 'construction') return row.error !== 'PolicyLoadError';
    const expected = /^(valid|replacement)/.test(row.fault) ? 'BLOCK' : 'POLICY_ERROR';
    return row.decision !== expected || JSON.stringify(row.record_decisions) !== JSON.stringify([expected]) ||
      (expected === 'BLOCK' && row.version !== 'v2.0.0');
  });
  expect(failures).toEqual([]);
});

it('latency reads p95, not one sample or every sample', () => {
  const n = latencySampleCount(); expect(n).toBe(20);
  const samples = [...Array(n-1).fill(0),10];
  expect(latencyStatistic(samples)).toBeCloseTo(0.5);
  expect(latencyStatistic(samples.reverse())).toBeCloseTo(0.5);
  expect(latencyStatistic(Array(n).fill(10))).toBe(10);
});

it('real filesystem tick rewrites give the new policy answer', () => {
  const child=spawnSync(process.execPath,[join(fixture,'same_tick_probe.mjs'),built,fixture,String(latencySampleCount())],{encoding:'utf8'});
  expect(child.status,child.stdout+child.stderr).toBe(0);
  const rows=JSON.parse(child.stdout.split('\n').find(line=>line.startsWith('HTL45_TICKS '))!.slice('HTL45_TICKS '.length));
  console.log('HTL45_REAL_TIMESTAMPS',JSON.stringify(rows));
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.filter((row:any)=>row.decision!=='BLOCK'||row.version!=='v2.0.0')).toEqual([]);
});
