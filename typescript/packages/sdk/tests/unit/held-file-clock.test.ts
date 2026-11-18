/** 70254bbc: a same-tick content change cannot keep the old policy answer. */
import {it, expect, vi} from 'vitest';
import fs from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {HIITL} from '../../src/client.js';

it.each(['json','yaml'])('same-tick %s rewrite and settled unchanged reading', async suffix => {
  const directory=fs.mkdtempSync(join(tmpdir(),'htl45-clock-'));
  const path=join(directory,'policy.'+suffix);
  const policy=JSON.parse(fs.readFileSync(resolve(__dirname,'../../../../../tests/conformance/sdk_startup/policy.json'),'utf8'));
  policy.rules[0].decision='ALLOW';fs.writeFileSync(path,JSON.stringify(policy));
  const client=new HIITL({policy_path:path,mode:'RESPECT_POLICY',org_id:policy.scope.org_id,audit_db_path:join(directory,'audit.db')});
  const loader=(client as any).policyLoader;
  const source=fs.statSync(path,{bigint:true});let clock=source.ctimeNs, reads=0;
  const stat=fs.statSync, fstat=fs.fstatSync, read=fs.readFileSync;
  const stamp=(value:any,t:bigint)=>({...value,ctimeNs:t,mtimeNs:source.mtimeNs});
  try {
    vi.spyOn(fs,'statSync').mockImplementation(((file:any,options:any)=>{
      const value=stat(file,options);return String(file)===path&&options?.bigint?stamp(value,source.ctimeNs):value;
    }) as any);
    vi.spyOn(fs,'fstatSync').mockImplementation(((fd:any,options:any)=>{
      const value=fstat(fd,options);return options?.bigint?stamp(value,clock):value;
    }) as any);
    vi.spyOn(fs,'readFileSync').mockImplementation(((file:any,...args:any[])=>{
      if(String(file)===path)reads++;return (read as any)(file,...args);
    }) as any);
    loader.invalidateCache();const old=loader.load();
    policy.version='v2.0.0';policy.rules[0].decision='BLOCK';fs.writeFileSync(path,JSON.stringify(policy));
    const decision=await client.evaluate({action:'guarded',parameters:{amount:100}});
    expect(decision.decision).toBe('BLOCK');expect(decision.policy_version).toBe('v2.0.0');
    expect((client as any).auditLogger.getUnsynced(10)[0].decision.decision).toBe('BLOCK');
    const held=loader.load();expect(held).not.toBe(old);
    clock++;expect(loader.load()).toBe(held);
    const before=reads;expect(loader.load()).toBe(held);expect(reads).toBe(before);
  } finally {vi.restoreAllMocks();client.close();fs.rmSync(directory,{recursive:true,force:true});}
});

it('an unavailable clock confirms content without new source permission', async () => {
  const {PolicyLoader}=await import('../../src/policy-loader.js');
  const directory=fs.mkdtempSync(join(tmpdir(),'htl45-clock-unavailable-')),path=join(directory,'policy.json');
  const policy=JSON.parse(fs.readFileSync(resolve(__dirname,'../../../../../tests/conformance/sdk_startup/policy.json'),'utf8'));
  fs.writeFileSync(path,JSON.stringify(policy));const open=fs.openSync;
  try {
    vi.spyOn(fs,'openSync').mockImplementation(((file:any,...args:any[])=>{
      if(String(file).includes('hiitl-file-clock-'))throw Object.assign(new Error('read-only clock directory'),{code:'EACCES'});
      return (open as any)(file,...args);
    }) as any);
    const loader=new PolicyLoader(path),held=loader.load();expect(loader.load()).toBe(held);
    policy.version='v2.0.0';fs.writeFileSync(path,JSON.stringify(policy));expect(loader.load().version).toBe('v2.0.0');
  } finally {vi.restoreAllMocks();fs.rmSync(directory,{recursive:true,force:true});}
});
