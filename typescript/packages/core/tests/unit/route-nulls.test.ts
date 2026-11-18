/** HTL-41: the route schema's typed members decide explicit-null handling. */
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { RouteSchema } from '../../src/route-types.js';
import { forbiddenNulls } from '../../src/route-nulls.js';
import { generatedArtifacts, nullCases, nullShape, typedMembers } from '../../../../../tests/conformance/typed_members/generate.mjs';

const corpus = JSON.parse(readFileSync(new URL('../../../../../tests/conformance/typed_members/route-null-cases.json', import.meta.url), 'utf8')) as ReturnType<typeof import('../../../../../tests/conformance/typed_members/generate.mjs').routeCorpus>;

it.each(corpus.cases)('reads the declared null answer and names the member: $id', row => {
  expect(RouteSchema.safeParse(row.control).success, `${row.id} control`).toBe(true);
  const result = RouteSchema.safeParse(row.input);
  expect(result.success, row.id).toBe(row.expected_accept);
  if (!result.success) {
    expect(result.error.issues.map(issue => issue.path), row.id).toContainEqual(row.path);
  }
});

it.each(corpus.untyped_controls)('keeps untyped null data: $id', row => {
  const result = RouteSchema.parse(row.input);
  expect(result).toStrictEqual(row.input);
});

it('keeps the complete corpus and shipped shapes fresh from their source', () => {
  for (const [relative, expected] of Object.entries(generatedArtifacts())) {
    expect(readFileSync(new URL(`../../../../../${relative}`, import.meta.url), 'utf8'), relative).toBe(expected);
  }
});

it('discovers reference siblings, arrays and typed map values without a field list', () => {
  const schema = {type:'object',properties:{items:{type:'array',items:{$ref:'external.json#/$defs/item',properties:{extra:{type:'boolean'}}}},map:{type:'object',properties:{known:{type:'integer'}},additionalProperties:{type:'string'}}}};
  const external = {$defs:{item:{type:'object',properties:{value:{type:['string','null']}}},unused:{type:'number'}}};
  expect(typedMembers(schema, () => external).map(row => [row.address,row.path,row.types,row.allows_null])).toStrictEqual([
    ['#',[],['object'],false],
    ['#/properties/items',['items'],['array'],false],
    ['external.json#/$defs/item',['items','*'],['object'],false],
    ['external.json#/$defs/item/properties/value',['items','*','value'],['string','null'],true],
    ['#/properties/items/items/properties/extra',['items','*','extra'],['boolean'],false],
    ['#/properties/map',['map'],['object'],false],
    ['#/properties/map/properties/known',['map','known'],['integer'],false],
    ['#/properties/map/additionalProperties',['map','{key}'],['string'],false],
  ]);
  expect(nullShape(schema,()=>external).properties?.items.items?.properties).toStrictEqual({value:{allows_null:true},extra:{allows_null:false}});
  const rows = nullCases(schema,[{id:'new',input:{items:[{value:'written',extra:true}],map:{known:1,other:'written'}}}],()=>external);
  expect(rows.find(row=>row.path.join('.')==='items.0.value')?.expected_accept).toBe(true);
  expect(rows.filter(row=>row.declaration.endsWith('/additionalProperties')).map(row=>row.path)).toStrictEqual([['map','other']]);
});

it('reads nullable unions and composition as schema logic, not a forbidden-path union', () => {
  const schema={type:'object',properties:{choice:{anyOf:[{type:'string'},{type:'null'}]},restricted:{type:['string','null'],enum:['written']}}};
  const rows=nullCases(schema,[{id:'choice',input:{choice:'written',restricted:'written'}}]);
  expect(rows.filter(row=>row.path[0]==='choice').map(row=>row.expected_accept)).toStrictEqual([true,true]);
  expect(rows.find(row=>row.path[0]==='restricted')?.expected_accept).toBe(false);
  expect(nullShape(schema).properties).toStrictEqual({choice:{allows_null:true},restricted:{allows_null:false}});
});

it('names typed conditional structure that the compact runtime shape cannot represent', () => {
  const schema={type:'object',if:{properties:{kind:{type:'string'}}},then:{properties:{value:{type:'string'}}}};
  expect(typedMembers(schema).map(row=>row.address)).toStrictEqual(['#','#/if/properties/kind','#/then/properties/value']);
  expect(()=>nullShape(schema)).toThrow('unread null shape composition #/if');
});

it('refuses unwitnessed, unread and recursive typed declarations', () => {
  expect(()=>nullCases({properties:{added:{type:'string'}}},[{id:'missing',input:{}}])).toThrow('no typed witness for added');
  expect(()=>typedMembers({future:{properties:{added:{type:'string'}}}})).toThrow('unread type declaration #/future/properties/added');
  expect(()=>typedMembers({properties:{item:{$ref:'#/$defs/loop'}},$defs:{loop:{$ref:'#/$defs/loop'}}})).toThrow('recursive schema at #/$defs/loop');
  expect(()=>typedMembers({properties:{item:{$ref:'external.json#/$defs/item'}}},()=>({$defs:{item:{future:{type:'string'}},unused:{type:'number'}}}))).toThrow('unread type declaration external.json#/$defs/item/future');
  expect(typedMembers({type:'object',examples:[{type:'not a schema'}],default:{type:'not a schema'}}).map(row=>row.address)).toStrictEqual(['#']);
});

it('names intersections whose map scope the compact shape cannot represent', () => {
  const sibling={type:'object',allOf:[{properties:{own:{type:'string'}},additionalProperties:{type:'integer'}},{properties:{sibling:{type:'boolean'}}}]};
  expect(()=>nullShape(sibling)).toThrow('unread null shape intersection');
  const reference={$ref:'external.json#/$defs/map',properties:{sibling:{type:'boolean'}}};
  expect(()=>nullShape(reference,()=>({$defs:{map:{type:'object',additionalProperties:{type:'integer'}}}}))).toThrow('unread null shape intersection');
});

it('the null-only guard preserves admitted null, omission and non-null values', () => {
  const schema={type:'object',properties:{nullable:{type:['string','null']},required:{type:'string'},items:{type:'array',items:{type:'string'}},map:{type:'object',properties:{free:{}},additionalProperties:{type:'string'}}}};
  const shape=nullShape(schema);
  expect(forbiddenNulls({nullable:null,items:['written',null],map:{free:null,other:null,toString:null}},shape)).toStrictEqual([['items',1],['map','other'],['map','toString']]);
  expect(forbiddenNulls({nullable:null,required:17,unknown:null,toString:null},shape)).toStrictEqual([]);
  expect(forbiddenNulls(null,{allows_null:true})).toStrictEqual([]);
  expect(forbiddenNulls(null,{allows_null:false})).toStrictEqual([[]]);
});

it('refuses metadata types forbidden by the schema after HTL-43 supersedes the null-only boundary', () => {
  // CC finding (a), d82fe0f5: preserve the historical input; its former acceptance ends here.
  const input=structuredClone(corpus.untyped_controls[0].input);
  input.metadata={author:17,created_at:false,tags:{existing:'open metadata'}};
  const result=RouteSchema.safeParse(input);
  expect(result.success).toBe(false);
  if(!result.success)expect(result.error.issues.map(issue=>issue.path)).toStrictEqual([
    ['metadata','author'],['metadata','created_at'],['metadata','tags'],
  ]);
  input.metadata={author:'writer',created_at:'2026-11-14T12:00:00Z',tags:['source'],free:null};
  expect(RouteSchema.parse(input)).toStrictEqual(input);
});

it('reads const, intersection and exclusive-union null constraints', () => {
  const schema={type:'object',properties:{exact:{type:['string','null'],const:'written'},intersect:{allOf:[{type:['string','null']},{type:'string'}]},exclusive:{oneOf:[{type:['string','null']},{type:'null'}]}}};
  const rows=nullCases(schema,[{id:'logic',input:{exact:'written',intersect:'written',exclusive:'written'}}]);
  expect(rows.filter(row=>row.path.length).map(row=>[row.path,row.expected_accept])).toStrictEqual([[['exact'],false],[['intersect'],false],[['intersect'],false],[['exclusive'],false],[['exclusive'],false]]);
  expect(nullShape(schema).properties).toStrictEqual({exact:{allows_null:false},intersect:{allows_null:false},exclusive:{allows_null:false}});
});

it('follows external reference chains in the owning document', () => {
  const schema={properties:{member:{$ref:'external.json#/$defs/alias'}}};
  const external={$defs:{alias:{$ref:'#/$defs/leaf'},leaf:{type:['string','null']}}};
  expect(typedMembers(schema,()=>external)).toStrictEqual([{address:'external.json#/$defs/leaf',path:['member'],types:['string','null'],allows_null:true}]);
  expect(nullCases(schema,[{id:'alias',input:{member:'written'}}],()=>external).map(row=>row.expected_accept)).toStrictEqual([true]);
  expect(nullShape(schema,()=>external)).toStrictEqual({allows_null:true,properties:{member:{allows_null:true}}});
});
