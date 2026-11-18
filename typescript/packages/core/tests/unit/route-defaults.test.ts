/** HTL-39: source-generated defaults, not the review's field inventory. */
import { describe, expect, it } from 'vitest';
import { RouteSchema } from '../../src/route-types.js';
import { allCases, applyDefaults, defaults, omissionCases, routeSchema, witnesses } from '../../../../../tests/conformance/route_defaults/generate.mjs';

describe('gap 272 declared route defaults', () => {
  it.each(allCases())('reads exact schema defaults and explicit values: $id', row => {
    expect(RouteSchema.parse(row.input)).toStrictEqual(row.expected);
  });
  it('covers every discovered source declaration', () => {
    expect(new Set(omissionCases().map(row => row.declaration))).toStrictEqual(new Set(defaults(routeSchema).map(row => row.address)));
  });
  it.each([false, 0, '', [], {}])('reads a new referenced array default %j', value => {
    const schema = { properties:{ items:{ type:'array', items:{$ref:'#/$defs/item'} } }, $defs:{item:{properties:{added:{default:value}}}} };
    expect(omissionCases(schema, [{id:'new',input:{items:[{}]}}])).toStrictEqual([
      {id:'items.*.added@new:items.0', path:['items',0,'added'], declaration:'#/$defs/item/properties/added', input:{items:[{}]}, expected:{items:[{added:value}]}}
    ]);
    expect(applyDefaults(schema, {})).toStrictEqual({});
  });
  it('refuses unwitnessed and unread source defaults', () => {
    expect(() => omissionCases({properties:{parent:{properties:{child:{default:false}}}}}, [{id:'absent',input:{}}])).toThrow('no omission witness for parent.child');
    expect(() => defaults({allOf:[{properties:{child:{default:0}}}]})).toThrow('unread default declaration #/allOf/0/properties/child');
  });
  it.each(witnesses)('defaults retain required root members: $id', row => {
    for (const key of routeSchema.required) {
      const value = structuredClone(row.input);
      delete value[key];
      expect(RouteSchema.safeParse(value).success).toBe(false);
    }
  });
});


it('audits an external target but not unreferenced members', () => {
  const schema = {properties:{referenced:{$ref:'external.json#/$defs/target'}}};
  const external: Record<string, any> = {$defs:{target:{allOf:[{default:'new'}]}, unrelated:{default:'not referenced'}}};
  expect(() => defaults(schema, () => external)).toThrow('unread default declaration external.json#/$defs/target/allOf/0');
  external.$defs.target = {properties:{written:{default:false}}};
  expect(defaults(schema, () => external)).toStrictEqual([
    {path:['referenced','written'],value:false,address:'external.json#/$defs/target/properties/written'}
  ]);
});


it('follows reference aliases in their owning document', () => {
  const external = {$defs:{alias:{$ref:'#/$defs/target'},target:{properties:{value:{default:false}}}}};
  const schema = {properties:{item:{$ref:'external.json#/$defs/alias'}}};
  expect(defaults(schema, () => external)).toStrictEqual([
    {path:['item','value'],value:false,address:'external.json#/$defs/target/properties/value'}
  ]);
  const local: Record<string, any> = {...external,properties:{item:{$ref:'#/$defs/alias'}}};
  expect(applyDefaults(local, {item:{}})).toStrictEqual({item:{value:false}});
  local.$defs.target = {default:false};
  expect(applyDefaults(local, {})).toStrictEqual({item:false});
});


it('names reference cycles', () => {
  const schema = {$defs:{loop:{$ref:'#/$defs/loop'}},properties:{item:{$ref:'#/$defs/loop'}}};
  expect(() => defaults(schema)).toThrow('recursive schema at #/$defs/loop');
  expect(() => applyDefaults(schema, {item:{}})).toThrow('recursive schema at #/$defs/loop');
});
