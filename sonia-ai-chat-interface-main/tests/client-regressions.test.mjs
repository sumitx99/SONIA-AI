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

const charts = loadTypeScript('../lib/chart-spec.ts');

test('a plotly block becomes a chart spec and picks the smallest Plotly build', () => {
  const bar = charts.parseChartSpec(JSON.stringify({
    data: [{ type: 'bar', name: 'BLEU', x: ['ByteNet', 'Transformer'], y: [23.75, 28.4] }],
    layout: { title: { text: 'BLEU (EN→DE)' }, yaxis: { title: 'BLEU' } },
  }));
  assert.equal(bar.bundle, 'cartesian');
  assert.equal(bar.title, 'BLEU (EN→DE)');
  assert.deepEqual(charts.chartTables(bar), [{ name: 'BLEU', columns: ['x', 'y'], rows: [['ByteNet', 23.75], ['Transformer', 28.4]] }]);
  const map = charts.parseChartSpec(JSON.stringify({ data: [{ type: 'choropleth', locations: ['India'], z: [6.8] }] }));
  assert.equal(map.bundle, 'geo');
  const street = charts.parseChartSpec(JSON.stringify({ data: [{ type: 'scattermap', lat: [28.6], lon: [77.2] }] }));
  assert.equal(street.bundle, 'map');
  assert.equal(charts.parseChartSpec('{"data":[{"y":[1,2,3]}]}').data[0].type, 'scatter');
});

test('chart JSON from the model cannot load outside content or overload the page', () => {
  const spec = charts.parseChartSpec(JSON.stringify({
    data: [{ type: 'choroplethmap', geojson: 'https://evil.example/shapes.json', locations: ['a'], z: [1] }],
  }));
  assert.match(spec.error, /aren't supported/);
  const cleaned = charts.parseChartSpec(JSON.stringify({
    data: [{ type: 'scattermap', lat: [1], lon: [2], geojson: 'https://evil.example/x.json' }],
    layout: { images: [{ source: 'https://evil.example/pixel.png' }], template: { layout: {} },
              map: { style: 'https://evil.example/style.json', center: { lat: 1, lon: 2 }, zoom: 4 },
              shapes: [{ type: 'path', path: 'M0 0' }, { type: 'line', x0: 0, x1: 1 }] },
  }));
  assert.equal('geojson' in cleaned.data[0], false);
  assert.deepEqual(Object.keys(cleaned.layout).sort(), ['map', 'shapes']);
  assert.deepEqual(cleaned.layout.map, { center: { lat: 1, lon: 2 }, zoom: 4 });
  assert.deepEqual(cleaned.layout.shapes, [{ type: 'line', x0: 0, x1: 1 }]);
  const huge = charts.parseChartSpec(JSON.stringify({ data: [{ y: Array.from({ length: 20_001 }, (_, i) => i) }] }));
  assert.match(huge.error, /too many points/);
  assert.match(charts.parseChartSpec(JSON.stringify({ data: [{ type: 'bar', y: [1] }, { type: 'scattergeo', lat: [1], lon: [1] }] })).error, /mix map/);
  assert.match(charts.parseChartSpec('{"data": [{"type": "bar", "y": [1, 2').error, /not valid JSON/);
});
