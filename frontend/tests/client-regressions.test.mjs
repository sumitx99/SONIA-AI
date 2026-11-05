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
const noImages = loadTypeScript('../lib/markdown/remark-no-images.ts').default;
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

const charts = loadTypeScript('../lib/markdown/chart-spec.ts');

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

const chatContext = loadTypeScript('../lib/chat-context.ts');
test('editing a question preserves earlier turns and replaces its continuation', () => {
  const messages=[{id:'u1',sender:'user',content:'Compare CNN and RNN'},{id:'b1',sender:'bot',content:'Which metric?'},{id:'u2',sender:'user',content:'Accuracy'},{id:'b2',sender:'bot',content:'Old answer'}];
  const edited=chatContext.editConversation(messages,'u2','Use sample latency');
  assert.deepEqual(edited.before.map(m=>m.id),['u1','b1']);
  assert.deepEqual(edited.messages.map(m=>m.id),['u1','b1','u2']);
  assert.equal(edited.messages[2].content,'Use sample latency');
  assert.equal(messages[2].content,'Accuracy');
  assert.throws(()=>chatContext.editConversation(messages,'b1','Cannot edit answer'));
});
test('memory excludes errors, incomplete answers and image URLs, and stays bounded',()=>{
 const result=chatContext.conversationHistory([{sender:'user',content:'Question',images:[{url:'private-url'}]},{sender:'bot',content:'Failure',error:true},{sender:'bot',content:'Incomplete',streaming:true},{sender:'bot',content:'Finished'}]);
 assert.deepEqual(result,[{sender:'user',content:'Question'},{sender:'bot',content:'Finished'}]);
 const bounded=chatContext.conversationHistory(Array.from({length:60},(_,i)=>({sender:i%2?'bot':'user',content:'x'.repeat(2000)})));
 assert.ok(bounded.length<=20); assert.ok(bounded.reduce((n,m)=>n+m.content.length,0)<=24000); assert.equal(bounded[0].sender,'user');
});
test('streaming fallback preserves the same conversation memory and document scope',async(t)=>{
 const calls=[]; t.mock.method(globalThis,'fetch',async(url,init)=>{calls.push([url,init.body]);return calls.length===1?response(404,{}):response(200,{answer:'Follow-up answer'});});
 const memory=[{sender:'user',content:'Compare CNN and RNN'},{sender:'bot',content:'Need metrics'}]; let answer='';
 await client().streamMessage('assume any no',[7],{onDelta:piece=>answer+=piece},memory);
 assert.equal(answer,'Follow-up answer');assert.equal(calls.length,2);
 for(const[,body] of calls){assert.deepEqual(JSON.parse(body.get('history')),memory);assert.deepEqual(body.getAll('document_ids'),['7']);}
});

test('web activity and sources reach the UI before answer text',async(t)=>{
 const events=[['tool_call',{id:'s1',server:'Web',tool:'google_search',title:'Searching the web',status:'running'}],['sources',{sources:[{title:'Official pricing',url:'https://ai.google.dev/pricing'}]}],['tool_call',{id:'s1',server:'Web',tool:'google_search',title:'Searched the web',status:'done'}],['delta',{text:'Answer'}],['done',{}]];
 t.mock.method(globalThis,'fetch',async()=>new Response(events.map(([name,data])=>`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}}));
 const received=[];
 await client().streamMessage('pricing',[],{onToolCall:c=>received.push(c.status),onSources:s=>received.push(s[0].url),onDelta:()=>received.push('answer')});
 assert.deepEqual(received,['running','https://ai.google.dev/pricing','done','answer']);
});

const webActivity = loadTypeScript('../lib/web-activity.ts');
test('web image attachments stream separately and keep image-search status', async(t)=>{
 const image={image_id:'a'.repeat(64),title:'Bridge',source_url:'https://commons.wikimedia.org/wiki/File:Bridge.jpg',url:'https://r2.example/signed',license:'CC BY-SA 4.0'};
 const events=[['web_images',{images:[image]}],['delta',{text:'Image found.'}],['done',{}]];
 t.mock.method(globalThis,'fetch',async()=>new Response(events.map(([name,data])=>`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}}));
 let received;
 await client().streamMessage('Show a bridge photo',[],{onDelta:()=>{},onWebImages:images=>received=images});
 assert.deepEqual(received,[image]);
 const [card]=webActivity.publicToolCalls([{id:'images1',server:'Web',tool:'image_search',title:'Searching web images',status:'running'}]);
 assert.equal(card.title,'Searching web images');
});
test('saved model-switch and quota diagnostics stay out of the account UI',()=>{
 const old=[{id:'web-backup',server:'Web',tool:'google_search',title:'Switching to Groq',status:'done',summary:'Gemini failed'}, {id:'web-search-unavailable',server:'Web',tool:'google_search',title:'Quota reached',status:'error'}];
 assert.deepEqual(webActivity.publicToolCalls(old,'hi'),[]);
 assert.deepEqual(webActivity.publicToolCalls(old,'Current pricing?'),[]);
});
test('web progress keeps queries but hides internal models and provider errors',()=>{
 const calls=[{id:'web-search',server:'Web',tool:'browser_search',title:'Trying web search · gpt-oss-120b',status:'running',summary:'Groq quota',arguments:{query:'Compare PDF with current data',model:'gpt-oss-120b'}}];
 const clean=webActivity.publicToolCalls(calls,'Compare PDF with latest data');
 assert.equal(clean[0].title,'Searching the web');
 assert.deepEqual(clean[0].arguments,{query:'Compare PDF with current data'});
 assert.doesNotMatch(JSON.stringify(clean),/Groq|gpt-oss/);
 const mcp={id:'mcp',server:'My notes',tool:'read',title:'Read note',status:'done'};
 assert.deepEqual(webActivity.publicToolCalls([mcp],'hi'),[mcp]);
});

const remarkCitations = loadTypeScript('../lib/markdown/remark-citations.ts').default;
test('citation markers become numbered superscripts, but not inside code or links', () => {
  const root = { type: 'root', children: [
    { type: 'paragraph', children: [text('BLEU was 28.4 [1][2].'), { type: 'inlineCode', value: 'arr[1]' },
      { type: 'link', url: 'https://x.example', children: [text('see [3]')] }] },
  ] };
  remarkCitations()(root);
  const nodes = root.children[0].children;
  assert.deepEqual(nodes.map((node) => node.type), ['text', 'citation', 'citation', 'text', 'inlineCode', 'link']);
  assert.equal(nodes[1].data.hProperties['data-citation'], '1');
  assert.equal(nodes[3].value, '.');
  assert.equal(nodes[4].value, 'arr[1]');
  assert.equal(nodes[5].children[0].value, 'see [3]');
});

test('the stream hands over the final answer and its checked citations', async (t) => {
  const citation = { n: 1, kind: 'web', title: 'Pricing', quote: 'costs $0.25', verified: true, url: 'https://x.example' };
  const events = [['delta', { text: 'It costs $0.25 [1].\n\n```citations\n[]\n```' }],
                  ['citations', { answer: 'It costs $0.25 [1].', citations: [citation] }], ['done', {}]];
  t.mock.method(globalThis, 'fetch', async () => new Response(events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
    { headers: { 'Content-Type': 'text/event-stream' } }));
  let final;
  await client().streamMessage('price', [], { onDelta: () => {}, onCitations: (answer, citations) => { final = { answer, citations }; } });
  assert.deepEqual(final, { answer: 'It costs $0.25 [1].', citations: [citation] });
});
