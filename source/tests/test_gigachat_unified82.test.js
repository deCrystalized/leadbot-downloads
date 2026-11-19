'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создатьИИ}=require('../extension-server/brain/ai');
const {создатьСервер,внутреннийДоступ}=require('../extension-server/vps/brain_http');
const {создать}=require('../extension-server/brain/index');
const {parseCandidate}=require('../extension-server/brain/assistant');
const response=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>data});
function aiFixture(extra={}){
 const calls=[],charges=[],memory=new Map();
 const ai=создатьИИ({env:{GIGACHAT_KEY:'synthetic-not-a-key'},
  cache:{взять:async k=>memory.get(k),положить:async(k,v)=>memory.set(k,v)},
  budget:{доступ:async()=>({можно:true,free:true}),записать:x=>{charges.push(x);return 0}},
  запрос:async(url,o)=>{calls.push({url,o});if(url.includes('/oauth'))return response({access_token:'synthetic-token',expires_at:Math.floor(Date.now()/1000)+1800});
   return response({choices:[{message:{content:'{"reply":"Подскажите модель?","needs_operator":false}'},finish_reason:'stop'}],usage:{prompt_tokens:20,completion_tokens:10}})},
  ...extra});
 return{ai,calls,charges};
}
test('current GigaChat URL, OAuth scope and verified TLS are used with actual API shapes',async()=>{
 const f=aiFixture();const r=await f.ai.спросить('assistant','system','task',{singleAttempt:true});
 assert.equal(r.model,'GigaChat-2-Pro');assert.equal(f.calls.length,2);
 assert.equal(f.calls[0].url,'https://ngw.devices.sberbank.ru:9443/api/v2/oauth');
 assert.equal(f.calls[0].o.body,'scope=GIGACHAT_API_PERS');assert.match(f.calls[0].o.headers.RqUID,/^[a-f0-9-]{36}$/);
 assert.equal(f.calls[1].url,'https://api.giga.chat/v1/chat/completions');
 assert.match(f.calls[1].o.ca,/BEGIN CERTIFICATE/);assert.equal(f.calls[1].o.rejectUnauthorized,undefined);
 assert.deepEqual(f.charges.filter(x=>!x.hit).map(x=>[x.inTok,x.outTok]),[[20,10]]);
 await f.ai.спросить('assistant','system','another task',{singleAttempt:true});
 assert.equal(f.calls.filter(x=>x.url.includes('/oauth')).length,1,'seconds expiry must remain cached');
});
test('parallel distinct dialogs share one OAuth refresh, equal turns share one generation',async()=>{
 const f=aiFixture();await Promise.all(Array.from({length:10},(_,i)=>f.ai.спросить('assistant','system','task'+i,{singleAttempt:true})));
 assert.equal(f.calls.filter(x=>x.url.includes('/oauth')).length,1);
 const before=f.calls.length;await Promise.all(Array.from({length:10},()=>f.ai.спросить('assistant','system','same',{singleAttempt:true})));
 assert.equal(f.calls.length-before,1);
});
test('internal completion route refuses forwarded or nonlocal callers even with the token',()=>{
 const req=(address,headers)=>({socket:{remoteAddress:address},headers});
 assert.equal(внутреннийДоступ(req('127.0.0.1',{'x-leadbot-token':'secret'}),'secret'),true);
 for(const [address,headers] of [['1.2.3.4',{'x-leadbot-token':'secret'}],['127.0.0.1',{'x-leadbot-token':'secret','x-forwarded-for':'1.2.3.4'}],['127.0.0.1',{}],['127.0.0.1',{'x-leadbot-token':'секрет'}]])
  assert.equal(внутреннийДоступ(req(address,headers),'secret'),false);
});
test('actual HTTP broker authenticates before generation and never exposes a public op',async t=>{
 const prev=process.env.LEADBOT_SERVICE_TOKEN;process.env.LEADBOT_SERVICE_TOKEN='synthetic-internal-token';
 t.after(()=>{if(prev===undefined)delete process.env.LEADBOT_SERVICE_TOKEN;else process.env.LEADBOT_SERVICE_TOKEN=prev});
 let calls=0;const server=создатьСервер({handler:async()=>({statusCode:404,body:'{}'}),completeLegacy:async args=>{calls++;assert.equal(args.task,'task');return{ok:true,text:'{}',auto_enabled:false}}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r)}));
 const url='http://127.0.0.1:'+server.address().port+'/internal/leadbot/completion';
 const send=headers=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify({task:'task'})});
 assert.equal((await send({})).status,403);assert.equal(calls,0);
 assert.equal((await send({'X-Leadbot-Token':'synthetic-internal-token','X-Forwarded-For':'1.2.3.4'})).status,403);assert.equal(calls,0);
 const r=await send({'X-Leadbot-Token':'synthetic-internal-token'});assert.equal(r.status,200);assert.equal((await r.json()).auto_enabled,false);assert.equal(calls,1);
});
test('legacy generation uses the same model budget and cache as extension requests',async()=>{
 const objects=new Map(),calls=[];
 const brain=создать({env:{GIGACHAT_KEY:'synthetic-key'},store:{get:async(k,d)=>structuredClone(objects.get(k)||d),put:async(k,v)=>objects.set(k,structuredClone(v))},log:()=>{},
 запрос:async(url,o)=>{calls.push(url);if(url.includes('/oauth'))return response({access_token:'token',expires_at:Date.now()+1800000});
  return response({choices:[{message:{content:'{"reply":"Модель подскажите?"}'},finish_reason:'stop'}],usage:{prompt_tokens:12,completion_tokens:8}})}});
 const args={system:'system',task:'task',max_tokens:350};
 const out=await brain.completeLegacy(args);assert.equal(out.model,'GigaChat-2-Pro');assert.equal(out.auto_enabled,false);
 assert.ok([...objects.keys()].some(k=>k.startsWith('brain/usage/')));
 const n=calls.length;assert.equal((await brain.completeLegacy(args)).cached,true);assert.equal(calls.length,n);
 await assert.rejects(brain.completeLegacy({...args,max_tokens:100000}),/контракт/);
});

test('a corrected format validator reuses the original rejected response without a provider retry',async()=>{
 const memory=new Map(),calls=[],charges=[],logs=[];
 const raw='{"reply":"Материал стены подскажите?","needs_operator":False}';
 const ai=создатьИИ({env:{GIGACHAT_KEY:'synthetic-not-a-credential'},
  cache:{взять:async k=>memory.get(k),положить:async(k,v)=>memory.set(k,{...v,at:Date.now()})},
  budget:{доступ:async()=>({можно:true,free:true}),записать:x=>{charges.push(x);return 0}},
  log:x=>logs.push(x),запрос:async(url)=>{calls.push(url);return response(url.includes('/oauth')
   ? {access_token:'synthetic-token',expires_at:Date.now()+1800000}
   : {choices:[{message:{content:raw},finish_reason:'stop'}],usage:{prompt_tokens:20,completion_tokens:10}});}});
 const strict=t=>{try{return !!JSON.parse(t);}catch{return false;}};
 await assert.rejects(ai.спросить('assistant','same system','same task',{singleAttempt:true,годен:strict}),e=>!!e.неПоФорме);
 const before=calls.length;
 const reused=await ai.спросить('assistant','same system','same task',{singleAttempt:true,годен:t=>!!parseCandidate(t)});
 assert.equal(reused.cached,true);assert.equal(reused.text,raw);assert.equal(reused.model,'GigaChat-2-Pro');assert.equal(calls.length,before);
 assert.equal(charges.filter(x=>!x.hit).length,1);assert.ok(logs.some(x=>x.recovered_format===true));
 await assert.rejects(ai.спросить('assistant','same system','same task',{singleAttempt:true,годен:strict}),e=>!!e.неПоФорме&&!!e.кэш);
 assert.equal(calls.length,before,'the original negative hold is preserved for a validator that still rejects it');
});
