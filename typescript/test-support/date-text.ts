import {readFileSync} from 'node:fs';
export const dateData=JSON.parse(readFileSync(new URL('../../tests/conformance/date_text/cases.json',import.meta.url),'utf8'));
export const lexicalDates=JSON.parse(readFileSync(new URL('../../tests/conformance/date_text/lexical-original.json',import.meta.url),'utf8')).filter((r:any)=>!r.native);

export const dateHashes=JSON.parse(readFileSync(new URL('../../tests/conformance/date_text/hash-vectors.json',import.meta.url),'utf8')).cases;
