'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создатьИИ}=require('../extension-server/brain/ai');
const {создатьСервер}=require('../extension-server/vps/brain_http');
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return{promise,resolve};};
const response=(body,status=200,headers={})=>({ok:status>=200&&status<300,status,headers,json:async()=>body});
const answer=()=>response({choices:[{message:{content:'{"reply":"Какой материал стены?","needs_operator":false}'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:5}});
function fixture(generate,extra={}){
 const calls=[],logs=[],charges=[],memory=new Map();
 const ai=создатьИИ({env:{GIGACHAT_KEY:'synthetic-key',CHAIN_ADDRESS:'GigaChat-2-Pro'},
  запрос:async(url,options)=>{calls.push(url);return url.includes('/oauth')
   ?response({access_token:'synthetic-token',expires_at:Date.now()+1800000}):generate(url,options);},
  cache:{взять:async k=>memory.get(k),положить:async(k,v)=>memory.set(k,v)},
  budget:{доступ:async()=>({можно:true,free:true}),записать:x=>{charges.push(x);return 0;}},
  log:x=>logs.push(x),...extra});
 return{ai,calls,logs,charges};
}
const once={singleAttempt:true};

test('different chats and extension operations share one personal GigaChat stream',async()=>{
 let active=0,maximum=0;
 const f=fixture(async()=>{active++;maximum=Math.max(active,maximum);
  await new Promise(r=>setTimeout(r,4));active--;return answer();});
 const result=await Promise.all(Array.from({length:8},(_,i)=>f.ai.спросить(i%2?'address':'assistant','system','chat'+i,once)));
 assert.equal(result.length,8);assert.equal(maximum,1);assert.equal(active,0);
 assert.equal(f.calls.filter(x=>x.includes('/oauth')).length,1);
 assert.equal(f.calls.filter(x=>x.includes('/chat/completions')).length,8);
});

test('a queued expired chat never calls the model or overtakes a still active request',async()=>{
 const entered=deferred(),head=deferred();let count=0,clock=10000;
 const f=fixture(async()=>{count++;if(count===1){entered.resolve();await head.promise;}return answer();},{now:()=>clock});
 const first=f.ai.спросить('assistant','system','first',once);await entered.promise;
 const second=f.ai.спросить('assistant','system','expired',{...once,срок:1600});
 await new Promise(r=>setImmediate(r));clock+=2000;head.resolve();
 await first;await assert.rejects(second,e=>e.providerError?.category==='queue_timeout');
 assert.equal(count,1);await f.ai.спросить('address','system','next',once);assert.equal(count,2);
});

test('a queued deadline returns before the slow head and keeps its FIFO position closed',async()=>{
 const entered=deferred(),head=deferred();let count=0,active=0,maximum=0;
 const f=fixture(async()=>{count++;active++;maximum=Math.max(maximum,active);
  if(count===1){entered.resolve();await head.promise;}active--;return answer();});
 const first=f.ai.спросить('assistant','system','head',once);await entered.promise;
 await assert.rejects(f.ai.спросить('assistant','system','waiter',{...once,срок:1600}),e=>e.providerError?.category==='queue_timeout');
 assert.equal(count,1);const third=f.ai.спросить('address','system','third',once);
 await new Promise(r=>setImmediate(r));assert.equal(count,1);head.resolve();
 await Promise.all([first,third]);assert.equal(count,2);assert.equal(maximum,1);
});

test('an upstream failure releases the stream for the next independent chat',async()=>{
 let count=0;const f=fixture(async()=>++count===1?response({},500):answer());
 await assert.rejects(f.ai.спросить('assistant','system','bad',once),e=>e.providerError?.status===500);
 const next=await f.ai.спросить('assistant','system','good',once);assert.equal(next.model,'GigaChat-2-Pro');assert.equal(count,2);
});

test('single-attempt429 preserves a bounded Retry-After without retries or paid fallback',async()=>{
 const f=fixture(async()=>response({},429,{'Retry-After':'17'}));
 await assert.rejects(f.ai.спросить('assistant','system','limited',once),e=>{
  assert.deepEqual(e.providerError,{provider:'gigachat',status:429,stage:'completion',category:'rate_limited',retry_after_seconds:17});return true;});
 assert.equal(f.calls.filter(x=>x.includes('/chat/completions')).length,1);
 assert.ok(f.calls.every(x=>!x.includes('yandex')));assert.equal(f.charges.length,0);
});

test('HTTP-date Retry-After works and malformed private header text is not exposed',async()=>{
 const clock=Date.parse('2026-10-20T00:00:00Z');
 for(const [value,seconds] of [['Tue, 20 Oct 2026 00:00:09 GMT',9],['private-header-value',null],['999999999999999999999999999',null]]){
  const f=fixture(async()=>response({},429,{'retry-after':value}),{now:()=>clock});
  await assert.rejects(f.ai.спросить('assistant','system','limited'+value,once),e=>{
   assert.equal(e.providerError.retry_after_seconds,seconds);assert.ok(!JSON.stringify(e).includes(value));return true;});
 }
});

test('provider status metadata is exposed only by authenticated loopback completion',async t=>{
 const old=process.env.LEADBOT_SERVICE_TOKEN;process.env.LEADBOT_SERVICE_TOKEN='synthetic-internal-token';
 t.after(()=>{if(old===undefined)delete process.env.LEADBOT_SERVICE_TOKEN;else process.env.LEADBOT_SERVICE_TOKEN=old;});
 const providerError={provider:'gigachat',status:429,stage:'completion',category:'rate_limited',retry_after_seconds:7};
 const fail=async()=>{throw Object.assign(new Error('GigaChat HTTP429'),{providerError});};
 const server=создатьСервер({handler:fail,completeLegacy:fail});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const base='http://127.0.0.1:'+server.address().port;
 const send=(path,headers={})=>fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:'{}'});
 const denied=await send('/internal/leadbot/completion');assert.equal(denied.status,403);
 assert.equal((await denied.json()).provider_error,undefined);
 const allowed=await send('/internal/leadbot/completion',{'X-Leadbot-Token':'synthetic-internal-token'});
 assert.equal(allowed.status,502);assert.deepEqual((await allowed.json()).provider_error,providerError);
 const publicResult=await send('/');assert.equal((await publicResult.json()).provider_error,undefined);
});
