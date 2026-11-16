/** Schema-derived explicit-null cases and compact shipped facts. No product model is an oracle. */
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { schemaFromMarkdown } from '../route_defaults/generate.mjs';

const rootUrl = new URL('../../../', import.meta.url);
const read = path => readFileSync(new URL(path, rootUrl), 'utf8');
const clone = value => structuredClone(value);
const escape = value => String(value).replaceAll('~', '~0').replaceAll('/', '~1');
const annotation = new Set(['default','enum','const','examples','description','title','$comment']);
const schemaMaps = new Set(['properties','patternProperties','dependentSchemas']);
const schemaArrays = new Set(['allOf','anyOf','oneOf','prefixItems']);
const schemaSingles = new Set(['items','additionalProperties','contains','propertyNames','if','then','else','not','unevaluatedItems','unevaluatedProperties']);
const readDocument = file => JSON.parse(read(`docs/specs/${file}`));
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const canonicalJson = value => JSON.stringify(sort(value));
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key,sort(value[key])]));
  return value;
}
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

function reference(document,node,address,documents) {
  const ref=node.$ref;
  const split=ref.indexOf('#');
  if(split<0) throw new Error(`unread schema reference ${ref}`);
  const file=ref.slice(0,split), fragment=ref.slice(split+1);
  if((file && /[/:]/.test(file)) || (fragment && !fragment.startsWith('/'))) throw new Error(`unread schema reference ${ref}`);
  const owner=file ? documents(file) : document;
  let target=owner;
  for(const part of fragment ? fragment.slice(1).split('/') : []) {
    const key=part.replaceAll('~1','/').replaceAll('~0','~');
    if(!isObject(target) || !Object.hasOwn(target,key)) throw new Error(`unread schema reference ${ref}`);
    target=target[key];
  }
  return {document:owner,node:target,address:`${file || address.split('#')[0]}#${fragment}`};
}
function typeList(node,address) {
  const types=Array.isArray(node.type) ? node.type : [node.type];
  if(!types.length || new Set(types).size!==types.length || types.some(type=>!['null','boolean','object','array','number','integer','string'].includes(type))) throw new Error(`unread type declaration ${address}`);
  return types;
}

/** Bounded JSON Schema assertions used for witness validation; unsupported assertions fail by name. */
export function valid(schema,value,documents=readDocument,document=schema,address='#',ancestors=[]) {
  if(typeof schema==='boolean') return schema;
  if(!isObject(schema)) throw new Error(`unread schema ${address}`);
  if(ancestors.includes(address)) throw new Error(`recursive schema at ${address}`);
  const next=[...ancestors,address];
  if(schema.$ref) {
    const target=reference(document,schema,address,documents);
    if(!valid(target.node,value,documents,target.document,target.address,next)) return false;
  }
  const matches=type=>type==='null' ? value===null : type==='array' ? Array.isArray(value) : type==='object' ? isObject(value) : type==='integer' ? typeof value==='number' && Number.isInteger(value) : type==='number' ? typeof value==='number' && Number.isFinite(value) : typeof value===type;
  if(Object.hasOwn(schema,'type') && !typeList(schema,address).some(matches)) return false;
  if(schema.enum && !schema.enum.some(item=>canonicalJson(item)===canonicalJson(value))) return false;
  if(Object.hasOwn(schema,'const') && canonicalJson(schema.const)!==canonicalJson(value)) return false;
  const child=(node,key,input=value)=>valid(node,input,documents,document,`${address}/${key}`,next);
  if(schema.allOf && !schema.allOf.every((node,i)=>child(node,`allOf/${i}`))) return false;
  if(schema.anyOf && !schema.anyOf.some((node,i)=>child(node,`anyOf/${i}`))) return false;
  if(schema.oneOf && schema.oneOf.filter((node,i)=>child(node,`oneOf/${i}`)).length!==1) return false;
  if(schema.not && child(schema.not,'not')) return false;
  if(schema.if) {
    const branch=child(schema.if,'if') ? 'then' : 'else';
    if(Object.hasOwn(schema,branch) && !child(schema[branch],branch)) return false;
  }
  if(typeof value==='string') {
    if(schema.pattern && !new RegExp(schema.pattern,'u').test(value)) return false;
    if(schema.minLength!==undefined && [...value].length<schema.minLength) return false;
    if(schema.maxLength!==undefined && [...value].length>schema.maxLength) return false;
  }
  if(typeof value==='number') {
    for(const [key,passes] of [['minimum',v=>value>=v],['maximum',v=>value<=v],['exclusiveMinimum',v=>value>v],['exclusiveMaximum',v=>value<v],['multipleOf',v=>Number.isInteger(value/v)]]) if(Object.hasOwn(schema,key) && !passes(schema[key])) return false;
  }
  if(Array.isArray(value)) {
    if(schema.minItems!==undefined && value.length<schema.minItems) return false;
    if(schema.maxItems!==undefined && value.length>schema.maxItems) return false;
    if(schema.uniqueItems && new Set(value.map(canonicalJson)).size!==value.length) return false;
    for(let i=0;i<value.length;i++) {
      const prefix=schema.prefixItems?.[i];
      if(prefix!==undefined ? !child(prefix,`prefixItems/${i}`,value[i]) : schema.items!==undefined && !child(schema.items,'items',value[i])) return false;
    }
    if(schema.contains) {
      const count=value.filter(item=>child(schema.contains,'contains',item)).length;
      if(count<(schema.minContains ?? 1) || count>(schema.maxContains ?? Infinity)) return false;
    }
  }
  if(isObject(value)) {
    if(schema.required?.some(key=>!Object.hasOwn(value,key))) return false;
    if(schema.minProperties!==undefined && Object.keys(value).length<schema.minProperties) return false;
    if(schema.maxProperties!==undefined && Object.keys(value).length>schema.maxProperties) return false;
    for(const [key,item] of Object.entries(value)) {
      let governed=false;
      if(Object.hasOwn(schema.properties ?? {},key)) { governed=true; if(!child(schema.properties[key],`properties/${escape(key)}`,item)) return false; }
      for(const [pattern,node] of Object.entries(schema.patternProperties ?? {})) if(new RegExp(pattern,'u').test(key)) { governed=true; if(!child(node,`patternProperties/${escape(pattern)}`,item)) return false; }
      if(!governed && Object.hasOwn(schema,'additionalProperties') && !child(schema.additionalProperties,'additionalProperties',item)) return false;
      if(schema.propertyNames && !child(schema.propertyNames,'propertyNames',key)) return false;
    }
    for(const [key,required] of Object.entries(schema.dependentRequired ?? {})) if(Object.hasOwn(value,key) && required.some(name=>!Object.hasOwn(value,name))) return false;
    for(const [key,node] of Object.entries(schema.dependentSchemas ?? {})) if(Object.hasOwn(value,key) && !child(node,`dependentSchemas/${escape(key)}`)) return false;
  }
  for(const key of ['unevaluatedProperties','unevaluatedItems','$dynamicRef']) if(Object.hasOwn(schema,key)) throw new Error(`unread schema assertion ${address}/${key}`);
  return true;
}

function discover(root,documents) {
  const rows=[],visited=new Set(),targets=new Map();
  function walk(document,node,path,address,ancestors=[],selectors=[]) {
    if(typeof node==='boolean') return;
    if(!isObject(node)) throw new Error(`unread schema ${address}`);
    if(ancestors.includes(address)) throw new Error(`recursive schema at ${address}`);
    const next=[...ancestors,address];
    if(node.$ref) {
      const target=reference(document,node,address,documents);
      targets.set(target.address,target.node);
      walk(target.document,target.node,path,target.address,next,selectors);
    }
    if(Object.hasOwn(node,'type')) {
      rows.push({address,path,types:typeList(node,address),allows_null:valid(node,null,documents,document,address),selectors});
      visited.add(address);
    }
    for(const [key,child] of Object.entries(node.properties ?? {})) walk(document,child,[...path,key],`${address}/properties/${escape(key)}`,next,[...selectors,null]);
    if(node.items!==undefined) walk(document,node.items,[...path,'*'],`${address}/items`,next,[...selectors,{after:(node.prefixItems ?? []).length}]);
    for(const [i,child] of (node.prefixItems ?? []).entries()) walk(document,child,[...path,i],`${address}/prefixItems/${i}`,next,[...selectors,null]);
    if(isObject(node.additionalProperties)) walk(document,node.additionalProperties,[...path,'{key}'],`${address}/additionalProperties`,next,[...selectors,{excluded:Object.keys(node.properties ?? {}),patterns:Object.keys(node.patternProperties ?? {})}]);
    for(const [pattern,child] of Object.entries(node.patternProperties ?? {})) walk(document,child,[...path,'{key}'],`${address}/patternProperties/${escape(pattern)}`,next,[...selectors,{pattern}]);
    for(const key of ['allOf','anyOf','oneOf']) for(const [i,child] of (node[key] ?? []).entries()) walk(document,child,path,`${address}/${key}/${i}`,next,selectors);
    for(const key of ['if','then','else','not']) if(Object.hasOwn(node,key)) walk(document,node[key],path,`${address}/${key}`,next,selectors);
    for(const [key,child] of Object.entries(node.dependentSchemas ?? {})) walk(document,child,path,`${address}/dependentSchemas/${escape(key)}`,next,selectors);
    // contains/propertyNames/unevaluated applicators have no unconditional child path.
    // The independent audit below names any type declaration in them as unread.
  }
  walk(root,root,[],'#');
  function audit(node,address='#') {
    if(!isObject(node)) return;
    if(Object.hasOwn(node,'type') && !visited.has(address)) throw new Error(`unread type declaration ${address}`);
    for(const [key,child] of Object.entries(node)) {
      if(annotation.has(key) || key==='$defs' || key==='definitions') continue;
      if(schemaMaps.has(key)) for(const [name,value] of Object.entries(child)) audit(value,`${address}/${key}/${escape(name)}`);
      else if(schemaArrays.has(key)) child.forEach((value,i)=>audit(value,`${address}/${key}/${i}`));
      else if(schemaSingles.has(key)) audit(child,`${address}/${key}`);
      else if(isObject(child)) audit(child,`${address}/${escape(key)}`);
      else if(Array.isArray(child)) child.forEach((value,i)=>audit(value,`${address}/${escape(key)}/${i}`));
    }
  }
  audit(root);
  for(const [address,target] of targets) audit(target,address);
  return rows;
}
export function typedMembers(schema,documents=readDocument) {
  return discover(schema,documents).map(({selectors,...row})=>row);
}
function locations(value,path,selectors,at=0,prefix=[]) {
  if(at===path.length) return [{value,path:prefix}];
  const key=path[at],selector=selectors[at];
  if(key==='*') return Array.isArray(value) ? value.flatMap((item,i)=>i>=(selector?.after ?? 0) ? locations(item,path,selectors,at+1,[...prefix,i]) : []) : [];
  if(key==='{key}') return isObject(value) ? Object.entries(value).filter(([name])=>selector?.pattern ? new RegExp(selector.pattern,'u').test(name) : !selector?.excluded?.includes(name) && !selector?.patterns?.some(pattern=>new RegExp(pattern,'u').test(name))).flatMap(([name,item])=>locations(item,path,selectors,at+1,[...prefix,name])) : [];
  return value!==null && typeof value==='object' && Object.hasOwn(value,key) ? locations(value[key],path,selectors,at+1,[...prefix,key]) : [];
}
export function nullCases(schema,witnesses,documents=readDocument) {
  for(const witness of witnesses) if(!valid(schema,witness.input,documents)) throw new Error(`invalid typed witness ${witness.id}`);
  return discover(schema,documents).flatMap(row=>{
    const cases=[];
    for(const witness of witnesses) for(const location of locations(witness.input,row.path,row.selectors)) {
      const control=clone(witness.input);
      let input=clone(control);
      if(!location.path.length) input=null;
      else {
        const parent=location.path.slice(0,-1).reduce((value,key)=>value[key],input);
        parent[location.path.at(-1)]=null;
      }
      cases.push({id:`${row.address}@${witness.id}:${location.path.join('.') || '<root>'}`,declaration:row.address,path:location.path,control,input,expected_accept:valid(schema,input,documents)});
    }
    if(!cases.length) throw new Error(`no typed witness for ${row.path.join('.') || '<root>'} (${row.address})`);
    return cases;
  });
}

function hasTypedChildren(node) {
  if(!isObject(node)) return false;
  for(const [key,value] of Object.entries(node)) {
    if(annotation.has(key) || key==='$defs') continue;
    if(key==='type' || key==='$ref') return true;
    if(Array.isArray(value) ? value.some(hasTypedChildren) : isObject(value) && hasTypedChildren(value)) return true;
  }
  return false;
}
function merge(left,right,address='#') {
  for(const [owner,sibling] of [[left,right],[right,left]]) {
    if(owner.additionalProperties && Object.keys(sibling.properties ?? {}).some(key=>!Object.hasOwn(owner.properties ?? {},key))) throw new Error(`unread null shape intersection ${address}: additionalProperties scope differs`);
  }
  const shape={allows_null:left.allows_null && right.allows_null};
  const keys=new Set([...Object.keys(left.properties ?? {}),...Object.keys(right.properties ?? {})]);
  if(keys.size) shape.properties=Object.fromEntries([...keys].map(key=>[key,left.properties?.[key] && right.properties?.[key] ? merge(left.properties[key],right.properties[key]) : clone(left.properties?.[key] ?? right.properties[key])]));
  for(const key of ['items','additionalProperties']) if(left[key] || right[key]) shape[key]=left[key] && right[key] ? merge(left[key],right[key]) : clone(left[key] ?? right[key]);
  return shape;
}
export function nullShape(schema,documents=readDocument) {
  typedMembers(schema,documents); // Independent declaration audit precedes emission.
  function build(document,node,address,ancestors=[]) {
    if(typeof node==='boolean') return {allows_null:node};
    if(ancestors.includes(address)) throw new Error(`recursive schema at ${address}`);
    const next=[...ancestors,address];
    let shape={allows_null:valid(node,null,documents,document,address)};
    if(node.$ref) {
      const target=reference(document,node,address,documents);
      shape=merge(shape,build(target.document,target.node,target.address,next));
    }
    const own={allows_null:true};
    if(node.properties) own.properties=Object.fromEntries(Object.entries(node.properties).map(([key,child])=>[key,build(document,child,`${address}/properties/${escape(key)}`,next)]));
    if(node.items!==undefined) own.items=build(document,node.items,`${address}/items`,next);
    if(isObject(node.additionalProperties)) own.additionalProperties=build(document,node.additionalProperties,`${address}/additionalProperties`,next);
    shape=merge(shape,own,address);
    for(const [i,child] of (node.allOf ?? []).entries()) shape=merge(shape,build(document,child,`${address}/allOf/${i}`,next));
    for(const key of ['if','then','else','not','dependentSchemas','patternProperties','prefixItems','contains','propertyNames','unevaluatedItems','unevaluatedProperties']) if(hasTypedChildren(node[key]) || Array.isArray(node[key]) && node[key].some(hasTypedChildren)) throw new Error(`unread null shape composition ${address}/${key}`);
    for(const key of ['anyOf','oneOf']) for(const [i,child] of (node[key] ?? []).entries()) {
      const branch=build(document,child,`${address}/${key}/${i}`,next);
      if(branch.properties || branch.items || branch.additionalProperties) throw new Error(`unread null shape composition ${address}/${key}/${i}`);
    }
    return shape;
  }
  return build(schema,schema,'#');
}

export const routeSchema=schemaFromMarkdown(read('docs/specs/routes.md'));
const witnessData=JSON.parse(read('tests/conformance/typed_members/witnesses.json'));
export function routeCorpus() {
  return {
    source_hashes:{'docs/specs/routes.md':digest(read('docs/specs/routes.md')),'docs/specs/envelope_schema.json':digest(read('docs/specs/envelope_schema.json'))},
    witness_hash:digest(read('tests/conformance/typed_members/witnesses.json')),
    declarations:typedMembers(routeSchema),
    cases:nullCases(routeSchema,witnessData.witnesses),
    untyped_controls:clone(witnessData.untyped_controls),
  };
}
export function generatedArtifacts() {
  const corpus=routeCorpus(),shape=nullShape(routeSchema),json=JSON.stringify(shape,null,2);
  const provenance=`Generated from routes.md JSON schema by tests/conformance/typed_members/generate.mjs. Source hashes: ${JSON.stringify(corpus.source_hashes)}`;
  return {
    'tests/conformance/typed_members/route-null-cases.json':JSON.stringify(corpus,null,2)+'\n',
    'python/hiitl/core/route_null_shape.py':`"""${provenance}"""\nimport json\n\nROUTE_NULL_SHAPE = json.loads(r'''${json}''')\n`,
    'typescript/packages/core/src/route-null-shape.ts':`/** ${provenance} */\nexport const ROUTE_NULL_SHAPE = ${json} as const;\n`,
  };
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  if(process.argv[2]!=='--write') throw new Error('Use --write to regenerate source-derived artifacts');
  for(const [file,content] of Object.entries(generatedArtifacts())) writeFileSync(new URL(file,rootUrl),content);
}
