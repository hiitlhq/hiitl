/** HTL-37, ruling 7baea573: Zod4 must not narrow an existing integer setting to safe integers.
 * HTL43 d82fe0f5 supersedes the earlier unrestricted magnitude; original inputs remain below.
 * Current bound is read independently from the numeric-domain source corpus.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const domain=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_domain/cases.json'),'utf8'));
import { LocalModeConfigSchema } from '../../src/config.js';

describe('HTL-37: the integer dedup duration keeps its domain', () => {
  it.each([
    [-Number.MAX_SAFE_INTEGER - 1, true], [-1, true], [-0.5, false], [0, true],
    [0.5, false], [1, true], [Number.MAX_SAFE_INTEGER + 1, true], [Number.MAX_VALUE, true],
  ] as const)('%s is accepted: %s', (value, accepted) => {
    const parsed = LocalModeConfigSchema.safeParse({ dedup_window_seconds: value });
    const currentlyAdmitted=accepted && Math.abs(value)<domain.bound;
    expect(parsed.success).toBe(currentlyAdmitted);
    if (currentlyAdmitted) expect(parsed.data?.dedup_window_seconds).toBe(value);
  });
});

it('the integer dedup duration keeps both admitted magnitude edges',()=>{
  for(const value of [domain.bound-1,1-domain.bound]){
    const result=LocalModeConfigSchema.safeParse({dedup_window_seconds:value});
    expect(result.success).toBe(true);
    if(result.success)expect(result.data.dedup_window_seconds).toBe(value);
  }
});
