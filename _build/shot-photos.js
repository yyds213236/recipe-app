// 用 CDP 精确截 390×844 视口图，并收集控制台错误
const { spawn } = require('child_process');
const fs = require('fs');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const BASE = 'file:///Users/apple/Desktop/recipe-app/index.html';
const OUT = '/Users/apple/Desktop/recipe-app/_shots';

const SHOTS = [
  { name: 'photos-home.png', hash: '#/', w: 390, h: 844 },
  { name: 'photos-detail.png', hash: '#/recipe/tomato-egg', w: 390, h: 844 },
  { name: 'photos-pantry.png', hash: '#/pantry?sel=tomato,egg,scallion', w: 390, h: 844 },
  { name: 'photos-credits.png', hash: '#/credits', w: 390, h: 844 },
  { name: 'photos-result.png', hash: '#/result?sel=tomato,egg,potato', w: 390, h: 844 }
];

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=/tmp/rcp-chrome-profile',
    '--no-first-run', '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' });

  let ver;
  for (let i = 0; i < 60; i++) {
    try {
      ver = await (await fetch('http://127.0.0.1:' + PORT + '/json/version')).json();
      break;
    } catch (e) { await sleep(250); }
  }
  if (!ver) throw new Error('chrome 未启动');

  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  const events = [];
  const logs = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
    } else if (msg.method) {
      events.push(msg);
      if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        logs.push('EXCEPTION: ' + (d.exception && d.exception.description || d.text));
      }
      if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        logs.push('CONSOLE ERROR: ' + msg.params.args.map(a => a.value || a.description || '').join(' '));
      }
      if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
        logs.push('LOG ERROR: ' + msg.params.entry.text + ' ' + (msg.params.entry.url || ''));
      }
    }
  };
  const send = (method, params, sessionId) => new Promise((res, rej) => {
    const m = { id: ++id, method, params: params || {} };
    if (sessionId) m.sessionId = sessionId;
    pending.set(m.id, { res, rej });
    ws.send(JSON.stringify(m));
  });

  // 建一个 page target 并 attach
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const S = sessionId;
  await send('Page.enable', {}, S);
  await send('Runtime.enable', {}, S);
  await send('Log.enable', {}, S);
  await send('Network.enable', {}, S);

  async function waitLoad() {
    for (let i = 0; i < 80; i++) {
      const found = events.some(e => e.method === 'Page.loadEventFired' && e.sessionId === S);
      if (found) return;
      await sleep(100);
    }
  }

  await send('Page.navigate', { url: BASE + '#/' }, S);
  await waitLoad();
  await sleep(300);
  await send('Runtime.evaluate', { expression: 'localStorage.clear(); location.reload();' }, S);
  await sleep(600);
  await waitLoad();

  for (const shot of SHOTS) {
    events.length = 0;
    await send('Emulation.setDeviceMetricsOverride', {
      width: shot.w, height: shot.h, deviceScaleFactor: 2, mobile: shot.w < 700
    }, S);
    await send('Page.navigate', { url: BASE + shot.hash }, S);
    await waitLoad();
    await sleep(650);
    if (shot.js) {
      const r = await send('Runtime.evaluate', { expression: shot.js, returnByValue: true, awaitPromise: true }, S);
      if (r.exceptionDetails) console.log('JS ERR', shot.name, r.exceptionDetails.text);
      await sleep(350);
    }
    // 触发一次重排/动画完成
    const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, S);
    fs.writeFileSync(OUT + '/' + shot.name, Buffer.from(data, 'base64'));
    console.log('shot', shot.name, shot.w + 'x' + shot.h);
  }

  // 额外检查：横向滚动
  const probe = await send('Runtime.evaluate', {
    expression: `(function(){
      var de=document.documentElement;
      return JSON.stringify({
        scrollW: de.scrollWidth, clientW: de.clientWidth,
        bodyScrollW: document.body.scrollWidth,
        tabs: document.querySelectorAll('.tab').length,
        cards: document.querySelectorAll('.card,.res-card').length,
        imgs: document.querySelectorAll('img').length,
        broken: Array.from(document.querySelectorAll('img')).filter(function(i){return i.complete && i.naturalWidth === 0}).length,
        remote: Array.from(document.querySelectorAll('img')).filter(function(i){return /^https?:/.test(i.getAttribute('src')||'')}).map(function(i){return i.src}).slice(0,5),
        cardPhoto: document.querySelectorAll('.card-photo').length,
        title: document.title
      });
    })()`,
    returnByValue: true
  }, S);
  console.log('probe', probe.result.value);

  console.log('--- console errors (' + logs.length + ') ---');
  logs.slice(0, 20).forEach(l => console.log(l));

  ws.close();
  chrome.kill();
  process.exit(0);
}

main().catch(e => { console.error('FAIL', e); process.exit(1); });
