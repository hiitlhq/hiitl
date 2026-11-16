/** Reserved policy forms, policy_format.md#reserved-policy-values. No new resolution. */
const MARKERS = new Set(['$field', '$declared', '$uncalibrated']);
export class PolicyValueError extends Error {
  constructor(message: string, readonly paths: (string|number)[][]) { super(message); }
}
export function assertPolicyValues(value: unknown, role = 'policy', path: (string|number)[] = []): void {
  if (Array.isArray(value)) {
    const childRole:Record<string,string>={rules:'rule',conditions:'condition',windows:'window',operand:'placeholder',placeholder:'placeholder'};
    value.forEach((child,index)=>assertPolicyValues(child,childRole[role]??'data',[...path,index]));
  } else if (value !== null && typeof value === 'object') {
    const data=value as Record<string,unknown>,keys=Object.keys(data).filter(key=>MARKERS.has(key));
    if(keys.length){
      const allowed:Record<string,string[]>={operand:['$field','$declared','$uncalibrated'],placeholder:['$declared','$uncalibrated'],reference:['$declared'],bound:['$uncalibrated']};
      if(Object.keys(data).length!==1 || !keys.every(key=>(allowed[role]??[]).includes(key))) {
        const location='<root>'+path.map(part=>'['+JSON.stringify(part)+']').join('');
        throw new PolicyValueError(`Reserved policy marker at ${location}: ${keys.sort().join(', ')} must be the sole key at a position that reads that form. Remove sibling keys or move the form to a supported position.`, [path,...Object.keys(data).map(key=>[...path,key])]);
      }
      const key=keys[0];assertPolicyValues(data[key],key==='$field'?'reference':'data',[...path,key]);return;
    }
    for(const [key,child] of Object.entries(data)){
      let next='data';
      if(role==='policy'&&key==='rules')next='rules';
      else if(role==='policy'&&key==='metadata')next='metadata';
      else if(role==='metadata'&&key==='rate_limits')next='windows';
      else if(role==='rule'&&key==='metadata')next='rule_metadata';
      else if(role==='rule_metadata'&&key==='compiled_from')next='provenance';
      else if(role==='provenance'&&key==='entry')next='window';
      else if(role==='rule'&&key==='conditions')next='condition';
      else if(role==='rule'&&key==='rate_limit')next='window';
      else if(role==='window'&&['limit','window_seconds'].includes(key))next='bound';
      else if(role==='condition'&&['all_of','any_of','none_of'].includes(key))next='conditions';
      else if(role==='condition'&&key==='value')next='operand';
      else if(['operand','placeholder'].includes(role))next='placeholder';
      assertPolicyValues(child,next,[...path,key]);
    }
  }
}
