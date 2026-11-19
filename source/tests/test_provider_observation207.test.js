'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создатьИИ,safeProviderError}=require('../extension-server/brain/ai');
const {createAssistant}=require('../extension-server/brain/assistant');
const schema={type:'json_schema',strict:true,schema:{type:'object',properties:{reply:{type:'string'}},required:['reply'],additionalProperties:false}};
function fixture({stage='oauth',status,malformed=false,missing=false}={}){
 let time=0;const calls=[],saved=[],charged=[],logs=[];
 const ai=создатьИИ({now:()=>time,env:{GIGACHAT_KEY:'synthetic-secret',CHAIN_ASSISTANT:'GigaChat-2-Pro,yandexgpt-lite'},
  cache:{взять:async()=>null,положить:async(k,v)=>saved.push(v)},budget:{доступ:async()=>({можно:true,free:true}),записать:v=>charged.push(v)},log:v=>logs.push(v),
  запрос:async(url,o)=>{const current=url.includes('/oauth')?'oauth':url.endsWith('/files')?'upload':url.endsWith('/delete')?'delete':'completion';calls.push({stage:current,timeout:o.timeout});
   const response=data=>({ok:true,status:200,json:async()=>data});
   if(current!==stage){if(current==='oauth')return response({access_token:'synthetic-token',expires_at:1800000});if(current==='upload')return response({id:'synthetic-file'});return response({});}
   if(status)return {ok:false,status,headers:{'retry-after':'12'},json:async()=>({})};
   if(missing)return response({});
   if(malformed)return {ok:true,status:200,json:async()=>{throw new SyntaxError('Bearer synthetic-token customer source must not leak');}};
   time+=o.timeout;const error=Error('Authorization Basic synthetic-secret; customer-private-text');error.name='AbortError';throw error;}});
 const run=()=>ai.спросить('assistant','system','source',{singleAttempt:true,responseFormat:schema,...(stage==='upload'?{image:{b64:'AA==',mime:'image/jpeg'}}:{})});
 return {run,calls,saved,charged,logs};
}
for(const stage of ['oauth','upload','completion'])test(`single network timeout is attributed to ${stage} without leaking or retry`,async()=>{
 const f=fixture({stage});let error;try{await f.run()}catch(e){error=e}
 assert.equal(error.providerError.stage,stage);assert.equal(error.providerError.category,'network_timeout');
 assert.equal(f.calls.filter(c=>c.stage===stage).length,1);assert.equal(f.calls.filter(c=>c.stage==='completion').length,stage==='completion'?1:0);
 assert.equal(f.saved.length,0);assert.equal(f.charged.length,0);assert.doesNotMatch(JSON.stringify([error.message,error.providerError,f.logs]),/synthetic-secret|synthetic-token|customer-private/);
});
for(const stage of ['oauth','completion'])test(`malformed ${stage} response has a safe response-stage error`,async()=>{
 const f=fixture({stage,malformed:true});let error;try{await f.run()}catch(e){error=e}
 assert.equal(error.providerError.stage,stage==='completion'?'completion_body':'oauth');assert.equal(error.providerError.category,'invalid_response');
 assert.equal(f.saved.length,0);assert.equal(f.charged.length,0);assert.doesNotMatch(error.message,/synthetic-token|customer source/);
});
for(const stage of ['oauth','completion'])test(`HTTP429 retains ${stage} and Retry-After with one attempt`,async()=>{
 const f=fixture({stage,status:429});await assert.rejects(f.run(),e=>e.providerError.stage===stage&&e.providerError.status===429&&e.providerError.retry_after_seconds===12);
 assert.equal(f.calls.filter(x=>x.stage===stage).length,1);assert.equal(f.charged.length,0);
});
test('provider error projection drops every non-contract field',()=>{
 assert.deepEqual(safeProviderError({provider:'gigachat',status:null,stage:'oauth',category:'network_timeout',retry_after_seconds:null,token:'secret',message:'private'}),{provider:'gigachat',status:null,stage:'oauth',category:'network_timeout',retry_after_seconds:null});
});
test('malformed provider metadata is absent rather than echoed',()=>{
 const base={provider:'gigachat',status:null,stage:'oauth',category:'network_timeout',retry_after_seconds:null};
 for(const value of [null,[],{...base,provider:'other'},{...base,stage:'https://secret'},{...base,status:900},{...base,retry_after_seconds:-1},{...base,category:'private-text'}])assert.equal(safeProviderError(value),null);
});
test('adapter passes only projected technical metadata into finalization',async()=>{
 const calls=[];const a=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-only'},now:()=>0,
  запрос:async(_u,o)=>{const b=JSON.parse(o.body);calls.push(b);return{ok:true,status:200,json:async()=>b.action==='preview'?{pending_model:true,request_id:'r',revision:'v',model_task:{system:'s',task:'t',response_format:schema}}:{ok:true,reply:'',needs_operator:true}}},
  ai:{спросить:async()=>{throw Object.assign(Error('Bearer hidden'),{providerError:{provider:'gigachat',status:null,stage:'oauth',category:'network_timeout',retry_after_seconds:null,headers:{Authorization:'hidden'}}})}}});
 await a({action:'preview',model_error:{stage:'forged'}},'owner','normal');
 assert.equal(calls[0].model_error,undefined);assert.equal(calls[1].model_failure,'transport');assert.equal(calls[1].model_error.stage,'oauth');assert.equal(calls[1].model_error.headers,undefined);assert.deepEqual(calls[1].candidate,{});
});
test('valid model output does not inherit caller-supplied failure metadata',async()=>{
 const calls=[];const a=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-only'},now:()=>0,
  запрос:async(_u,o)=>{const b=JSON.parse(o.body);calls.push(b);return{ok:true,status:200,json:async()=>b.action==='preview'?{pending_model:true,request_id:'r',revision:'v',model_task:{system:'s',task:'t'}}:{ok:true,reply:b.candidate.reply}}},ai:{спросить:async()=>({text:'{"reply":"Схема есть?","needs_operator":false}',model:'GigaChat-2-Pro'})}});
 const out=await a({action:'preview',model_error:{stage:'forged'}},'owner','normal');assert.equal(out.reply,'Схема есть?');assert.equal(calls[1].model_error,undefined);
});
for(const stage of ['oauth','upload'])test(`missing ${stage} identity never proceeds to completion`,async()=>{
 const f=fixture({stage,missing:true});await assert.rejects(f.run(),e=>e.providerError?.stage===stage&&e.providerError?.category==='invalid_response');
 assert.equal(f.calls.filter(x=>x.stage==='completion').length,0);assert.equal(f.saved.length,0);assert.equal(f.charged.length,0);
});
for(const valid of [true,false])test(`HTTP route projects ${valid?'valid':'untrusted'} error metadata without raw secret text`,async t=>{
 const {создатьСервер}=require('../extension-server/vps/brain_http');
 const before=process.env.LEADBOT_SERVICE_TOKEN,log=console.log,logs=[];
 process.env.LEADBOT_SERVICE_TOKEN='synthetic-internal';console.log=value=>logs.push(value);
 t.after(()=>{console.log=log;if(before===undefined)delete process.env.LEADBOT_SERVICE_TOKEN;else process.env.LEADBOT_SERVICE_TOKEN=before});
 const fail=async()=>{throw Object.assign(Error('Bearer synthetic-secret customer-private'),{providerError:{provider:'gigachat',status:null,stage:valid?'oauth':'https://private-token',category:'network_timeout',retry_after_seconds:null,headers:{Authorization:'synthetic-secret'}}})};
 const server=создатьСервер({handler:fail,completeLegacy:fail});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r)}));
 const base='http://127.0.0.1:'+server.address().port;
 for(const privateRoute of [true,false]){
  const response=await fetch(base+(privateRoute?'/internal/leadbot/completion':'/public'),{method:'POST',headers:{'Content-Type':'application/json',...(privateRoute?{'X-Leadbot-Token':'synthetic-internal'}:{})},body:'{}'});
  assert.equal(response.status,502);const body=await response.json();assert.doesNotMatch(JSON.stringify(body),/synthetic-secret|customer-private|private-token/);
  if(privateRoute&&valid)assert.deepEqual(body.provider_error,{provider:'gigachat',status:null,stage:'oauth',category:'network_timeout',retry_after_seconds:null});
  else assert.equal(body.provider_error,undefined);
 }
 assert.doesNotMatch(JSON.stringify(logs),/synthetic-secret|customer-private|private-token/);
});
