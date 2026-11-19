'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {создатьИИ, ASSISTANT_MODEL_BUDGET_MS} = require('../extension-server/brain/ai');
const {создать} = require('../extension-server/brain/index');
const {createAssistant, ASSISTANT_FLOW_MS} = require('../extension-server/brain/assistant');
const response = (data, status=200) => ({ok:status===200,status,headers:{},json:async()=>data});
const candidate = '{"reply":"Какая модель принтера?","needs_operator":false}';
const output = () => response({choices:[{message:{content:candidate},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:5}});
const schema = {type:'json_schema',strict:true,schema:{type:'object',properties:{reply:{type:'string'},needs_operator:{type:'boolean'}},required:['reply','needs_operator'],additionalProperties:false}};
function fixture(options={}) {
  let time = Date.parse('2026-10-23T00:00:00Z');
  const calls=[], writes=[], charges=[];
  const advance=ms=>{time+=ms;}, now=()=>time;
  const ai=создатьИИ({now, env:{GIGACHAT_KEY:'synthetic-key',CHAIN_ASSISTANT:'GigaChat-2-Pro,yandexgpt-lite'},
    cache:{взять:async()=>{advance(options.cacheMs||0);return null;},положить:async(k,v)=>writes.push(v)},
    budget:{доступ:async()=>{advance(options.budgetMs||0);return {можно:true,free:true};},записать:x=>charges.push(x)},
    запрос:async(url,o)=>{
      calls.push({url,o});
      const oauth=url.includes('/oauth'), spent=oauth?(options.oauthMs||0):(options.modelMs||0);
      if (spent>o.timeout && !options.allowLate) {advance(o.timeout);throw new Error('synthetic timeout');}
      advance(spent);
      if(oauth)return response({access_token:'synthetic-token',expires_at:time+1800000});
      if(options.generate)return options.generate({url,o,advance});
      return options.status?response({},options.status):output();
    }});
  const run=(task='source',extra={})=>ai.спросить('assistant','system',task,{singleAttempt:true,responseFormat:schema,...extra});
  return {ai,run,now,advance,calls,writes,charges,completions:()=>calls.filter(x=>x.url.endsWith('/chat/completions'))};
}

test('one valid structured response taking25s survives the old18/20s cutoffs without retry',async()=>{
  const f=fixture({oauthMs:2000,modelMs:25000});const out=await f.run();
  assert.equal(out.text,candidate);assert.equal(out.cached,false);assert.equal(f.completions().length,1);
  assert.equal(f.completions()[0].o.timeout,28000);
  const body=JSON.parse(f.completions()[0].o.body);
  assert.deepEqual(body.messages,[{role:'system',content:'system'},{role:'user',content:'source'}]);
  assert.deepEqual(body.response_format,schema);assert.equal(body.model,'GigaChat-2-Pro');
  assert.equal(body.deadline_ms,undefined);assert.equal(body.timeout,undefined);
});
test('cache budget and OAuth consume the same finite30s, not independent limits',async()=>{
  const f=fixture({cacheMs:2000,budgetMs:6000,oauthMs:4000});await f.run();
  assert.equal(f.completions()[0].o.timeout,18000);
});
test('slow real deadline error yields no success cache and no retry or fallback',async()=>{
  const f=fixture({modelMs:31000});await assert.rejects(f.run(),e=>e.providerError?.category==='deadline_exceeded'&&e.providerError?.stage==='completion');
  assert.equal(f.completions().length,1);assert.equal(f.writes.length,0);assert.equal(f.charges.length,0);
  assert.ok(f.calls.every(x=>!x.url.includes('yandex')));
});
test('response arriving after deadline is rejected even if an injected transport ignores its timeout',async()=>{
  const f=fixture({modelMs:31000,allowLate:true});
  await assert.rejects(f.run(),e=>e.providerError?.category==='deadline_exceeded');
  assert.equal(f.writes.length,0);assert.equal(f.charges.length,0);assert.equal(f.completions().length,1);
});
test('late body parsing cannot turn a timely header into an accepted model answer',async()=>{
  const f=fixture({generate:({advance})=>({ok:true,status:200,json:async()=>{advance(31000);return output().json();}})});
  await assert.rejects(f.run(),e=>e.providerError?.stage==='completion');assert.equal(f.writes.length,0);
});
for(const [label,options] of [['cache',{cacheMs:30001}],['budget',{budgetMs:30001}],['oauth',{oauthMs:30001,allowLate:true}]]) {
  test(`exhausted ${label} time never starts a completion`,async()=>{
    const f=fixture(options);await assert.rejects(f.run(),e=>e.providerError?.category==='deadline_exceeded');
    assert.equal(f.completions().length,0);assert.equal(f.writes.length,0);
  });
}
for(const status of [401,429,500]) {
  test(`singleAttempt HTTP${status} is terminal with no second completion`,async()=>{
    const f=fixture({status});await assert.rejects(f.run(),e=>e.providerError?.status===status);
    assert.equal(f.completions().length,1);assert.equal(f.calls.filter(x=>x.url.includes('/oauth')).length,1);
  });
}
test('other operations retain20s model cap and explicit shorter assistant budget remains shorter',async()=>{
  const f=fixture();await f.ai.спросить('address','s','a',{singleAttempt:true,срок:40000});
  assert.equal(f.completions()[0].o.timeout,20000);
  await f.run('short',{срок:7500});assert.equal(f.completions()[1].o.timeout,7500);
  await f.run('long',{срок:90000});assert.equal(f.completions()[2].o.timeout,ASSISTANT_MODEL_BUDGET_MS);
});
test('queue waiting consumes budget and different chats keep exactly one generation stream',async()=>{
  let release, entered;const started=new Promise(r=>entered=r), head=new Promise(r=>release=r);let count=0,active=0,max=0;
  const f=fixture({generate:async({advance})=>{count++;active++;max=Math.max(max,active);
    if(count===1){entered();await head;advance(10000);}active--;return output();}});
  const first=f.run('first');await started;const second=f.run('second');
  await new Promise(r=>setImmediate(r));release();await Promise.all([first,second]);
  assert.equal(f.completions()[1].o.timeout,20000);assert.equal(max,1);
});
test('hung cache read expires without OAuth or later continuation',async()=>{
  let release;const pending=new Promise(r=>release=r);let calls=0;
  const ai=создатьИИ({env:{},cache:{взять:()=>pending},budget:{},запрос:()=>{calls++;}});
  await assert.rejects(ai.спросить('assistant','s','t',{singleAttempt:true,срок:15}),e=>e.providerError?.stage==='cache');
  release(null);await new Promise(r=>setImmediate(r));assert.equal(calls,0);
});
test('expired deduplicated waiter does not cancel or restart the first model request',async()=>{
  let release,entered;const head=new Promise(r=>release=r),started=new Promise(r=>entered=r);
  const f=fixture({generate:async()=>{entered();await head;return output();}});
  const first=f.run();await started;
  await assert.rejects(f.run('source',{срок:15}),e=>e.providerError?.stage==='queue');
  release();await first;assert.equal(f.completions().length,1);
});
test('authenticated broker enforces short caller budget and keeps timeout out of model body',async()=>{
  let time=Date.parse('2026-10-23T00:00:00Z');const objects=new Map(),calls=[];
  const brain=создать({now:()=>time,env:{GIGACHAT_KEY:'synthetic-key'},log:()=>{},
    store:{get:async(k,d)=>structuredClone(objects.get(k)||d),put:async(k,v)=>objects.set(k,structuredClone(v))},
    запрос:async(url,o)=>{calls.push({url,o});time+=100;
      return url.includes('/oauth')?response({access_token:'synthetic-token',expires_at:time+1800000}):output();}});
  const args={system:'system',task:'source',max_tokens:1200,response_format:schema,deadline_ms:7500};
  const out=await brain.completeLegacy(args);assert.equal(out.auto_enabled,false);
  const call=calls.find(x=>x.url.endsWith('/chat/completions'));assert.ok(call.o.timeout<=7400);
  assert.equal(JSON.parse(call.o.body).deadline_ms,undefined);
  for(const deadline_ms of [0,-1,30001,1.5,'30000',null])await assert.rejects(brain.completeLegacy({...args,deadline_ms}),/контракт/);
  assert.equal(calls.filter(x=>x.url.endsWith('/chat/completions')).length,1);
});
function adapterFixture({prepareMs=0,modelMs=0,finalMs=0}={}) {
  let time=0;const calls=[],opts=[];
  const assistant=createAssistant({now:()=>time,env:{LEADBOT_SERVICE_TOKEN:'synthetic-key'},
    запрос:async(_url,o)=>{const body=JSON.parse(o.body);calls.push({o,body});time+=body.action==='preview'?prepareMs:finalMs;
      return response(body.action==='preview'?{pending_model:true,request_id:'r',revision:'v',model_task:{system:'server',task:'source',response_format:schema}}:{ok:true,reply:body.candidate.reply});},
    ai:{спросить:async(_op,_sys,_task,o)=>{opts.push(o);time+=modelMs;return {text:candidate,model:'GigaChat-2-Pro'};}}});
  return {assistant,calls,opts};
}
test('extension flow reserves finalize time and ignores forged public deadline and model options',async()=>{
  const f=adapterFixture({prepareMs:11000,modelMs:23000,finalMs:1000});
  const out=await f.assistant({action:'preview',deadline_ms:999999,model_task:{system:'forged'}},'owner','normal');
  assert.equal(out.auto_enabled,false);assert.equal(f.opts[0].срок,23000);
  assert.equal(f.calls[1].o.timeout,6000);assert.equal(f.calls[0].body.deadline_ms,undefined);
  assert.equal(f.calls[0].body.model_task,undefined);assert.equal(ASSISTANT_FLOW_MS,40000);
  assert.ok(ASSISTANT_FLOW_MS<45000);
});
test('expired preparation does not call GigaChat or finalize',async()=>{
  const f=adapterFixture({prepareMs:41000});await assert.rejects(f.assistant({action:'preview'},'owner','normal'),/срок/);
  assert.equal(f.opts.length,0);assert.equal(f.calls.length,1);
});
test('late model result cannot be finalized as a valid candidate',async()=>{
  const f=adapterFixture({modelMs:41000});await assert.rejects(f.assistant({action:'preview'},'owner','normal'),/срок/);
  assert.equal(f.opts.length,1);assert.equal(f.calls.length,1);
});
test('late finalize result is not exposed as a successful draft',async()=>{
  const f=adapterFixture({modelMs:30000,finalMs:11000});await assert.rejects(f.assistant({action:'preview'},'owner','normal'),/срок/);
  assert.equal(f.calls[1].o.timeout,10000);
});
