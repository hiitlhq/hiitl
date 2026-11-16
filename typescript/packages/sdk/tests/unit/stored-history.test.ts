/** 93d/5203: actual stored rows drain unchanged; new result intents remain supplied. */
import {it,expect,vi,afterEach} from 'vitest';
import {readFileSync,readdirSync,mkdtempSync,rmSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import {gunzipSync} from 'node:zlib';
import Database from 'better-sqlite3';
import {AUDIT_FURTHER,NumericDomainError} from '@hiitl/core';
import {AuditLogger} from '../../src/audit.js';
import {SyncClient} from '../../src/sync-client.js';
import {SyncEngine} from '../../src/sync-engine.js';
import {HostedClient} from '../../src/http-client.js';
import {createHostedConfig} from '../../src/config.js';
const root=resolve(__dirname,'../../../../../');
const cases=readdirSync(join(root,'tests/conformance/audit_hash')).filter(p=>p.endsWith('.json')).sort().map(p=>JSON.parse(readFileSync(join(root,'tests/conformance/audit_hash',p),'utf8')));
const bound=JSON.parse(readFileSync(join(root,'tests/conformance/numeric_domain/cases.json'),'utf8')).bound;
const env:any={schema_version:'v2.0',org_id:'org_1234567890abcdef',environment:'dev',agent_id:'fixture',action_id:'act_01234567890123456789',idempotency_key:'history',action:'read',operation:'execute',target:{},parameters:{},timestamp:'2026-11-14T00:00:00Z',signature:'0'.repeat(64)};
const decision:any={action_id:env.action_id,decision:'ALLOW',allowed:true,reason_codes:[],policy_version:'v1.0.0',timing:{ingest_ms:0,evaluation_ms:0,total_ms:0}};
const dirs:string[]=[];
afterEach(()=>{vi.restoreAllMocks();for(const dir of dirs.splice(0))rmSync(dir,{recursive:true,force:true});});
function context(){const dir=mkdtempSync(join(tmpdir(),'hiitl-history-'));dirs.push(dir);const path=join(dir,'audit.db');const store=new AuditLogger(path);const db=new Database(path);return {path,store,db};}
function restore(store:AuditLogger,db:Database.Database,c:any,last=false){
  const event=store.write(env,decision);
  const values:any={event_id:c.event_id,timestamp:last?'2090-01-01T00:00:00Z':'2000-01-01T00:00:00Z',envelope:JSON.stringify(c.envelope),decision:JSON.stringify(c.decision),content_hash:c.expected.content_hash,
    ...Object.fromEntries(['org_id','environment','action_id','action','agent_id'].map(k=>[k,c.envelope[k]??null])),decision_type:c.decision.decision,policy_version:c.decision.policy_version,
    ...Object.fromEntries(AUDIT_FURTHER.map(k=>[k,k in c?JSON.stringify(c[k]):null]))};
  db.prepare('UPDATE audit_log SET '+Object.keys(values).map(k=>k+'=?').join(',')+' WHERE event_id=?').run(...Object.values(values),event);
}
const snapshot=(db:Database.Database):any[]=>db.prepare('SELECT * FROM audit_log ORDER BY event_id').all();
const hosted=(path:string):any=>new HostedClient(createHostedConfig({org_id:env.org_id,environment:'dev',agent_id:'fixture',api_key:'local-contract-fixture-key',server_url:'https://fixture.invalid',audit_db_path:path}));
const rows=['background','hosted'].flatMap(channel=>[false,true].flatMap(last=>[null,...cases].map(c=>({channel,last,c,id:`${channel}/${last}/${c?.event_id??'valid-only'}`}))));
it.each(rows)('$id stored records and followers drain as written',async({channel,last,c})=>{
  const {path,store,db}=context();let client:any;
  try{
    if(c)restore(store,db,c,last);store.write(env,decision);
    const before=snapshot(db),expected=store.getUnsynced(),sent:any[]=[];
    if(c){
      const old:any=expected.find(r=>r.event_id===c.event_id);
      for(const member of ['envelope','decision',...AUDIT_FURTHER]){expect(member in old).toBe(member in c);if(member in c)expect(old[member]).toEqual(JSON.parse(JSON.stringify(c[member])));}
      expect(old.content_hash).toBe(c.expected.content_hash);expect(store.verifyIntegrity(c.event_id)).toBe(true);
      expect(expected[last?expected.length-1:0].event_id).toBe(c.event_id);
    }
    const fetchImpl=vi.fn(async(url:any,init:any)=>{
      expect(new URL(String(url)).pathname).toBe('/v1/sync/audit');
      let raw=Buffer.from(init.body);if(new Headers(init.headers).get('Content-Encoding')==='gzip')raw=gunzipSync(raw);
      const payload=JSON.parse(raw.toString());sent.push(payload);
      return new Response(JSON.stringify({accepted:payload.records.length,duplicates:0,errors:[]}),{status:200});
    });
    let drain:()=>Promise<unknown>;
    if(channel==='background'){
      client=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:env.org_id,environment:'dev',fetchImpl});
      const engine:any=Object.create(SyncEngine.prototype);Object.assign(engine,{auditLogger:store,client,config:{audit_batch_size:100},auditSequence:0,stopController:new AbortController(),log:{debug(){},warn(){},error(){},info(){}}});drain=()=>engine._syncAudit();
    }else{vi.stubGlobal('fetch',fetchImpl);client=hosted(path);client.store=store;drain=()=>client._pushFirst();}
    let error:unknown;try{await drain();}catch(e){error=e;}
    expect(error).toBeUndefined();
    expect(sent).toHaveLength(1);expect(sent[0].records).toEqual(expected);expect(store.getUnsynced()).toEqual([]);
    await drain();expect(sent).toHaveLength(1);
    expect(snapshot(db)).toEqual(before.map(row=>({...row,synced:1})));
    for(const row of before)expect(store.verifyIntegrity(row.event_id)).toBe(true);
    for(const record of store.queryByOrgId(env.org_id)){const original=before.find(r=>r.event_id===record.event_id);expect(record.content_hash).toBe(original.content_hash);expect(record.envelope).toBe(original.envelope);}
  }finally{db.close();if(channel==='hosted')client?.close();else store.close();vi.unstubAllGlobals();}
});
it.each(['execution_result','review'])('new %s admits new terms while copying history',member=>{
  const {store,db}=context();const c=cases[cases.length-1];
  try{
    restore(store,db,c);const old:any=store.lifecycle(c.envelope.org_id,c.envelope.environment,c.envelope.action_id)[0];const before=snapshot(db);
    const result={status:'succeeded',duration_ms:1};let record:any;
    expect(()=>{record=store.writeResult(old,result);}).not.toThrow();
    expect(record.envelope).toEqual(old.envelope);expect(record.decision).toEqual(old.decision);expect(record.execution_result).toEqual(result);
    for(const field of AUDIT_FURTHER)if(field!=='execution_result'&&field in old)expect(record[field]).toEqual(old[field]);
    expect(snapshot(db).find(r=>r.event_id===c.event_id)).toEqual(before[0]);expect(store.verifyIntegrity(record.event_id)).toBe(true);
    let error:any;try{store.writeResult(old,member==='execution_result'?{status:'succeeded',probe:bound}:result,member==='review'?{probe:bound} as any:null);}catch(e){error=e;}
    expect(error).toBeInstanceOf(AuditLogError);expect(error.message).toContain('<root>['+JSON.stringify(member)+']["probe"]');expect(snapshot(db)).toHaveLength(2);
  }finally{db.close();store.close();}
});
it('hosted returns an existing record without readmission',async()=>{
  const c=cases[1];const {expected:fixed,description,...old}=c;const expected=JSON.parse(JSON.stringify({...old,content_hash:fixed.content_hash}));const dir=mkdtempSync(join(tmpdir(),'hiitl-history-response-'));dirs.push(dir);
  const sent:any[]=[];vi.stubGlobal('fetch',vi.fn(async(_url:any,init:any)=>{sent.push(JSON.parse(init.body));return new Response(JSON.stringify(expected),{status:200});}));
  const client=hosted(join(dir,'absent.db'));
  try{const result={status:'succeeded',duration_ms:1};let actual:unknown,error:unknown;try{actual=await client.recordResult(env.action_id,result);}catch(e){error=e;}expect(error).toBeUndefined();expect(actual).toEqual(expected);expect(sent).toEqual([result]);
    await expect(client.recordResult(env.action_id,{probe:bound})).rejects.toThrow(LifecycleError);expect(sent).toEqual([result]);
  }finally{client.close();vi.unstubAllGlobals();}
});
it.each([false,true])('held result intent invalid=%s is admitted before its new request',async invalid=>{
  const {path,store,db}=context();const result={status:'succeeded',duration_ms:invalid?bound:1};db.prepare('INSERT INTO held_results(action_id,execution_result) VALUES (?,?)').run(env.action_id,JSON.stringify(result));
  const sent:any[]=[];vi.stubGlobal('fetch',vi.fn(async(_url:any,init:any)=>{sent.push(JSON.parse(init.body));return new Response('{}',{status:200});}));const client=hosted(path);client.store=store;
  try{if(invalid){let error:any;try{await client._pushFirst();}catch(e){error=e;}expect(error).toBeInstanceOf(NumericDomainError);expect(error.path).toEqual(['execution_result','duration_ms']);expect(sent).toEqual([]);expect(store.heldResults()).toEqual([{action_id:env.action_id,execution_result:result}]);}
    else{await client._pushFirst();expect(sent).toEqual([result]);expect(store.heldResults()).toEqual([]);}
  }finally{db.close();client.close();vi.unstubAllGlobals();}
});
it.each(['sequence','acknowledgement'])('hosted new %s remains admitted',async surface=>{
  const {path,store,db}=context();store.write(env,decision);const client=hosted(path);client.store=store;const sent:any[]=[];
  if(surface==='sequence')client.sequence=bound-1;
  vi.stubGlobal('fetch',vi.fn(async(_url:any,init:any)=>{sent.push(JSON.parse(init.body));return new Response(JSON.stringify({accepted:surface==='acknowledgement'?bound:1,errors:[]}),{status:200});}));
  try{let error:any;try{await client._pushFirst();}catch(e){error=e;}expect(error).toBeInstanceOf(surface==='sequence'?NumericDomainError:ServerError);if(surface==='sequence')expect(error.path).toEqual(['sync_sequence']);else{expect(error.status_code).toBe(200);expect(error.error_code).toBe('UNKNOWN_ERROR');expect(error.message).toContain('<root>["accepted"]');expect(error.message).toContain('JSON integer');expect(error.message).not.toContain('pass the value as text');}expect(sent).toHaveLength(surface==='sequence'?0:1);expect(store.getUnsynced()).toHaveLength(1);expect(snapshot(db).map(row=>row.refused)).toEqual([null]);}
  finally{db.close();client.close();vi.unstubAllGlobals();}
});

import ts from 'typescript';
import {ServerError,SyncError,AuditLogError,LifecycleError} from '../../src/exceptions.js';
function transportDeclarations(file:string){
  const text=readFileSync(resolve(__dirname,'../../src',file),'utf8');const source=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
  let statuses:number[]|undefined;const methods:Array<{method:string,args:unknown[]}>=[];
  function visit(node:ts.Node){
    if(ts.isVariableDeclaration(node)&&node.name.getText(source)==='RETRYABLE_STATUS_CODES'){
      const init=node.initializer;if(!init||!ts.isNewExpression(init)||!init.arguments?.[0]||!ts.isArrayLiteralExpression(init.arguments[0]))throw new Error('unread retry status declaration');
      statuses=JSON.parse(init.arguments[0].getText(source));
    }
    if(ts.isMethodDeclaration(node)&&!node.modifiers?.some(m=>m.kind===ts.SyntaxKind.PrivateKeyword)){
      let sends=false;function read(n:ts.Node){if(ts.isCallExpression(n)&&ts.isPropertyAccessExpression(n.expression)&&n.expression.name.text==='_sendWithRetry')sends=true;ts.forEachChild(n,read);}ts.forEachChild(node,read);
      if(sends){const fixture:Record<string,unknown>={records:[],syncSequence:1,etag:undefined};const args=node.parameters.map(p=>{const name=p.name.getText(source);if(!Object.hasOwn(fixture,name))throw new Error('unread transport input '+name);return fixture[name];});methods.push({method:node.name.getText(source),args});}
    }
    ts.forEachChild(node,visit);
  }
  visit(source);if(!statuses)throw new Error('unread retry statuses');return {statuses,methods};
}
const syncDecl=transportDeclarations('sync-client.ts'),hostedDecl=transportDeclarations('http-client.ts');
const syncErrors=syncDecl.methods.flatMap(({method,args})=>[400,...syncDecl.statuses].flatMap(status=>[0,1].flatMap(retries=>[false,true].map(invalid=>({method,args,status,retries,invalid,id:`${method}/${status}/${retries}/${invalid}`})))));
it.each(syncErrors)('$id sync current body is admitted before retry or projection',async({method,args,status,retries,invalid})=>{
  vi.useFakeTimers();const sent:string[]=[];const fetchImpl=vi.fn(async(url:any)=>{sent.push(String(url));return new Response(JSON.stringify({extra:{probe:invalid?bound:1}}),{status});});
  const client:any=new SyncClient({server_url:'https://fixture.invalid',api_key:'local-contract-fixture-key',org_id:env.org_id,environment:'dev',max_retries:retries,fetchImpl});
  try{let error:any;const pending=client[method](...args).catch((e:unknown)=>{error=e;});await vi.runAllTimersAsync();await pending;
    if(invalid){expect(error).toBeInstanceOf(SyncError);expect(error.cause_error?.path).toEqual(['extra','probe']);expect(String(error)).toContain('text');expect(sent).toHaveLength(1);}
    else{expect(error).toBeInstanceOf(SyncError);expect(sent).toHaveLength(syncDecl.statuses.includes(status)?retries+1:1);}
  }finally{vi.useRealTimers();}
});
const hostedErrors=['evaluate','result','audit','held-result'].flatMap(producer=>[400,...hostedDecl.statuses].flatMap(status=>[0,1].flatMap(retries=>[false,true].map(invalid=>({producer,status,retries,invalid,id:`${producer}/${status}/${retries}/${invalid}`})))));
it.each(hostedErrors)('$id hosted current body is admitted before classification',async({producer,status,retries,invalid})=>{
  vi.useFakeTimers();const {path,store,db}=context(),result={status:'succeeded',duration_ms:1};
  if(producer==='audit')store.write(env,decision);if(producer==='held-result')store.holdResult(env.action_id,result);
  const client=hosted(path);client.store=store;client.maxRetries=retries;client.unpushed=false;
  const before=snapshot(db),held=store.heldResults(),sent:string[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url:any)=>{sent.push(String(url));return new Response(JSON.stringify({extra:{probe:invalid?bound:1}}),{status});}));
  const calls:Record<string,()=>Promise<any>>={evaluate:()=>client.evaluate(structuredClone(env)),result:()=>client.recordResult(env.action_id,result),audit:()=>client._pushRecords(store),'held-result':()=>client._pushResults(store)};
  try{let error:any,actual:any;const pending=calls[producer]().then(v=>{actual=v;},e=>{error=e;});await vi.runAllTimersAsync();await pending;
    if(invalid){expect(error).toBeInstanceOf(ServerError);expect(error.status_code).toBe(status);expect(error.error_code).toBe('UNKNOWN_ERROR');expect(String(error)).toContain('<root>["extra"]["probe"]');expect(String(error)).toContain('text');expect(sent).toHaveLength(1);expect(snapshot(db)).toEqual(before);expect(store.heldResults()).toEqual(held);}
    else{expect(sent).toHaveLength(hostedDecl.statuses.includes(status)?retries+1:1);
      if(['evaluate','result'].includes(producer)&&status===400)expect(error).toBeInstanceOf(ServerError);
      else if(producer==='evaluate'){expect(error).toBeUndefined();expect(actual.decision).toBe('CONTROL_PLANE_UNAVAILABLE');expect(actual.reason_codes).toEqual(['CONTROL_PLANE_UNREACHABLE']);expect(actual.allowed).toBe(false);}
      else if(producer==='result'){expect(error).toBeUndefined();expect(actual).toEqual({action_id:env.action_id,execution_result:result,held:true});}
      else{expect(error).toBeUndefined();expect(actual).toEqual(hostedDecl.statuses.includes(status)?['CONTROL_PLANE_UNREACHABLE',`HTTP ${status}`]:undefined);}
    }
  }finally{db.close();client.close();vi.unstubAllGlobals();vi.useRealTimers();}
});
