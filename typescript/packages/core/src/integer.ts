import { z } from 'zod';
import { assertNumericDomain, NumericDomainError } from './numeric-domain.js';

/** Integer additionally requires the shared numeric domain (sync_engine.md#numeric-domain). */
export function integer(): z.ZodNumber {
  return z.number().check(({ value, issues }) => {
    try { assertNumericDomain(value); }
    catch (error) {
      if (!(error instanceof NumericDomainError)) throw error;
      issues.push({ code: 'custom', input: value, message: error.message });
      return;
    }
    if (!Number.isInteger(value)) issues.push({ code: 'invalid_type', expected: 'int', input: value });
  }).meta({type:'integer'});
}
