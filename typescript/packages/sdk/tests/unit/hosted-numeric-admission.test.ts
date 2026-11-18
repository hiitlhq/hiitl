/** Gap291: actual public entry refuses before an envelope, decision, audit or send. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {afterEach,expect,it,vi} from 'vitest';
import type {Decision,Envelope} from '@hiitl/core';
import {HIITL} from '../../src/client.js';
import {HostedClient} from '../../src/http-client.js';
import {AuditLogger} from '../../src/audit.js';
import {EnvelopeValidationError} from '../../src/exceptions.js';

type NumericCase={id:string;kind:string;input:string;expected_accept:boolean};
const corpus=JSON.parse(readFileSync(resolve(__dirname,'../../../../../tests/conformance/numeric_domain/cases.json'),'utf8')) as {cases:NumericCase[]};
const fixtures=corpus.cases.flatMap(row=>['parameters','unread'].map(surface=>({row,surface,id:`${surface}/${row.id}`})));
const held=(row:NumericCase):unknown=>row.kind==='native'?Number(row.input):JSON.parse(row.input);
afterEach(()=>vi.restoreAllMocks());

it.each(fixtures)('$id follows the declared public-entry admission',async({row,surface})=>{
  const client=new HIITL({evaluation:'remote',environment:'dev',org_id:'org_1234567890abcdef',agent_id:'numeric-entry',
    api_key:'local-contract-fixture-key',signature_key:'local-contract-fixture-signing-key',server_url:'https://fixture.invalid'});
  const builder=vi.spyOn(client as any,'_buildEnvelope'); // real constructor and builder, no replacement
  let produced:Decision|undefined;
  const downstream=vi.spyOn(HostedClient.prototype,'_evaluateAdmitted').mockImplementation(async(envelope:Envelope)=>{
    produced={action_id:envelope.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',
      timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};
    return produced;
  });
  const write=vi.spyOn(AuditLogger.prototype,'write');
  const writeResult=vi.spyOn(AuditLogger.prototype,'writeResult');
  const fetch=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>{throw new Error('No network in SDK-entry cell');});
  const value=held(row);
  const options={action:'read',parameters:{control:'kept'},[surface]:{probe:value}} as any;
  try{
    if(row.expected_accept){
      const result=await client.evaluate(options);
      expect(builder).toHaveBeenCalledTimes(1);
      expect(downstream).toHaveBeenCalledTimes(1);
      const envelope=downstream.mock.calls[0][0];
      expect(result).toBe(produced);
      expect(result.action_id).toBe(envelope.action_id);
      expect(result.decision).toBe('ALLOW');
      expect(result.allowed).toBe(true);
      expect(envelope.parameters).toEqual(surface==='parameters'?{probe:value}:{control:'kept'});
    }else{
      let refusal:unknown;
      try{await client.evaluate(options);}catch(error){refusal=error;}
      expect(refusal).toBeInstanceOf(EnvelopeValidationError);
      const detail=(refusal as EnvelopeValidationError).validation_errors;
      expect(detail).toEqual([expect.stringContaining(`${surface}.probe`)]);
      expect(detail[0]).toMatch(surface==='parameters'?/text/i:/not declared/i);
      expect(builder).not.toHaveBeenCalled();
      expect(downstream).not.toHaveBeenCalled();
      expect(produced).toBeUndefined();
    }
    expect(write).not.toHaveBeenCalled();
    expect(writeResult).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  }finally{client.close();}
});
