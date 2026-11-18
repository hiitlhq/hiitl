/** Expected answers come from canonical declarations, independent of these runtime readers. */
import { expect,it } from 'vitest';
import { EnvelopeSchema,PolicySetSchema } from '../../src/types.js';
import { RouteSchema } from '../../src/route-types.js';
import { inputCases,issuePaths } from '../../../../test-support/input-contract.js';

it.each(inputCases)('core reads the source-declared answer: $id',row=>{
  const schema={envelope:EnvelopeSchema,policy:PolicySetSchema,routes:RouteSchema}[row.format];
  const control=schema.safeParse(row.control);
  expect(control.success,`${row.id} valid control: ${control.success?'':control.error.message}`).toBe(true);
  const result=schema.safeParse(row.input);
  expect(result.success,`${row.id} ${row.declaration}`).toBe(row.expected_accept);
  if(!result.success)expect(issuePaths(result.error.issues),row.id).toContainEqual(row.path);
});
