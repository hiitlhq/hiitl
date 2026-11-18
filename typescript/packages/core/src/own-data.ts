/** Open JSON data keeps every supplied own key, including names on Object.prototype. */
import { z } from 'zod';
import { assertNumericDomain, NumericDomainError, numericDeclaration, type NumericShape } from './numeric-domain.js';

const numberShapes=new WeakMap<z.ZodType,NumericShape>();
/** A typed refusal reads the same declaration as the parser, including derived objects. */
export function assertSchemaNumbers(value:unknown,schema:z.ZodType,path:(string|number)[]=[]):void {
  try {assertNumericDomain(value,path);}catch(error){
    if(!(error instanceof NumericDomainError))throw error;
    let shape=numberShapes.get(schema);
    if(!shape){shape=z.toJSONSchema(schema,{io:'input',unrepresentable:'any'});numberShapes.set(schema,shape);}
    const declaration=numericDeclaration(shape,error.path.slice(path.length),value);
    if(declaration)throw new NumericDomainError(error.path,declaration);
    throw error;
  }
}

type BeforeObject=(value:unknown,ctx:z.RefinementCtx)=>unknown;
type AdmittedDef=z.core.$ZodObjectDef & {beforeInput?:BeforeObject};
const ADMITTED_NUMBERS=Symbol('admitted supplied numbers');
/** Internal call-local reader; never used for a transport response or a new caller input. */
export function parseAdmittedNumbers<S extends z.ZodType>(schema:S,value:unknown):z.output<S>{
  return schema.parse(value,{[ADMITTED_NUMBERS]:true} as z.core.ParseContext<z.core.$ZodIssue>);
}
// Use Zod's extension constructor so clones made by pick/extend keep the same
// parser and their own shape. Admission precedes projection, including in nesting.
const AdmittedObject=z.core.$constructor<z.ZodObject,AdmittedDef>('AdmittedObject',(instance,def)=>{
  z.ZodObject.init(instance,def);
  (instance._zod.deferred??=[]).push(()=>{
    const run=instance._zod.run;
    instance._zod.run=(payload,ctx)=>{
      try{if(!(ctx as any)[ADMITTED_NUMBERS])assertSchemaNumbers(payload.value,instance);}catch(error){
        if(!(error instanceof NumericDomainError))throw error;
        payload.issues.push({code:'custom',path:error.path,message:error.message,input:payload.value});
        return payload;
      }
      if(def.beforeInput){
        const refinement={value:payload.value,issues:payload.issues,addIssue:(issue:any)=>payload.issues.push({...issue,input:payload.value})};
        payload.value=def.beforeInput(payload.value,refinement);
        if(payload.issues.length)return payload;
      }
      const admittedContext={...ctx,[ADMITTED_NUMBERS]:true};
      return run(payload,admittedContext);
    };
  });
});

/** A root reads supplied numbers before compilation/defaults; input and output types stay the schema's. */
export function numericInput<Schema extends z.ZodObject>(schema:Schema,beforeInput?:BeforeObject):Schema {
  return new AdmittedObject({...schema._zod.def,beforeInput}) as Schema;
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  if(value === null || typeof value !== 'object' || Array.isArray(value))return false;
  const prototype=Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

/** Own JSON containers before invoking callbacks; keep every supplied own key. */
export function copySuppliedInput<T>(value:T):T {
  if(Array.isArray(value))return value.map(copySuppliedInput) as T;
  if(isRecord(value))return Object.fromEntries(Object.entries(value).map(([key,child])=>[key,copySuppliedInput(child)])) as T;
  return value;
}

type ArmResult=z.core.ParsePayload;
const refusesKind=(result:ArmResult)=>result.issues.some(issue=>issue.code==='invalid_type'&&!issue.path?.length);
const undefinedMembers=(result:ArmResult)=>result.issues.reduce((n,issue)=>n+(issue.code==='unrecognized_keys'?issue.keys.length:0),0);
function closest(results:ArmResult[],payload:ArmResult):ArmResult {
  const passed=results.find(result=>!result.issues.length);
  if(passed){payload.value=passed.value;return payload;}
  const ofKind=results.filter(result=>!refusesKind(result));
  const nearest=(ofKind.length?ofKind:results).reduce((best,result)=>{
    const [members,errors]=[undefinedMembers(result),result.issues.length],[bestMembers,bestErrors]=[undefinedMembers(best),best.issues.length];
    return members<bestMembers||members===bestMembers&&errors<bestErrors?result:best;
  });
  payload.issues.push(...nearest.issues);
  return payload;
}
// Zod's union reports the one arm that did not abort, so an enum's refusal of the data's own arm was lost to another
// arm's undefined keys. This union reads Python's rule (input_types.py): an arm of the input's JSON kind, then the
// fewest undefined members, then the fewest errors (tests/conformance/TEST_DESIGN.md, `matches`).
const ClosestUnion=z.core.$constructor<z.ZodUnion,z.core.$ZodUnionDef>('ClosestUnion',(instance,def)=>{
  z.ZodUnion.init(instance,def);
  instance._zod.parse=(payload,ctx)=>{
    const results=def.options.map(option=>option._zod.run({value:payload.value,issues:[]},ctx));
    if(results.some(result=>result instanceof Promise))return Promise.all(results).then(settled=>closest(settled,payload));
    return closest(results as ArmResult[],payload);
  };
});
/** A union refused by the arm closest to the data; its type and JSON Schema are the union's. */
export function closestArm<const Options extends readonly z.core.SomeType[]>(options:Options):z.ZodUnion<Options> {
  return new ClosestUnion({type:'union',options:options as unknown as z.core.$ZodUnionDef['options']}) as unknown as z.ZodUnion<Options>;
}

/** Zod's record parser skips __proto__; this reader validates values and creates own data properties. */
export function dataRecord<Value extends z.ZodType>(schema: Value) {
  return z.custom<Record<string,z.input<Value>>>(isRecord,{message:'Expected a JSON object'})
    .transform((value,ctx): Record<string,z.output<Value>> => {
      const entries: [string,z.output<Value>][]=[];
      for(const [key,item] of Object.entries(value)) {
        const result=schema.safeParse(item);
        if(result.success)entries.push([key,result.data]);
        else for(const issue of result.error.issues)ctx.addIssue({...issue,path:[key,...issue.path]});
      }
      return Object.fromEntries(entries);
    }).meta({type:'object',additionalProperties:z.toJSONSchema(schema,{io:'input',unrepresentable:'any'})});
}

/** Read only supplied members: a sparse parent's absent values are not materialized by child defaults. */
export function checkMembers(value: Record<string,unknown>, members: Readonly<Record<string,z.ZodType>>, ctx: z.RefinementCtx, closed=false, unknownNote?: (key: string) => string | undefined): void {
  for(const [key,item] of Object.entries(value)) {
    if(!Object.hasOwn(members,key)) {
      if(closed)ctx.addIssue({code:'unrecognized_keys',keys:[key],path:[],
        message:[`Unrecognized key '${key}'`,unknownNote?.(key)].filter(note=>note!==undefined).join('. ')});
      continue;
    }
    const result=members[key].safeParse(item);
    if(!result.success)for(const issue of result.error.issues)ctx.addIssue({...issue,path:[key,...issue.path]});
  }
}

/** Known child declarations in an otherwise open object; omitted children remain omitted. */
export function declaredMemberShape(members:Readonly<Record<string,z.ZodType>>,closed=false) {
  // The same member readers supply diagnostics for these otherwise open objects.
  const { $schema,...shape }=z.toJSONSchema(z.object(Object.fromEntries(Object.entries(members).map(([key,schema])=>[key,schema.optional()]))).loose(),{io:'input',unrepresentable:'any'});
  return {...shape,additionalProperties:!closed};
}
export const dataObject=(members:Readonly<Record<string,z.ZodType>>)=>dataRecord(z.any()).superRefine((value,ctx)=>checkMembers(value,members,ctx)).meta(declaredMemberShape(members));

const preparedSchemas = new WeakSet<z.ZodType>();
/** Build owned schema readers where their input owner is constructed.
 *
 * The Zod object parser compiles on its first object, even if it is invalid.
 * Prepare every declared child, not a chosen valid envelope: no evaluation,
 * decision, admission exemption, or public schema surface changes here.
 */
export function prepareInputSchemas(...schemas: z.ZodType[]): void {
  const visited = new Set<object>();
  function visit(value: unknown): void {
    if (value === null || typeof value !== 'object' || visited.has(value)) return;
    visited.add(value);
    if ('_zod' in value && 'safeParse' in value) {
      const schema = value as z.ZodType;
      if (preparedSchemas.has(schema)) return;
      preparedSchemas.add(schema);
      const definition = schema._zod.def as any;
      if (definition.type === 'lazy') visit(definition.getter());
      for (const [key, child] of Object.entries(definition)) {
        if (key !== 'defaultValue' && key !== 'checks') visit(child);
      }
      if (definition.type === 'object') {
        // parse bypasses the root refinement; child declarations retain their
        // parsers. An empty object compiles the reader without a guarded action.
        schema._zod.parse({value: {}, issues: []}, {async: false});
      }
      if (!numberShapes.has(schema)) {
        numberShapes.set(schema, z.toJSONSchema(schema, {io:'input', unrepresentable:'any'}));
      }
      return;
    }
    for (const child of Object.values(value)) visit(child);
  }
  for (const schema of schemas) visit(schema);
}
