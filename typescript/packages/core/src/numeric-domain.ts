/** One held-number admission rule: sync_engine.md#numeric-domain. */
export const NUMERIC_BOUND = 2 ** 53;
export type NumericPath = ReadonlyArray<string | number>;
export type NumericShape = Record<string, any>;

/** The owning declaration is read on error, never added to the admitted hot path. */
export function numericDeclaration(shape: NumericShape, path: NumericPath, value?:unknown): NumericShape | undefined {
  const member=(current:any,key:string|number)=>current!==null && typeof current==='object'?current[key]:undefined;
  const matches=(current:any,condition:NumericShape):boolean=>{
    if(Object.hasOwn(condition,'const') && current!==condition.const)return false;
    if((condition.required??[]).some((key:string)=>current===null || typeof current!=='object' || !Object.hasOwn(current,key)))return false;
    return Object.entries(condition.properties??{}).every(([key,child])=>current===null || typeof current!=='object' || !Object.hasOwn(current,key) || matches(current[key],child as NumericShape));
  };
  const branchFits=(node:NumericShape,current:any):boolean=>{
    if(!node || typeof node!=='object')return (node as unknown)!==false;
    if(node.$ref){let target=shape;for(const part of node.$ref.replace(/^#\//,'').split('/'))target=target[part.replace(/~1/g,'/').replace(/~0/g,'~')];return branchFits(target,current);}
    if(node.type==='object'){
      if(current===null || typeof current!=='object' || Array.isArray(current))return false;
      if(node.additionalProperties===false && Object.keys(current).some(key=>!Object.hasOwn(node.properties??{},key)))return false;
    }else if(node.type==='array' && !Array.isArray(current))return false;
    else if(node.type==='null' && current!==null)return false;
    else if(['string','boolean'].includes(node.type) && typeof current!==node.type)return false;
    else if(['integer','number'].includes(node.type) && typeof current!=='number')return false;
    return matches(current,node);
  };
  const read=(node:NumericShape,remaining:NumericPath,current:unknown):NumericShape|undefined=>{
    if((node as unknown)===false)return {forbidden:true};
    if(!node || typeof node!=='object')return undefined;
    if(node.$ref){let target=shape;for(const part of node.$ref.replace(/^#\//,'').split('/'))target=target[part.replace(/~1/g,'/').replace(/~0/g,'~')];return read(target,remaining,current);}
    for(const branch of node.allOf??[]){const found=read(branch,remaining,current);if(found)return found;}
    if(node.if){const found=read(node[matches(current,node.if)?'then':'else']??{},remaining,current);if(found)return found;}
    const branches:NumericShape[]=node.anyOf??node.oneOf??[];
    const fitting=branches.filter(branch=>branchFits(branch,current));
    const choices=(fitting.length?fitting:branches).map(branch=>read(branch,remaining,current)).filter((found:NumericShape|undefined)=>found!==undefined) as NumericShape[];
    if(choices.length){const found=choices.find(choice=>choice.type==='number')??choices.find(choice=>choice.type==='integer')??choices.find(choice=>choice.type && choice.type!=='null')??choices[0];return {...found,...Object.fromEntries(Object.entries(node).filter(([key])=>['minimum','maximum','exclusiveMinimum','exclusiveMaximum'].includes(key)))};}
    if(!remaining.length)return node.type?node:undefined;
    const [key,...rest]=remaining;
    return read(typeof key==='number'?(node.items??{}):(node.properties?.[key]??node.additionalProperties??{}),rest,member(current,key));
  };
  return read(shape,path,value);
}

export class NumericDomainError extends Error {
  readonly path: Array<string | number>;
  constructor(path: NumericPath, declaration?: NumericShape) {
    const location = '<root>' + path.map((part) => '[' + JSON.stringify(part) + ']').join('');
    const bounds=declaration?Object.entries({minimum:'>=',maximum:'<=',exclusiveMinimum:'>',exclusiveMaximum:'<'}).filter(([key])=>declaration[key]!==undefined).map(([key,relation])=>`${relation} ${declaration[key]}`):[];
    super(declaration?.forbidden
      ? `Numeric value at ${location} is outside the shared domain; this member is not declared. Remove the undeclared member.`
      : declaration && !['integer','number'].includes(declaration.type)
      ? `Numeric value at ${location} is outside the shared domain; this member requires a JSON ${declaration.type}. Supply a value matching its declaration.`
      : declaration
      ? `Numeric value at ${location} must be a JSON ${declaration.type}, finite with magnitude below ${NUMERIC_BOUND}${bounds.length?' and '+bounds.join(', '):''}; supply a JSON ${declaration.type} within this declared range.`
      : `Numeric value at ${location} must be finite with magnitude below ${NUMERIC_BOUND}; pass the value as text instead.`);
    this.name = 'NumericDomainError';
    this.path = [...path];
  }
}

/** Inspect own JSON data members without coercing, filtering or copying them. */
export function assertNumericDomain(value: unknown, path: NumericPath = []): void {
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || Math.abs(value) >= NUMERIC_BOUND) throw new NumericDomainError(path);
  } else if (Array.isArray(value)) {
    value.forEach((member, index) => assertNumericDomain(member, [...path, index]));
  } else if (value !== null && typeof value === 'object') {
    for (const key of Object.keys(value)) {
      assertNumericDomain((value as Record<string, unknown>)[key], [...path, key]);
    }
  }
}
