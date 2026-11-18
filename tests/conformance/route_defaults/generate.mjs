/** HTL-39 oracle: source declarations plus valid input shapes, never a default-field list. */
import { readFileSync } from 'node:fs';
const read = (url) => readFileSync(url, 'utf8');
export const copy = (value) => structuredClone(value);
export function schemaFromMarkdown(text) {
  const sections = text.split(/^### JSON Schema\s*$/m);
  if (sections.length !== 2) throw new Error('expected one JSON Schema heading');
  const match = /^\s*```json\s*\n([\s\S]*?)\n```/m.exec(sections[1]);
  if (!match) throw new Error('missing JSON Schema fence');
  return JSON.parse(match[1]);
}
export const routeSchema = schemaFromMarkdown(read(new URL('../../../docs/specs/routes.md', import.meta.url)));
export const decisionSchema = schemaFromMarkdown(read(new URL('../../../docs/specs/decision_response.md', import.meta.url)));
export const witnesses = JSON.parse(read(new URL('./witnesses.json', import.meta.url))).witnesses;
const escape = (s) => s.replaceAll('~', '~0').replaceAll('/', '~1');
const readDocument = file => JSON.parse(read(new URL(`../../../docs/specs/${file}`, import.meta.url)));
function deref(root, node, address, documents = readDocument) {
  const references = [], seen = new Set();
  while (node.$ref) {
    const [file, fragment] = node.$ref.split('#');
    if (!fragment?.startsWith('/') || (file && /[/:]/.test(file))) throw new Error(`unsupported reference ${node.$ref}`);
    const document = file ? documents(file) : root;
    address = `${file || address.split('#')[0]}#${fragment}`;
    if (seen.has(address)) throw new Error(`recursive schema at ${address}`);
    seen.add(address);
    node = fragment.slice(1).split('/').reduce((v, k) => v[k.replaceAll('~1','/').replaceAll('~0','~')], document);
    references.push([address, node]);
    root = document;
  }
  return { node, address, document:root, references };
}
/** Paths describe instance members; addresses independently hold declaration coverage. */
export function defaults(root, documents = readDocument) {
  const rows = [], visited = new Set(), referenced = new Map();
  function walk(document, raw, path, rawAddress, ancestors = []) {
    const { node, address, document:owner, references } = deref(document, raw, rawAddress, documents);
    for (const [targetAddress, target] of references) referenced.set(targetAddress, target);
    if (ancestors.includes(address)) throw new Error(`recursive schema at ${address}`);
    const next = [...ancestors, address];
    if (Object.hasOwn(node, 'default')) { rows.push({ path, value: copy(node.default), address }); visited.add(address); }
    for (const [key, child] of Object.entries(node.properties ?? {})) walk(owner, child, [...path, key], `${address}/properties/${escape(key)}`, next);
    if (node.items) walk(owner, node.items, [...path, '*'], `${address}/items`, next);
  }
  walk(root, root, [], '#');
  function declarations(node, address = '#') {
    if (!node || typeof node !== 'object') return;
    if (!Array.isArray(node) && Object.hasOwn(node, 'default') && !visited.has(address)) throw new Error(`unread default declaration ${address}`);
    for (const [key, child] of Object.entries(node)) if (key !== 'default') declarations(child, `${address}/${escape(key)}`);
  }
  declarations(root);
  for (const [address, target] of referenced) declarations(target, address);
  return rows;
}
export function applyDefaults(root, input, raw = root) {
  const { node, document } = deref(root, raw, '#');
  const value = copy(input);
  if (Array.isArray(value)) return value.map(v => applyDefaults(document, v, node.items ?? {}));
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(node.properties ?? {})) {
      const resolved = deref(document, child, '#').node;
      if (!Object.hasOwn(value, key) && Object.hasOwn(resolved, 'default')) value[key] = copy(resolved.default);
      if (Object.hasOwn(value, key)) value[key] = applyDefaults(document, value[key], child);
    }
  }
  return value;
}
function parents(value, path) {
  if (path.length === 0) return [{ value, path: [] }];
  const [key, ...rest] = path;
  if (key === '*') return Array.isArray(value) ? value.flatMap((item, i) => parents(item, rest).map(p => ({ value:p.value, path:[i,...p.path] }))) : [];
  return value && Object.hasOwn(value, key) ? parents(value[key], rest).map(p => ({ value:p.value, path:[key,...p.path] })) : [];
}
export function omissionCases(root = routeSchema, inputs = witnesses) {
  return defaults(root).flatMap(declaration => {
    const rows = [];
    for (const witness of inputs.filter(w => w.omit_defaults !== false)) for (const parent of parents(witness.input, declaration.path.slice(0,-1))) {
      if (!parent.value || typeof parent.value !== 'object' || Array.isArray(parent.value)) continue;
      const input = copy(witness.input), path = [...parent.path, declaration.path.at(-1)];
      const container = parent.path.reduce((v,k) => v[k], input);
      delete container[path.at(-1)];
      rows.push({ id:`${declaration.path.join('.')}@${witness.id}:${parent.path.join('.')}`, path, declaration:declaration.address, input, expected:applyDefaults(root,input) });
    }
    if (rows.length === 0) throw new Error(`no omission witness for ${declaration.path.join('.')} (${declaration.address})`);
    return rows;
  });
}
export function expectedContext(route, schema = decisionSchema) {
  return Object.fromEntries(Object.entries(schema.properties.escalation_context.properties).flatMap(([key, node]) => {
    const match = /^The route's `([^`]+)`/.exec(node.description);
    if (!match) throw new Error(`unread context projection ${key}`);
    let value = route;
    for (const part of match[1].split('.')) { if (!value || !Object.hasOwn(value, part)) return []; value = value[part]; }
    return [[key,copy(value)]];
  }));
}
export function allCases() {
  return [...omissionCases(), ...witnesses.map(w => ({ id:w.id, input:copy(w.input), expected:applyDefaults(routeSchema,w.input) }))];
}
