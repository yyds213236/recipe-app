const { spawn } = require('child_process');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', PORT=9336;
const BASE='file:///Users/apple/Desktop/recipe-app/index.html';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const chrome=spawn(CHROME,['--headless=new','--hide-scrollbars','--remote-debugging-port='+PORT,'--user-data-dir=/tmp/rcp-p2','--no-first-run','about:blank'],{stdio:'ignore'});
 let ver; for(let i=0;i<60;i++){try{ver=await(await fetch('http://127.0.0.1:'+PORT+'/json/version')).json();break;}catch(e){await sleep(250);}}
 const ws=new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 let id=0;const p=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){p.get(m.id)(m.result||m.error);p.delete(m.id);}};
 const send=(mm,pp={},s)=>new Promise(res=>{const i=++id;p.set(i,res);const m={id:i,method:mm,params:pp};if(s)m.sessionId=s;ws.send(JSON.stringify(m));});
 const {targetId}=await send('Target.createTarget',{url:'about:blank'});
 const {sessionId:S}=await send('Target.attachToTarget',{targetId,flatten:true});
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true},S);
 const ev=async x=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true},S);return r.exceptionDetails?('ERR '+r.exceptionDetails.text+' '+((r.exceptionDetails.exception||{}).description||'')):r.result.value;};
 await send('Page.navigate',{url:BASE+'#/result?sel=tomato,egg,potato'},S); await sleep(1200);
 console.log('before', await ev("JSON.stringify({hash:location.hash, groups:document.querySelectorAll('.res-group').length, miss:document.querySelectorAll('.miss').length, head:(document.querySelector('.result-head p')||{}).textContent})"));
 console.log('toggle', await ev("(()=>{const t=document.querySelector('#season-toggle');t.click();return t.checked})()"));
 await sleep(600);
 console.log('after', await ev("JSON.stringify({hash:location.hash, groups:document.querySelectorAll('.res-group').length, miss:document.querySelectorAll('.miss').length, head:(document.querySelector('.result-head p')||{}).textContent, empty:document.querySelectorAll('.empty').length, sel:localStorage.getItem('rcp.sel')})"));
 ws.close(); chrome.kill(); process.exit(0);
})();
