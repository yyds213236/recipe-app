const { spawn } = require('child_process');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9345;
const url = 'file:///Users/apple/Desktop/recipe-app/_build/audit.html';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const chrome = spawn(CHROME, ['--headless=new','--disable-gpu','--hide-scrollbars','--remote-debugging-port='+PORT,'--user-data-dir=/tmp/rcp-audit','--no-first-run','--no-default-browser-check','--allow-file-access-from-files','about:blank'], {stdio:'ignore'});
  let ver;
  for (let i=0;i<60;i++){ try{ ver = await (await fetch('http://127.0.0.1:'+PORT+'/json/version')).json(); break; }catch(e){ await sleep(250); } }
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  let id=0; const pend=new Map(); const evs=[];
  ws.onmessage = e => { const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){const p=pend.get(m.id);pend.delete(m.id);m.error?p.j(new Error(JSON.stringify(m.error))):p.r(m.result);} else if(m.method) evs.push(m); };
  const send=(method,params,sessionId)=>new Promise((r,j)=>{const mm={id:++id,method,params:params||{}}; if(sessionId)mm.sessionId=sessionId; pend.set(mm.id,{r,j}); ws.send(JSON.stringify(mm));});
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId:S}=await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Page.enable',{},S); await send('Runtime.enable',{},S);
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:1200,deviceScaleFactor:1,mobile:false},S);
  await send('Page.navigate',{url},S);
  await sleep(3500);
  const h=(await send('Runtime.evaluate',{expression:'document.body.scrollHeight',returnByValue:true},S)).result.value;
  const n=Math.ceil(h/1150);
  for(let i=0;i<n;i++){
    const shot=await send('Page.captureScreenshot',{format:'png',clip:{x:0,y:i*1150,width:1100,height:Math.min(1150,h-i*1150),scale:1},captureBeyondViewport:true},S);
    fs.writeFileSync('/Users/apple/Desktop/recipe-app/_build/audit-'+String(i).padStart(2,'0')+'.png',Buffer.from(shot.data,'base64'));
  }
  console.log('height',h,'pages',n);
  ws.close(); chrome.kill();
})();
