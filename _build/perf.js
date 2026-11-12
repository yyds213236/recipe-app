const { spawn } = require('child_process');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', PORT=9337;
const BASE='file:///Users/apple/Desktop/recipe-app/index.html';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const chrome=spawn(CHROME,['--headless=new','--hide-scrollbars','--remote-debugging-port='+PORT,'--user-data-dir=/tmp/rcp-perf','--no-first-run','about:blank'],{stdio:'ignore'});
 let ver; for(let i=0;i<60;i++){try{ver=await(await fetch('http://127.0.0.1:'+PORT+'/json/version')).json();break;}catch(e){await sleep(250);}}
 const ws=new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 let id=0;const p=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){p.get(m.id)(m.result||m.error);p.delete(m.id);}};
 const send=(mm,pp={},s)=>new Promise(res=>{const i=++id;p.set(i,res);const m={id:i,method:mm,params:pp};if(s)m.sessionId=s;ws.send(JSON.stringify(m));});
 const {targetId}=await send('Target.createTarget',{url:'about:blank'});
 const {sessionId:S}=await send('Target.attachToTarget',{targetId,flatten:true});
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true},S);
 await send('Page.navigate',{url:BASE},S); await sleep(1500);
 const r = await send('Runtime.evaluate',{expression:`(()=>{const t=performance.getEntriesByType('navigation')[0];
 return JSON.stringify({dcl:Math.round(t.domContentLoadedEventEnd), load:Math.round(t.loadEventEnd), paint:Math.round((performance.getEntriesByName('first-contentful-paint')[0]||{}).startTime||0), res:performance.getEntriesByType('resource').map(r=>r.name.split('/').pop()+':'+Math.round(r.duration))});})()`,returnByValue:true},S);
 console.log(r.result.value);
 // 交互流畅度：连续点 5 个食材，测 frame 间隔（用 rAF 采样时长）
 const jank = await send('Runtime.evaluate',{expression:`new Promise(res=>{const t=[];let last=performance.now();let n=0;function f(ts){t.push(ts-last);last=ts;if(++n<40)requestAnimationFrame(f);else res(JSON.stringify({frames:t.length,max:Math.round(Math.max(...t)),avg:+(t.reduce((a,b)=>a+b,0)/t.length).toFixed(1)}));}requestAnimationFrame(f);})`,awaitPromise:true,returnByValue:true},S);
 console.log('frames', jank.result.value);
 ws.close(); chrome.kill(); process.exit(0);
})();
