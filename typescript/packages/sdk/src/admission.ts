/** Numeric refusals retain the SDK entry's existing recoverable failure. */
import {z} from 'zod';
import {assertSchemaNumbers,NumericDomainError} from '@hiitl/core';
import {SyncError,ConfigurationError} from './exceptions.js';
import {syncNumberSchema} from './sync-numbers.js';

export function admitSync(channel:string,value:unknown,path:(string|number)[]=[],schema:z.ZodType=syncNumberSchema(channel)):void {
  try { assertSchemaNumbers(value,schema,path); }
  catch(error) {
    if(!(error instanceof NumericDomainError))throw error;
    throw new SyncError(channel,`Numeric input refused: ${error.message}`,error);
  }
}
export function syncChannel(path:string):string {
  const name=path.split('/').at(-1)!.replace(/\.json$/,'');
  return ({policies:'policy','kill-switches':'kill_switches'} as Record<string,string>)[name]??name;
}

export function admitConfiguration(value:unknown,schema:z.ZodType):void {
  try {assertSchemaNumbers(value,schema);} catch(error) {
    if(!(error instanceof NumericDomainError))throw error;
    throw new ConfigurationError(error.message);
  }
}
