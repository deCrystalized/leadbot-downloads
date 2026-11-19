'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { parseCandidate, parseJsonObject } = require('../extension-server/brain/assistant');
const { создать } = require('../extension-server/brain/index');
const { создатьСервер } = require('../extension-server/vps/brain_http');

function fixture(text) {
  const objects = new Map(), calls = [], logs = [];
  const brain = создать({env:{GIGACHAT_KEY:'synthetic-not-a-credential'},
    store:{get:async(k,d)=>structuredClone(objects.get(k)||d),put:async(k,v)=>objects.set(k,structuredClone(v))},
    log:row=>logs.push(row), запрос:async(url)=>{
      calls.push(url);
      return {ok:true,status:200,json:async()=>url.includes('/oauth')
        ? {access_token:'synthetic-access',expires_at:Date.now()+1800000}
        : {choices:[{message:{content:text},finish_reason:'stop'}],usage:{prompt_tokens:15,completion_tokens:12}}};
    }});
  return {brain,objects,calls,logs};
}

test('both completion paths parse one complete JSON object with or without a code fence',()=>{
  const value={reply:'Материал стены подскажите?',needs_operator:false};
  for(const raw of [JSON.stringify(value),'```json\n'+JSON.stringify(value)+'\n```','```\n'+JSON.stringify(value)+'\n```']) {
    assert.deepEqual(parseJsonObject(raw),value);
    assert.deepEqual(parseCandidate(raw),value);
  }
  for(const raw of ['null','[]','true','{"reply":','Пояснение\n```json\n{}\n```','```json\n{}','{}\n{}'])
    assert.equal(parseJsonObject(raw),null,raw);
  assert.deepEqual(parseJsonObject('{"other":1}'),{other:1});
  assert.equal(parseCandidate('{"other":1}'),null,'the downstream reply contract remains strict');
});

test('the actual budgeted completion normalizes a fenced object and reuses the same cache',async()=>{
  const expected={reply:'Из какого материала стены?',needs_operator:false,context_review:{evidence_ids:['latest']}};
  const f=fixture('```json\n'+JSON.stringify(expected)+'\n```');
  const args={system:'synthetic system',task:'synthetic fenced response',max_tokens:700};
  const out=await f.brain.completeLegacy(args);
  assert.deepEqual(JSON.parse(out.text),expected);
  assert.equal(out.auto_enabled,false);assert.equal(out.cached,false);
  assert.equal(out.model_json_normalized,true);
  const cached=await f.brain.completeLegacy(args);
  assert.equal(cached.cached,true);assert.deepEqual(JSON.parse(cached.text),expected);
  assert.equal(f.calls.filter(url=>!url.includes('/oauth')).length,1);
});

test('bare Python booleans are normalized without changing strings or accepting executable syntax',()=>{
  const raw=String.raw`{"reply":"True and False stay here, including \"False\" and C:\\True","needs_operator":False,"context_review":{"selected_step_fits":True}}`;
  const out=parseCandidate(raw);
  assert.equal(out.reply,'True and False stay here, including "False" and C:\\True');
  assert.equal(out.needs_operator,false);assert.equal(out.context_review.selected_step_fits,true);
  for(const raw of ['{"needs_operator":None}', '{"needs_operator":Falsey}', '{"value":True.__class__}',
                   '{True:False}', '{"needs_operator":False /* comment */}', '{"needs_operator":False};process.exit()',
                   '{"needs_operator":False,"reply":"unterminated}']) assert.equal(parseJsonObject(raw),null,raw);
  assert.equal(parseCandidate('{"reply":"True","needs_operator":"False"}'),null,'a string never becomes a boolean');
});

test('the actual broker accepts recorded Python-style boolean syntax with one generation and explicit normalization evidence',async()=>{
  const raw='{"reply":"Здравствуйте! Из какого материала стены?","needs_operator":False,"context_review":{"selected_step_fits":True,"evidence_ids":["latest"]}}';
  const f=fixture(raw),out=await f.brain.completeLegacy({system:'synthetic',task:'synthetic boolean syntax',max_tokens:700});
  assert.equal(out.model_json_normalized,true);assert.equal(out.cached,false);assert.equal(out.auto_enabled,false);
  const value=JSON.parse(out.text);assert.equal(value.needs_operator,false);assert.equal(value.context_review.selected_step_fits,true);
  assert.equal(f.calls.filter(url=>!url.includes('/oauth')).length,1);
});

test('first malformed output retains bounded evidence and charged usage without a retry or shared raw log',async()=>{
  const raw='Ответ без JSON '+'.'.repeat(6100),f=fixture(raw);
  const args={system:'synthetic system',task:'synthetic malformed response',max_tokens:700};
  let error;
  try {await f.brain.completeLegacy(args);} catch(e) {error=e;}
  assert.ok(error?.неПоФорме);
  const evidence=error.modelFormatDiagnostics;
  assert.equal(evidence.text.length,6000);assert.equal(evidence.chars,raw.length);assert.equal(evidence.truncated,true);
  assert.equal(evidence.sha256,crypto.createHash('sha256').update(raw).digest('hex'));
  assert.equal(f.calls.filter(url=>!url.includes('/oauth')).length,1);
  assert.ok([...f.objects.keys()].some(k=>k.startsWith('brain/usage/')),'rejected output still consumed provider tokens');
  assert.ok(f.logs.every(row=>!JSON.stringify(row).includes('Ответ без JSON')));
  await assert.rejects(f.brain.completeLegacy(args),e=>!!e.неПоФорме&&!e.modelFormatDiagnostics);
  assert.equal(f.calls.filter(url=>!url.includes('/oauth')).length,1,'negative cache is not bypassed');
});

test('rejected model evidence is available only on the authenticated loopback completion route',async t=>{
  const previous=process.env.LEADBOT_SERVICE_TOKEN;
  process.env.LEADBOT_SERVICE_TOKEN='synthetic-internal-token';
  t.after(()=>{if(previous===undefined)delete process.env.LEADBOT_SERVICE_TOKEN;else process.env.LEADBOT_SERVICE_TOKEN=previous;});
  const diagnostics={text:'synthetic rejected response',sha256:'a'.repeat(64),chars:27,truncated:false};
  const fail=async()=>{throw Object.assign(new Error('synthetic format error'),{modelFormatDiagnostics:diagnostics});};
  const server=создатьСервер({handler:fail,completeLegacy:fail});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base='http://127.0.0.1:'+server.address().port;
  const post=(path,headers={})=>fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:'{}'});
  const denied=await post('/internal/leadbot/completion');
  assert.equal(denied.status,403);assert.equal((await denied.json()).model_format_diagnostics,undefined);
  const allowed=await post('/internal/leadbot/completion',{'X-Leadbot-Token':'synthetic-internal-token'});
  assert.equal(allowed.status,502);assert.deepEqual((await allowed.json()).model_format_diagnostics,diagnostics);
  const publicResponse=await post('/public');
  assert.equal(publicResponse.status,502);assert.equal((await publicResponse.json()).model_format_diagnostics,undefined);
});
