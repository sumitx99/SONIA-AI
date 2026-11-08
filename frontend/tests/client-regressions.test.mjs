import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const realRequire = createRequire(import.meta.url);
function loadTypeScript(path, imports = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { fileName: path, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((name) => imports[name] ?? realRequire(name), module, module.exports);
  return module.exports;
}
const noImages = loadTypeScript('../lib/markdown/remark-no-images.ts').default;
const { isImageUrl } = loadTypeScript('../lib/markdown/image-url.ts');
const image = () => ({ type: 'image', url: 'invented.png', alt: 'Figure 1' });
const text = (value) => ({ type: 'text', value });

test('only standard image URLs are accepted for generated_images events', () => {
  assert.equal(isImageUrl('https://i0.nekobot.xyz/4/d/b/1d7493e0bceea91f53406738e9065.jpg'), true);
  assert.equal(isImageUrl('https://cdn.example.test/generated.webp?token=x'), true);
  assert.equal(isImageUrl('https://example.test/article'), false);
  assert.equal(isImageUrl('javascript:alert(1)'), false);
});

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

test('Stop interrupts auth waiting before an answer request is sent', { timeout: 1000 }, async (t) => {
  let finishAuth;
  let fetched = false;
  const api = client({ getSession: () => new Promise(resolve => { finishAuth = resolve; }) });
  t.mock.method(globalThis, 'fetch', async () => { fetched = true; });
  const controller = new AbortController();
  const request = api.streamMessage('Explain this', [], { onDelta() {} }, [], controller.signal);
  controller.abort();
  await assert.rejects(request, { name: 'AbortError' });
  finishAuth({ data: { session: { access_token: 'token' } } });
  await Promise.resolve();
  assert.equal(fetched, false);
});

for (const partial of ['', 'The BLEU score is ']) {
  test(`Stop releases an idle stream ${partial ? 'after partial text' : 'before any text'} without waiting for transport cleanup`, { timeout: 1000 }, async (t) => {
    let waiting;
    const idle = new Promise(resolve => { waiting = resolve; });
    let reads = 0;
    let cancelled = false;
    const reader = {
      read: () => {
        if (partial && reads++ === 0) return Promise.resolve({ value: `event: delta\ndata: ${JSON.stringify({ text: partial })}\n\n`, done: false });
        waiting();
        return new Promise(() => {});
      },
      cancel: () => { cancelled = true; return new Promise(() => {}); },
      releaseLock() {},
    };
    t.mock.method(globalThis, 'fetch', async () => ({ ok: true, status: 200, body: { pipeThrough: () => ({ getReader: () => reader }) } }));
    const text = [];
    const controller = new AbortController();
    const request = client().streamMessage('Explain this', [7], { onDelta: piece => text.push(piece) }, [], controller.signal);
    await idle;
    controller.abort();
    await assert.rejects(request, { name: 'AbortError' });
    assert.equal(cancelled, true);
    assert.equal(text.join(''), partial);
  });
}

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

test('an upload still running elsewhere is waited for without using up the normal retries', async (t) => {
  const calls = [];
  const waits = [];
  const timer = globalThis.setTimeout;
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => { if (ms !== 180_000) waits.push(ms); return timer(fn, ms === 180_000 ? ms : 0, ...args); });
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push(init.body);
    if (calls.length <= 3) return new Response(JSON.stringify({ detail: 'Still processing' }), { status: 409, headers: { 'Retry-After': '30' } });
    if (calls.length <= 5) return response(503, { detail: 'Starting' });
    return response(200, { file_id: 7, images_status: 'processing' });
  });
  const result = await client().uploadPDF(new File(['%PDF-demo'], 'demo.pdf'), 'chat-1');
  assert.equal(result.file_id, 7);
  assert.equal(calls.length, 6);
  assert.deepEqual(waits.slice(0, 3), [30_000, 30_000, 30_000]);
  assert.equal(new Set(calls.map((body) => body.get('request_id'))).size, 1);
});

test('image status is polled until background processing finishes', async (t) => {
  const timer = globalThis.setTimeout;
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => timer(fn, 0, ...args));
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url) => {
    urls.push(url);
    if (urls.length === 1) return response(200, { images_status: 'processing', images_stored: 0 });
    if (urls.length === 2) return response(502, { detail: 'Restarting' });
    return response(200, { images_status: 'ready', images_stored: 52 });
  });
  const status = await client().waitForDocumentImages(7);
  assert.deepEqual(status, { images_status: 'ready', images_stored: 52 });
  assert.equal(urls.length, 3);
  assert.match(urls[0], /\/documents\/7\/status$/);
});

test('waiting for images stops when the document no longer exists', async (t) => {
  const timer = globalThis.setTimeout;
  t.mock.method(globalThis, 'setTimeout', (fn, ms, ...args) => timer(fn, 0, ...args));
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return response(404, { detail: 'Document not found' }); });
  assert.deepEqual(await client().waitForDocumentImages(7), { images_status: null, images_stored: 0 });
  assert.equal(calls, 1);
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

test('an SSE error after partial text is reported as a cut-off answer', async(t)=>{
 const events=[['delta',{text:'Partial answer'}],['error',{detail:'The answer reached its output limit.'}]];
 t.mock.method(globalThis,'fetch',async()=>new Response(events.map(([name,data])=>`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}}));
 let answer='';
 const result=await client().streamMessage('question',[],{onDelta:piece=>answer+=piece});
 assert.equal(answer,'Partial answer');
 assert.deepEqual(result,{cutOff:true});
});

const webActivity = loadTypeScript('../lib/web-activity.ts');
test('web image attachments stream separately and keep image-search status', async(t)=>{
 const image={image_id:'a'.repeat(64),title:'Bridge',source_url:'https://commons.wikimedia.org/wiki/File:Bridge.jpg',url:'https://r2.example/signed',license:'CC BY-SA 4.0'};
 const generated={src:'https://images.example.test/generated.webp',alt:'Generated image'};
 const events=[['web_images',{images:[image]}],['generated_images',{images:[generated]}],['delta',{text:'Image found.'}],['done',{}]];
 t.mock.method(globalThis,'fetch',async()=>new Response(events.map(([name,data])=>`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}}));
 let received, receivedGenerated;
 await client().streamMessage('Show a bridge photo',[],{onDelta:()=>{},onWebImages:images=>received=images,onGeneratedImages:images=>receivedGenerated=images});
 assert.deepEqual(received,[image]);
 assert.deepEqual(receivedGenerated,[generated]);
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

const { ToolCalls } = loadTypeScript('../components/chat/tool-calls.tsx', {
  '@/lib/web-activity': webActivity,
  '@/lib/api': { decideToolCall: async () => {}, handleApiError: String },
  './tool-activity.module.css': { default: new Proxy({}, { get: (_, key) => String(key) }) },
});
const renderActivity = (calls, streaming = false) => realRequire('react-dom/server').renderToStaticMarkup(
  realRequire('react').createElement(ToolCalls, { calls, streaming }));
const jobStep = { id: 'jobs-1', server: 'JSearch Jobs', tool: 'Job_Search', title: 'Job_Search',
  status: 'running', arguments: { query: 'software developer jobs in Mohali' } };

test('activity follows real tool lifecycle and keeps JSON inside collapsed Details', () => {
  const running = renderActivity([jobStep], true);
  assert.match(running, /Using Job Search/);
  assert.match(running, /JSearch Jobs/);
  assert.match(running, /In progress/);
  assert.match(running, /<ol/);
  assert.match(running, /<details[^>]*open=""/);
  assert.match(running, /<summary[^>]*>Activity <svg/);
  assert.match(running, /<details[^>]*><summary>Details/);
  assert.doesNotMatch(running, /Preparing answer|MCP ·|>Running</);
  const done = { ...jobStep, status: 'done' };
  assert.match(renderActivity([done], true), /Complete.*Preparing answer/s);
  assert.doesNotMatch(renderActivity([done], false), /Preparing answer/);
  assert.doesNotMatch(renderActivity([done, { ...jobStep, id: 'jobs-2' }], true), /Preparing answer/);
});

test('image URL remains activity text and is not rendered as an image from Details', () => {
  const url = 'https://i0.nekobot.xyz/4/d/b/1d7493e0bceea91f53406738e9065.jpg';
  const rendered = renderActivity([{ id: 'image-tool', server: 'Generator', tool: 'generate', title: 'Generate image',
    status: 'done', summary: `{"success":true,"url":"${url}"}` }]);
  assert.ok(rendered.includes(url));
  assert.doesNotMatch(rendered, /<img/);
});

test('activity distinguishes approval, failure, decline and stop without fake success', () => {
  const approval = renderActivity([{ ...jobStep, status: 'awaiting_approval' }], true);
  assert.match(approval, /Waiting for you/);
  assert.match(approval, /Deny/);
  assert.match(approval, /Allow/);
  assert.doesNotMatch(approval, /Preparing answer/);
  for (const [status, label] of [['error', 'Failed'], ['denied', 'Declined'], ['stopped', 'Stopped']]) {
    const rendered = renderActivity([{ ...jobStep, status }]);
    assert.match(rendered, new RegExp(label));
    assert.doesNotMatch(rendered, /Preparing answer|>Complete</);
  }
  const stoppedWeb = webActivity.publicToolCalls([{ ...jobStep, server: 'Web', status: 'stopped' }]);
  assert.equal(stoppedWeb[0].title, 'Web search stopped');
  assert.match(renderActivity([], true), /Activity.*Preparing answer/s);
  assert.equal(renderActivity([], false), '');
});

const remarkCitations = loadTypeScript('../lib/markdown/remark-citations.ts').default;
const { applyInlineGroundingCitations } = loadTypeScript('../lib/markdown/inline-grounding.ts');

test('grounding annotations become inline source links at UTF-16 answer offsets', () => {
  const answer = '💼 Zscaler offers hybrid roles.';
  const position = answer.length;
  const linked = applyInlineGroundingCitations(answer, [
    { position, title: 'Zscaler careers', url: 'https://zscaler.example/careers' },
    { position, title: 'Zscaler careers', url: 'https://zscaler.example/careers' },
  ]);
  assert.equal(linked, '💼 Zscaler offers hybrid roles. [↗](<https://zscaler.example/careers> "sonia-grounding:Zscaler%20careers")');
  assert.equal(applyInlineGroundingCitations(answer, [
    { position, title: 'Unsafe', url: 'javascript:alert(1)' },
  ]), answer);
});

test('grounding source title is available on hover and keyboard focus', () => {
  const renderer = readFileSync(new URL('../components/chat/markdown-message.tsx', import.meta.url), 'utf8');
  const styles = readFileSync(new URL('../components/chat/citation-marker.module.css', import.meta.url), 'utf8');
  assert.match(renderer, /data-source-title=\{sourceTitle\}/);
  assert.match(styles, /\.groundingLink:hover::after,\s*\.groundingLink:focus-visible::after/);
  assert.match(styles, /content:\s*attr\(data-source-title\)/);
});

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
  const inline = { position: 20, title: 'Pricing page', url: 'https://x.example/pricing' };
  const events = [['delta', { text: 'It costs $0.25 [1].\n\n```citations\n[]\n```' }],
                  ['inline_citation', inline],
                  ['citations', { answer: 'It costs $0.25 [1].', citations: [citation] }], ['done', {}]];
  t.mock.method(globalThis, 'fetch', async () => new Response(events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
    { headers: { 'Content-Type': 'text/event-stream' } }));
  let final;
  let streamedInline;
  await client().streamMessage('price', [], { onDelta: () => {}, onInlineCitation: (value) => { streamedInline = value; },
    onCitations: (answer, citations) => { final = { answer, citations }; } });
  assert.deepEqual(final, { answer: 'It costs $0.25 [1].', citations: [citation] });
  assert.deepEqual(streamedInline, inline);
});
