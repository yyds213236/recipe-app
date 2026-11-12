// 交互冒烟测试：CDP 驱动真实点击，校验 DOM 状态
const { spawn } = require('child_process');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9335;
const BASE = 'file:///Users/apple/Desktop/recipe-app/index.html';
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const chrome = spawn(CHROME, ['--headless=new','--hide-scrollbars','--remote-debugging-port='+PORT,
    '--user-data-dir=/tmp/rcp-test-profile','--no-first-run','about:blank'], { stdio: 'ignore' });
  let ver;
  for (let i=0;i<60;i++){ try{ ver = await (await fetch('http://127.0.0.1:'+PORT+'/json/version')).json(); break;}catch(e){await sleep(250);} }
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
  let id=0; const pending=new Map(); const logs=[];
  ws.onmessage = e => { const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result||m.error); pending.delete(m.id); }
    else if (m.method==='Runtime.exceptionThrown') logs.push('EXC '+JSON.stringify(m.params.exceptionDetails.text));
    else if (m.method==='Runtime.consoleAPICalled' && m.params.type==='error') logs.push('ERR '+m.params.args.map(a=>a.value).join(' '));
  };
  const send=(method,params={},sid)=>new Promise(res=>{const i=++id;pending.set(i,res);const m={id:i,method,params};if(sid)m.sessionId=sid;ws.send(JSON.stringify(m));});
  const { targetId } = await send('Target.createTarget',{url:'about:blank'});
  const { sessionId:S } = await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Runtime.enable',{},S);
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true},S);
  const ev = async (expr) => { const r = await send('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true},S);
    if (r.exceptionDetails) return { __err: r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception||{}).description };
    return r.result.value; };

  await send('Page.navigate',{url:BASE+'#/'},S); await sleep(900);
  await ev("localStorage.clear(); location.reload()"); await sleep(1000);

  const out = {};
  // 1) 搜索别名：西红柿 -> 番茄相关
  await ev("(()=>{const i=document.querySelector('#q')||document.querySelector('input[type=search]');i.focus();i.value='西红柿';i.dispatchEvent(new Event('input',{bubbles:true}));return 1})()");
  await sleep(400);
  out.searchAlias = await ev("JSON.stringify({cards:document.querySelectorAll('.card').length, first:(document.querySelector('.card-name')||{}).textContent})");
  // 清空搜索
  await ev("(()=>{const i=document.querySelector('input[type=search]');i.value='';i.dispatchEvent(new Event('input',{bubbles:true}));return 1})()");
  await sleep(300);

  // 2) 打开详情
  await ev("document.querySelector('.card').click()"); await sleep(600);
  out.detailOpen = await ev("JSON.stringify({sheet:!!document.querySelector('.sheet.show'), name:(document.querySelector('.sh-name')||{}).textContent, ingRows:document.querySelectorAll('.ing-row').length, steps:document.querySelectorAll('.step').length})");

  // 3) 勾选第一样食材
  await ev("document.querySelector('.ing-row').click()"); await sleep(200);
  out.ingChecked = await ev("JSON.stringify({progress:document.querySelector('#ing-progress').textContent, aria:document.querySelector('.ing-row').getAttribute('aria-checked')})");

  // 4) 步骤推进
  await ev("document.querySelector('#next-step').click()"); await sleep(400);
  out.stepAdvance = await ev("JSON.stringify({current:[...document.querySelectorAll('.step')].findIndex(s=>s.classList.contains('current')), doneCount:document.querySelectorAll('.step[data-done=\"1\"]').length})");
  await ev("document.querySelectorAll('.step-done')[1].click()"); await sleep(250);
  out.stepDone = await ev("JSON.stringify({done:document.querySelectorAll('.step[data-done=\"1\"]').length, label:document.querySelectorAll('.step-done')[1].textContent})");

  // 5) 计时器
  await ev("document.querySelector('#sh-timer').click()"); await sleep(300);
  await ev("document.querySelectorAll('.timer-presets .tbtn')[0].click()"); await sleep(200);
  await ev("document.querySelector('#t-start').click()"); await sleep(1200);
  out.timer = await ev("JSON.stringify({block:!document.querySelector('#timer-block').hidden, display:document.querySelector('#t-display').textContent, running:document.querySelector('#t-start').textContent})");
  await ev("document.querySelector('#t-reset').click()");

  // 6) 加入菜篮
  await ev("document.querySelector('#add-basket').click()"); await sleep(300);
  out.basket = await ev("JSON.stringify({label:document.querySelector('#add-basket').textContent.trim(), ls:localStorage.getItem('rcp.basket')})");
  await ev("document.querySelector('#sh-close').click()"); await sleep(400);

  // 7) 食材页多选 → 结果
  await ev("location.hash='#/pantry'"); await sleep(600);
  await ev("[...document.querySelectorAll('.ing')].slice(0,3).forEach(n=>n.click())"); await sleep(500);
  await ev("(()=>{const t=document.querySelector('#season-toggle');return 1})()");
  out.pantrySel = await ev("JSON.stringify({bar:document.querySelector('#ps')?document.querySelector('#ps').textContent.trim().slice(0,24):'', cta:document.querySelector('#go-result').textContent.replace(/\\s+/g,' ').trim()})");
  await ev("document.querySelector('#go-result').click()"); await sleep(700);
  out.result = await ev("JSON.stringify({hash:location.hash, groups:[...document.querySelectorAll('.res-group h3')].map(h=>h.textContent), stat:(document.querySelector('.result-head p')||{}).textContent.slice(0,40), missChips:document.querySelectorAll('.miss').length})");

  // 8) 调料开关
  const before = await ev("document.querySelectorAll('.miss').length");
  await ev("document.querySelector('#season-toggle').click()"); await sleep(500);
  out.seasonToggle = await ev("JSON.stringify({before:"+before+", after:document.querySelectorAll('.miss').length})");

  // 9) 合并采购清单 + 复制按钮存在
  await ev("location.hash='#/basket'"); await sleep(600);
  await ev("document.querySelector('#merge-btn').click()"); await sleep(500);
  out.shopping = await ev("JSON.stringify({lines:document.querySelectorAll('.shop-line').length, head:(document.querySelector('.shopping h4')||{}).textContent.slice(0,30), copy:!!document.querySelector('#copy-btn')})");

  // 10) 键盘 Esc / 斜杠
  await ev("location.hash='#/'"); await sleep(500);
  await ev("document.querySelector('.card').click()"); await sleep(500);
  await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"); await sleep(400);
  out.escClose = await ev("JSON.stringify({sheet:!!document.querySelector('.sheet.show')})");

  // 11) 手机视口无横向滚动
  out.noHScroll = await ev("JSON.stringify({doc:document.documentElement.scrollWidth+'/'+document.documentElement.clientWidth, widest:[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>391).length})");

  // 12) 触摸目标尺寸抽样
  out.tapTargets = await ev("JSON.stringify([...document.querySelectorAll('.tab,.ing,.card,.cat-tab,.step-done,.btn-primary,.icon-btn')].map(n=>Math.round(n.getBoundingClientRect().height)).filter(h=>h>0&&h<44).length)");

  console.log(JSON.stringify(out,null,1));
  console.log('console errors:', logs.length, logs.slice(0,5).join(' | '));
  ws.close(); chrome.kill(); process.exit(0);
})();
