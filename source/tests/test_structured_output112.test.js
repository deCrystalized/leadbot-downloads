'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const {создатьИИ}=require('../extension-server/brain/ai');
const {создать}=require('../extension-server/brain/index');
const {createAssistant}=require('../extension-server/brain/assistant');
const response=data=>({ok:true,status:200,json:async()=>data});
const format=(max=280)=>({type:'json_schema',strict:true,schema:{type:'object',
  properties:{reply:{type:'string',maxLength:max},needs_operator:{type:'boolean'}},
  required:['reply','needs_operator'],additionalProperties:false}});
function fixture(env={}){
 const calls=[],charges=[],memory=new Map();
 const ai=создатьИИ({env:{GIGACHAT_KEY:'synthetic-not-a-key',...env},
  cache:{взять:async k=>memory.get(k),положить:async(k,v)=>memory.set(k,v)},
  budget:{доступ:async()=>({можно:true,free:true}),записать:x=>{charges.push(x);return 0}},
  запрос:async(url,opt)=>{calls.push({url,opt});return response(url.includes('/oauth')
   ?{access_token:'synthetic-token',expires_at:Date.now()+1800000}
   :{choices:[{message:{content:'{"reply":"Что требуется сделать?","needs_operator":false}'},finish_reason:'stop'}],
      usage:{prompt_tokens:20,completion_tokens:10}});}});
 return{ai,calls,charges};
}
test('strict format reaches the actual V1 GigaChat body without changing TLS or message roles',async()=>{
 const f=fixture(),schema=format();await f.ai.спросить('assistant','system','task',{singleAttempt:true,responseFormat:schema});
 const call=f.calls.find(x=>x.url.endsWith('/chat/completions')),body=JSON.parse(call.opt.body);
 assert.equal(call.url,'https://api.giga.chat/v1/chat/completions');assert.deepEqual(body.response_format,schema);
 assert.deepEqual(body.messages,[{role:'system',content:'system'},{role:'user',content:'task'}]);
 assert.match(call.opt.ca,/BEGIN CERTIFICATE/);assert.equal(call.opt.rejectUnauthorized,undefined);
 assert.equal(body.model,'GigaChat-2-Pro');
});
test('freestyle and strict requests have distinct caches; the same schema still reuses one generation',async()=>{
 const f=fixture();await f.ai.спросить('assistant','same system','same task',{singleAttempt:true});
 await f.ai.спросить('assistant','same system','same task',{singleAttempt:true,responseFormat:format()});
 const cached=await f.ai.спросить('assistant','same system','same task',{singleAttempt:true,responseFormat:format()});
 assert.equal(cached.cached,true);assert.equal(f.calls.filter(x=>x.url.endsWith('/chat/completions')).length,2);
 await f.ai.спросить('assistant','same system','same task',{singleAttempt:true,responseFormat:format(200)});
 assert.equal(f.calls.filter(x=>x.url.endsWith('/chat/completions')).length,3);
});
test('invalid structured format fails before OAuth, generation or a text fallback',async()=>{
 for(const value of [null,[],{type:'text'}, {...format(),strict:false},
   {...format(),schema:{type:'object',properties:'invalid',required:['reply'],additionalProperties:false}},
   {...format(),schema:{type:'object',properties:{},required:['missing'],additionalProperties:false}}]){
  const f=fixture();await assert.rejects(f.ai.спросить('assistant','s','t',{singleAttempt:true,responseFormat:value}),/контракт/);
  assert.equal(f.calls.length,0);assert.equal(f.charges.length,0);
 }
});
test('a strict request cannot silently fall back to another provider',async()=>{
 const f=fixture({CHAIN_ASSISTANT:'yandexgpt-lite'});
 await assert.rejects(f.ai.спросить('assistant','s','t',{responseFormat:format()}));
 assert.equal(f.calls.length,0);
});
test('schema is captured before awaits rather than changing between cache identity and wire request',async()=>{
 const f=fixture(),schema=format();const pending=f.ai.спросить('assistant','s','t',{singleAttempt:true,responseFormat:schema});
 schema.schema.properties.reply.maxLength=1;await pending;
 const body=JSON.parse(f.calls.find(x=>x.url.endsWith('/chat/completions')).opt.body);
 assert.equal(body.response_format.schema.properties.reply.maxLength,280);
});
test('ordinary extension path uses server format and does not forward a forged public format',async()=>{
 const requests=[],modelOptions=[],serverFormat=format();
 const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-service-token'},
  запрос:async(_url,opt)=>{const body=JSON.parse(opt.body);requests.push(body);return response(body.action==='preview'
    ?{pending_model:true,request_id:'draft',revision:'r',model_task:{system:'trusted-system',task:'trusted-task',max_tokens:700,response_format:serverFormat}}
    :{ok:true,reply:body.candidate.reply,auto_enabled:false});},
  ai:{спросить:async(_op,sys,task,opt)=>{assert.equal(sys,'trusted-system');assert.equal(task,'trusted-task');modelOptions.push(opt);return{text:'{"reply":"Что требуется сделать?","needs_operator":false}',model:'GigaChat-2-Pro'};}}});
 const out=await assistant({action:'preview',response_format:{type:'text'},model_task:{system:'forged'},ctx:{}},'owner','normal');
 assert.equal(out.auto_enabled,false);assert.equal(requests[0].owner,'owner');
 assert.equal(requests[0].response_format,undefined);assert.equal(requests[0].model_task,undefined);
 assert.deepEqual(modelOptions[0].responseFormat,serverFormat);assert.equal(modelOptions[0].singleAttempt,true);
});
test('authenticated internal completion path sends the same strict format',async()=>{
 const objects=new Map(),calls=[];
 const brain=создать({env:{GIGACHAT_KEY:'synthetic-not-a-key'},log:()=>{},
  store:{get:async(k,d)=>structuredClone(objects.get(k)||d),put:async(k,v)=>objects.set(k,structuredClone(v))},
  запрос:async(url,opt)=>{calls.push({url,opt});return response(url.includes('/oauth')
    ?{access_token:'synthetic-token',expires_at:Date.now()+1800000}
    :{choices:[{message:{content:'{"reply":"Что требуется сделать?","needs_operator":false}'},finish_reason:'stop'}],usage:{prompt_tokens:12,completion_tokens:8}});}});
 const out=await brain.completeLegacy({system:'s',task:'t',max_tokens:700,response_format:format()});
 assert.equal(out.auto_enabled,false);assert.deepEqual(JSON.parse(calls.find(x=>x.url.endsWith('/chat/completions')).opt.body).response_format,format());
 assert.equal(calls.filter(x=>x.url.endsWith('/chat/completions')).length,1);
});
test('provider error under strict format is not retried with free text',async()=>{
 const calls=[];const ai=создатьИИ({env:{GIGACHAT_KEY:'synthetic-not-a-key'},
  cache:{взять:async()=>null,положить:async()=>{}},budget:{доступ:async()=>({можно:true,free:true}),записать:()=>0},
  запрос:async(url,opt)=>{calls.push({url,opt});return url.includes('/oauth')?response({access_token:'synthetic-token',expires_at:Date.now()+1800000})
    :{ok:false,status:400,headers:{get:()=>null},json:async()=>({error:'synthetic unsupported schema'})};}});
 await assert.rejects(ai.спросить('assistant','s','t',{singleAttempt:true,responseFormat:format()}));
 const generations=calls.filter(x=>x.url.endsWith('/chat/completions'));assert.equal(generations.length,1);
 assert.deepEqual(JSON.parse(generations[0].opt.body).response_format,format());
});
