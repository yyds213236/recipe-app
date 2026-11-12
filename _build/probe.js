const { spawn } = require('child_process');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9334;
const BASE = 'file:///Users/apple/Desktop/recipe-app/index.html';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const chrome = spawn(CHROME, ['--headless=new','--hide-scrollbars','--remote-debugging-port='+PORT,
    '--user-data-dir=/tmp/rcp-probe-profile','--no-first-run','about:blank'], { stdio: 'ignore' });
  let ver;
  for (let i=0;i<60;i++){ try{ ver = await (await fetch('http://127.0.0.1:'+PORT+'/json/version')).json(); break;}catch(e){await sleep(250);} }
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res,rej)=>{ws.onopen=res;ws.onerror=rej;});
  let id=0; const pending=new Map();
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result||m.error); pending.delete(m.id);} };
  const send=(method,params={},sid)=>new Promise(res=>{const i=++id;pending.set(i,res);const m={id:i,method,params};if(sid)m.sessionId=sid;ws.send(JSON.stringify(m));});
  const { targetId } = await send('Target.createTarget',{url:'about:blank'});
  const { sessionId } = await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true},sessionId);
  await send('Page.navigate',{url:BASE+'#/pantry?sel=tomato,egg'},sessionId);
  await sleep(1200);
  const r = await send('Runtime.evaluate',{expression:`(()=>{const c=document.querySelector('.pantry-cta'),t=document.querySelector('.tabbar'),v=document.querySelector('#view');
  const cb=c.getBoundingClientRect(),tb=t.getBoundingClientRect();
  return JSON.stringify({cta:[cb.top,cb.bottom,cb.height],tab:[tb.top,tb.bottom],ctaBg:getComputedStyle(c).backgroundImage.slice(0,90),viewPad:getComputedStyle(v).paddingBottom,tap:getComputedStyle(document.documentElement).getPropertyValue('--tap')});})()`,returnByValue:true},sessionId);
  console.log(r.result.value);
  ws.close(); chrome.kill(); process.exit(0);
})();
