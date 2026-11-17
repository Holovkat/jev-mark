import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../Resources/Web/index.html', import.meta.url), 'utf8');
const core = html.split('// IMAGE-REQUEST-CORE-START')[1].split('// IMAGE-REQUEST-CORE-END')[0];
const sandbox = vm.createContext({});
vm.runInContext(core + ';globalThis.filter = filterRequestImages;globalThis.iou=boxIntersectionOverUnion;globalThis.presence=boxPresence;', sandbox);
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

test('Box overlap validates geometry and compares normalized rectangles', () => {
  const box = { left: .1, right: .4, top: .2, bottom: .6 };
  assert.equal(sandbox.iou(box, box), 1);
  assert.equal(sandbox.iou(box, { left: .5, right: .8, top: .2, bottom: .6 }), 0);
  assert.equal(sandbox.iou({ ...box, left: NaN }, box), null);
});
test('Box presence gate hides absent or missing targets without using box confidence', () => {
  const definition = { presence_field: 'present', presence_threshold: .5 };
  assert.equal(sandbox.presence(definition, { present: { noul: .98 } }).draw, true);
  assert.equal(sandbox.presence(definition, { present: { noul: .02 } }).draw, false);
  assert.equal(sandbox.presence(definition, {}).draw, false);
  assert.match(sandbox.presence({}, {}).note, /candidate location/);
});
