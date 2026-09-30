import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../Resources/Web/analytics-portal.js', import.meta.url), 'utf8');
function page(pathname = '/workbench') {
  const calls = [], nodes = [];
  const context = {
    URL, Request, Headers,
    location: { origin: 'http://localhost:8096', href: 'http://localhost:8096' + pathname, pathname },
    document: {
      getElementById: id => nodes.find(node => node.id === id),
      createElement: () => ({ style: {} }),
      body: { append: node => nodes.push(node) }
    },
    window: { fetch: (...args) => { calls.push(args); return Promise.resolve({ status: 200 }); } }
  };
  vm.runInNewContext(source, context);
  return { context, calls, nodes };
}

test('adds one analytics link without replacing page content', () => {
  const { context, nodes } = page();
  vm.runInNewContext(source, context);
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].href, '/analytics');
});

test('tags decision POSTs while preserving headers and body', async () => {
  const { context, calls } = page();
  await context.window.fetch('/v1/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(calls[0][1].headers.get('X-JEV-Client'), 'workbench');
  assert.equal(calls[0][1].headers.get('X-JEV-Purpose'), 'interactive-test');
  assert.equal(calls[0][1].headers.get('Content-Type'), 'application/json');
  assert.equal(calls[0][1].body, '{}');
});

test('respects explicit client and purpose labels', async () => {
  const { context, calls } = page();
  await context.window.fetch('/v1/decision', { method: 'POST', headers: { 'X-JEV-Client': 'specific-app', 'X-JEV-Purpose': 'classification' } });
  assert.equal(calls[0][1].headers.get('X-JEV-Client'), 'specific-app');
  assert.equal(calls[0][1].headers.get('X-JEV-Purpose'), 'classification');
});

test('does not tag health checks, analytics polling or other origins', async () => {
  const { context, calls } = page();
  const init = { method: 'POST' };
  await context.window.fetch('/health');
  await context.window.fetch('/api/analytics');
  await context.window.fetch('https://provider.example/v1/decision', init);
  assert.equal(calls[0][1], undefined);
  assert.equal(calls[1][1], undefined);
  assert.equal(calls[2][1], init);
});

test('supports Request instances without losing headers', async () => {
  const { context, calls } = page();
  const request = new Request('http://localhost:8096/v1/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  await context.window.fetch(request);
  assert.equal(calls[0][0], request);
  assert.equal(calls[0][1].headers.get('Content-Type'), 'application/json');
  assert.equal(calls[0][1].headers.get('X-JEV-Client'), 'workbench');
});

test('landing page does not intercept fetch', async () => {
  const { context, calls } = page('/');
  const init = { method: 'POST' };
  await context.window.fetch('/v1/decision', init);
  assert.equal(calls[0][1], init);
});

test('analytics JavaScript parses, has no external scripts or token persistence', () => {
  const html = readFileSync(new URL('../Resources/Web/analytics.html', import.meta.url), 'utf8');
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  new vm.Script(scripts[0][1]);
  assert.doesNotMatch(html, /<script[^>]+src=["']https?:/i);
  assert.doesNotMatch(html, /localStorage|sessionStorage/);
});
