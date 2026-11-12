const { spawn } = require('child_process');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', PORT=9338;
const BASE='file:///Users/apple/Desktop/recipe-app/index.html';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const chrome=spawn(CHROME,['--headless=new','--hide-scrollbars','--remote-debugging-port='+PORT,'--user-data-dir=/tmp/rcp-key','--no-first-run','about:blank'],{stdio:'ignore'});
 let ver; for(let i=0;i<60;i++){try{ver=await(await fetch('http://127.0.0.1:'+PORT+'/json/version')).json();break;}catch(e){await sleep(250);}}
 const ws=new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 let id=0;const p=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){p.get(m.id)(m.result||m.error);p.delete(m.id);}};
 const send=(mm,pp={},s)=>new Promise(res=>{const i=++id;p.set(i,res);const m={id:i,method:mm,params:pp};if(s)m.sessionId=s;ws.send(JSON.stringify(m));});
 const {targetId}=await send('Target.createTarget',{url:'about:blank'});
 const {sessionId:S}=await send('Target.attachToTarget',{targetId,flatten:true});
 await send('Page.navigate',{url:BASE},S); await sleep(1200);
 const ev=async x=>(await send('Runtime.evaluate',{expression:x,returnByValue:true},S)).result.value;
 console.log('slash focus ->', await ev(`(()=>{document.body.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'/',code:'Slash',bubbles:true}));const a=document.activeElement;return a.tagName+'#'+(a.id||'');})()`));
 await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]},S);
 await sleep(300);
 console.log('dark mode ->', await ev(`(()=>{return 'bg='+getComputedStyle(document.body).backgroundColor+' card='+getComputedStyle(document.querySelector('.card')).backgroundColor+' ink='+getComputedStyle(document.body).color;})()`));
 ws.close(); chrome.kill(); process.exit(0);
})();
