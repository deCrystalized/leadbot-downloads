const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/native-api.js');
const BASE='/bot-dialogs/assistant/native-office/';
function setup(handler,extra={}){
  const f={calls:[],tokens:0};
  f.client=create({fetch:async(...args)=>{f.calls.push(args);return handler(...args)},
    token:async()=>{f.tokens++;return 'synthetic-local-native-jwt'},loggedOut:()=>false,...extra});
  return f;
}
const json=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json'}});
test('native construction makes no request and never starts a Run',()=>{
  const f=setup(()=>json({}));assert.equal(f.tokens,0);assert.equal(f.calls.length,0);
});
test('native accepted response is original object from a single authenticated same-origin request',async()=>{
  const f=setup(()=>json({state:'create_started',execution_allowed:true,cid:'synthetic'}));
  const result=await f.client.post(BASE+'issue-create',{work_id:'a'.repeat(64)});
  assert.deepEqual(result,{state:'create_started',execution_allowed:true,cid:'synthetic'});
  assert.equal(f.calls.length,1);
  const [url,args]=f.calls[0];assert.equal(url,'/api/v1'+BASE+'issue-create');
  assert.equal(args.redirect,'error');assert.equal(args.credentials,'omit');
  assert.equal(args.headers.Authorization,'Bearer synthetic-local-native-jwt');
});
for(const status of [401,403,409,429,500,503]){
  test('native HTTP '+status+' is never silently retried or returned as success',async()=>{
    const f=setup(()=>json({state:'create_started',execution_allowed:true},status));
    await assert.rejects(f.client.post(BASE+'issue-create',{}),e=>e.status===status&&e.request_started);
    assert.equal(f.calls.length,1);assert.equal(f.tokens,1);
  });
}
for(const body of ['', 'not JSON', 'null', '[]']){
  test('2xx with invalid native body '+JSON.stringify(body)+' is unknown, not an empty success',async()=>{
    const f=setup(()=>new Response(body,{status:200,headers:{'Content-Type':'application/json'}}));
    await assert.rejects(f.client.post(BASE+'issue-create',{}),e=>e.code==='native_response'&&e.request_started);
    assert.equal(f.calls.length,1);
  });
}
test('native request timeout aborts one attempt without replay',async()=>{
  const f=setup((_,args)=>new Promise((_,reject)=>args.signal.addEventListener('abort',()=>reject(Error('private failure')))),{timeout:5});
  await assert.rejects(f.client.post(BASE+'issue-create',{}),e=>e.code==='native_timeout'&&e.request_started);
  assert.equal(f.calls.length,1);
});
test('native body deadline also covers stalled successful response',async()=>{
  const f=setup(()=>({ok:true,status:200,headers:new Headers({'Content-Type':'application/json'}),
    text:()=>new Promise(()=>{})}),{timeout:5});
  await assert.rejects(f.client.post(BASE+'created',{}),e=>e.code==='native_timeout');
  assert.equal(f.calls.length,1);
});
test('native network exception does not expose credential or private exception detail',async()=>{
  const secret='synthetic-private-header-never-log';
  const f=setup(()=>{throw Error(secret)});
  await assert.rejects(f.client.post(BASE+'created',{}),e=>{
    assert.ok(!JSON.stringify(e).includes(secret));assert.ok(!e.message.includes(secret));
    return e.code==='native_network';
  });
  assert.equal(f.calls.length,1);
});
test('native accepts only fixed own controls/office endpoints',async()=>{
  const f=setup(()=>json({}));
  for(const path of ['https://example.com/'+BASE,BASE+'send',BASE+'issue-create?x=1','/messages',BASE+'../native-run/start'])
    await assert.rejects(f.client.post(path,{}));
  assert.equal(f.calls.length,0);assert.equal(f.tokens,0);
});
test('invalid non-finite/missing/cyclic payload cannot be silently JSON-normalized',async()=>{
  const f=setup(()=>json({})),cyclic={};cyclic.self=cyclic;
  for(const value of [{cost:NaN},{cost:Infinity},{missing:undefined},cyclic])
    await assert.rejects(f.client.post(BASE+'prepare',value));
  assert.equal(f.calls.length,0);assert.equal(f.tokens,0);
});
test('native response content type/byte budget cannot become authority',async()=>{
  for(const headers of [
    {'Content-Type':'text/html'},
    {'Content-Type':'application/json','Content-Length':'2000001'},
  ]){
    const f=setup(()=>new Response('{"execution_allowed":true}',{headers}));
    await assert.rejects(f.client.post(BASE+'issue-create',{}),e=>e.code==='native_response');
    assert.equal(f.calls.length,1);
  }
});
test('native response bounded stream rejects oversized body',async()=>{
  const f=setup(()=>new Response(' '.repeat(2000001),{headers:{'Content-Type':'application/json'}}));
  await assert.rejects(f.client.get('/bot-dialogs/assistant/native-run'),e=>e.code==='native_response');
});
test('logout stops before token access and any native request',async()=>{
  const f=setup(()=>json({}),{loggedOut:()=>true});
  await assert.rejects(f.client.post(BASE+'heartbeat',{}),e=>e.code==='native_logout'&&!e.request_started);
  assert.equal(f.calls.length,0);assert.equal(f.tokens,0);
});
