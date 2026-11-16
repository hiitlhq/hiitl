/** Diagnostic declarations from the content's owner, never a second reader. */
import {z} from 'zod';
import {PolicySetSchema,RouteSchema} from '@hiitl/core';
import {shapes} from './numeric-declarations.js';
const policy=z.object({policies:z.array(z.object({content:PolicySetSchema}))});
const tick=z.object({policy_set:PolicySetSchema});
const routes=z.array(z.object({config:RouteSchema}));
const routesReply=z.object({routes});
const acknowledgement=z.unknown().meta(shapes.audit_ack);
export function syncNumberSchema(channel:string,cache=false):z.ZodType {
  if(channel==='policy')return policy;
  if(channel==='kill_switches')return tick;
  if(channel==='routes')return cache?routes:routesReply;
  return acknowledgement;
}
export const TelemetryUploadNumberSchema=z.unknown().meta({
 ...Object.fromEntries(Object.entries(shapes.telemetry).filter(([key])=>['$defs','definitions'].includes(key))),
 type:'object',properties:{records:{type:'array',items:shapes.telemetry}},
});
