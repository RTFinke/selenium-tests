import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
const work=path.resolve('output/siz3r-mail-footer-work'),dest=path.resolve('output/siz3r-mail-z-naglowkiem');
const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--hide-scrollbars','--disable-gpu','--no-first-run','--remote-debugging-port=9298',`--user-data-dir=${path.join(work,'chrome-profile')}`],{windowsHide:true,stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let ws;
try{
 let info;for(let i=0;i<100;i++){try{info=await(await fetch('http://127.0.0.1:9298/json/version')).json();break;}catch{await sleep(100);}}
 if(!info)throw Error('No Chrome');ws=new WebSocket(info.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 let seq=0;const pending=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){const{r,j}=pending.get(m.id);pending.delete(m.id);m.error?j(Error(JSON.stringify(m.error))):r(m.result);}};
 const call=(method,params={},sessionId)=>new Promise((r,j)=>{const id=++seq;pending.set(id,{r,j});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
 const{targetId}=await call('Target.createTarget',{url:'about:blank'});const{sessionId}=await call('Target.attachToTarget',{targetId,flatten:true});
 const c=(method,params={})=>call(method,params,sessionId);await c('Page.enable');await c('Runtime.enable');await c('Network.enable');
 const results=[];
 for(const[mode,width,name]of[['light',900,'Podglad_desktop.png'],['light',390,'Podglad_mobile.png'],['light',320,'Podglad_mobile_320.png'],['dark',390,'Symulacja_dark_mobile.png'],['blocked',390,'Podglad_bez_obrazow.png']]){
  await c('Network.setBlockedURLs',{urls:mode==='blocked'?['*framerusercontent.com*']:[]});await c('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
  await c('Page.navigate',{url:pathToFileURL(path.join(dest,'Siz3r_Oferta_podglad.html')).href});
  for(let i=0;i<100;i++){const r=await c('Runtime.evaluate',{expression:'document.readyState === "complete"',returnByValue:true});if(r.result.value)break;await sleep(100);}
  if(mode==='dark')await c('Runtime.evaluate',{expression:`(()=>{const content=document.body.innerHTML;document.body.removeAttribute('class');document.body.innerHTML='<u style="display:none"></u><div class="siz3r-body">'+content+'</div>';document.body.style.backgroundColor='#202124';for(const e of document.querySelectorAll('[style]')){const s=e.style;if(s.color==='rgb(9, 9, 11)')s.color='#F1F3F4';if(s.color==='rgb(107, 114, 128)')s.color='#A6ADB8';if(s.backgroundColor==='rgb(255, 255, 255)')s.backgroundColor='#202124';if(s.backgroundColor==='rgb(0, 230, 118)')s.backgroundColor='#075923';if(s.backgroundColor==='rgb(228, 228, 231)')s.backgroundColor='#353539';}})()`});
  await c('Runtime.evaluate',{expression:'Promise.all(Array.from(document.images,i=>i.decode().catch(()=>null))).then(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))',awaitPromise:true});
  const r=await c('Runtime.evaluate',{returnByValue:true,expression:`(()=>{const rect=id=>document.getElementById(id).getBoundingClientRect(),line=rect('siz3r-footer-line'),text=rect('siz3r-footer-text'),card=rect('siz3r-email'),signature=rect('siz3r-signature'),button=rect('siz3r-cta');return{height:document.documentElement.scrollHeight,scrollWidth:document.documentElement.scrollWidth,lineToText:text.top-line.bottom,signatureToLine:line.top-signature.bottom,textToCardBottom:card.bottom-text.bottom,buttonWidth:button.width,buttonWeight:getComputedStyle(document.getElementById('siz3r-cta')).fontWeight}})()`});
  const m={mode,width,...r.result.value};if(m.lineToText!==24||m.signatureToLine!==40||m.textToCardBottom!==40||m.scrollWidth>width||m.buttonWidth!==Math.min(width,600)-80||m.buttonWeight!=='700')throw Error(JSON.stringify(m));results.push(m);
  const shot=await c('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width,height:m.height,scale:1}});fs.writeFileSync(path.join(dest,name),Buffer.from(shot.data,'base64'));
 }
 fs.writeFileSync(path.join(work,'metrics.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));await call('Browser.close');
}finally{if(ws)ws.close();browser.kill();}
