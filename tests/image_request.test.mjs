import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../Resources/Web/index.html', import.meta.url), 'utf8');
const core = html.split('// IMAGE-REQUEST-CORE-START')[1].split('// IMAGE-REQUEST-CORE-END')[0];
const sandbox = vm.createContext({});
vm.runInContext(core + ';globalThis.filter = filterRequestImages;', sandbox);
test('batch filtering preserves images referenced in nested criteria or shared context', () => {
  const request = { contexts: ['shared-image'], schema: { q: { criteria: { yes: ['criterion-image'] } } }, assets: { 'shared-image': {}, 'criterion-image': {}, unused: {} } };
  sandbox.filter(request);
  assert.deepEqual(Object.keys(request.assets), ['shared-image', 'criterion-image']);
});
test('asset references in object keys do not count as visual evidence', () => {
  const request = { contexts: ['text'], schema: { q: { choices: ['key-image', 'other'], criteria: { 'key-image': 'text' } } }, assets: { 'key-image': {} } };
  sandbox.filter(request);
  assert.equal(request.assets, undefined);
});
test('all inline Workbench JavaScript parses', () => {
  for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});
