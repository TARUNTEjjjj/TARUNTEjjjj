import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {validateConfig,readCatalog} from './resource-catalog.mjs';
const config=validateConfig(JSON.parse(await readFile('resources/sources.json','utf8')));
const raw=JSON.parse(await readFile('resources/catalog.json','utf8'));
assert.equal(raw.schemaVersion,1);
assert.equal(raw.project,config.project);
assert.ok(Array.isArray(raw.items) && raw.items.length>0,'Catalog must contain resources');
assert.equal(Object.hasOwn(raw,'sourceCache'),false,'Transport cache must not be published');
assert.ok(Buffer.byteLength(JSON.stringify(raw))<250000,'Public catalog must remain compact');
const validated=await readCatalog(config,{snapshotPath:'resources/catalog.json'});
assert.equal(validated.items.length,raw.items.length,'All committed resource records must validate');
for(const category of config.categories) {
 const items=raw.items.filter(item=>item.category===category.id);
 assert.ok(items.length<=config.maxPerCategory);
 assert.equal(new Set(items.map(item=>item.id)).size,items.length,'Duplicate category members');
}
console.log(`${config.project}: ${raw.items.length} valid resource memberships`);
