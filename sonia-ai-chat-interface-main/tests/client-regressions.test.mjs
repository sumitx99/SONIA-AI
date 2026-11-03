import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const realRequire = createRequire(import.meta.url);
function loadTypeScript(path, imports = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((name) => imports[name] ?? realRequire(name), module, module.exports);
  return module.exports;
}
const noImages = loadTypeScript('../lib/remark-no-images.ts').default;
const image = () => ({ type: 'image', url: 'invented.png', alt: 'Figure 1' });
const text = (value) => ({ type: 'text', value });

test('model images and an image-only table are removed, prose is preserved', () => {
  const root = { type: 'root', children: [
    { type: 'paragraph', children: [text('Explanation')] },
    { type: 'paragraph', children: [image()] },
    { type: 'table', children: [
      { type: 'tableRow', children: [{ type: 'tableCell', children: [text('Figure')] }] },
      { type: 'tableRow', children: [{ type: 'tableCell', children: [image()] }] },
    ] },
  ] };
  noImages()(root);
  assert.equal(root.children.length, 1);
  assert.equal(root.children[0].children[0].value, 'Explanation');
});

test('ordinary comparison tables and image syntax inside code stay intact', () => {
  const table = { type: 'table', children: [
    { type: 'tableRow', children: [{ type: 'tableCell', children: [text('Header')] }] },
    { type: 'tableRow', children: [{ type: 'tableCell', children: [image(), text('Useful value')] }] },
  ] };
  const root = { type: 'root', children: [table, { type: 'code', value: '![example](file.png)' }] };
  noImages()(root);
  assert.equal(root.children.length, 2);
  assert.equal(table.children[1].children[0].children[0].value, 'Useful value');
  assert.equal(root.children[1].value, '![example](file.png)');
});

function client(auth = {}) {
  return loadTypeScript('../lib/api.ts', { '@/lib/supabase': { supabase: { auth: {
    getSession: async () => ({ data: { session: { access_token: 'old-token' } } }),
    refreshSession: async () => ({ data: { session: { access_token: 'renewed-token' } } }),
    signOut: async () => {}, ...auth,
  } } } });
}
const response = (status, payload) => new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } });

test('automatic upload retries reuse a request ID and keep the document scope', async (t) => {
  const calls = [];
  const timer = globalThis.setTimeout;
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => timer(fn, ms < 10_000 ? 0 : ms, ...args));
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push(init.body);
    return calls.length === 1 ? response(503, { detail: 'Starting' }) : response(200, { file_id: 7 });
  });
  const result = await client().uploadPDF(new File(['%PDF-demo'], 'demo.pdf'), 'chat-1');
  assert.equal(result.file_id, 7);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].get('request_id'), calls[1].get('request_id'));
  assert.equal(calls[1].get('chat_id'), 'chat-1');
});

test('an expired access token is renewed before retrying instead of signing out', async (t) => {
  const headers = [];
  let signedOut = false;
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    headers.push(init.headers.get('Authorization'));
    return headers.length === 1 ? response(401, {}) : response(200, { conversations: [] });
  });
  assert.deepEqual(await client({ signOut: async () => { signedOut = true; } }).loadConversations(), []);
  assert.deepEqual(headers, ['Bearer old-token', 'Bearer renewed-token']);
  assert.equal(signedOut, false);
});

test('an oversized document is rejected before any network request', async (t) => {
  let called = false;
  t.mock.method(globalThis, 'fetch', async () => { called = true; });
  await assert.rejects(client().uploadPDF({ size: 26 * 1024 * 1024 }), /25 MB/);
  assert.equal(called, false);
});
