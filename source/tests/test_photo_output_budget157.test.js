'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создать}=require('../extension-server/brain/index');
const {createAssistant}=require('../extension-server/brain/assistant');
const response=data=>({ok:true,status:200,json:async()=>data});
const valid='{"reply":"Что требуется сделать?","needs_operator":false}';
const format={type:'json_schema',strict:true,schema:{type:'object',properties:{reply:{type:'string'},needs_operator:{type:'boolean'}},required:['reply','needs_operator'],additionalProperties:false}};
function brokerFixture(){
 const objects=new Map(),calls=[],logs=[];
 const brain=создать({env:{GIGACHAT_KEY:'synthetic-not-a-key'},log:x=>logs.push(x),
  store:{get:async(k,d)=>structuredClone(objects.get(k)||d),put:async(k,v)=>objects.set(k,structuredClone(v))},
  запрос:async(url,opt)=>{
   if(url.includes('/oauth'))return response({access_token:'synthetic-token',expires_at:Date.now()+1800000});
   const body=JSON.parse(opt.body);calls.push(body);
   const short=body.max_tokens===700;
   return response({choices:[{message:{content:short?'{"reply":':valid},finish_reason:short?'length':'stop'}],usage:{prompt_tokens:4522,completion_tokens:short?151:260}});
  }});
 return{brain,calls,logs};
}
function extensionFixture(fail=false){
 const opts=[],requests=[];
 const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-service-token'},
  запрос:async(_url,opt)=>{const b=JSON.parse(opt.body);requests.push(b);return response(b.action==='preview'
   ?{pending_model:true,request_id:'r',revision:'v',model_task:{system:'trusted',task:'photo-proof',max_tokens:1100,response_format:format}}
   :{ok:true,auto_enabled:false,reply:b.candidate.reply||''});},
  ai:{спросить:async(_op,_system,_task,o)=>{opts.push(o);if(fail)throw Object.assign(new Error('synthetic truncated JSON'),{неПоФорме:true});return{text:valid,model:'GigaChat-2-Pro'};}}});
 return{assistant,opts,requests};
}
test('extension honors the server photo-proof budget rather than truncating it to900',async()=>{
 const f=extensionFixture();const o=await f.assistant({action:'preview',ctx:{}},'owner','normal');
 assert.equal(f.opts[0].maxTokens,1100);assert.equal(f.opts[0].singleAttempt,true);
 assert.deepEqual(f.opts[0].responseFormat,format);assert.equal(o.auto_enabled,false);
});
test('internal broker sends the same1100-token budget on the actual GigaChat wire',async()=>{
 const f=brokerFixture();const o=await f.brain.completeLegacy({system:'trusted',task:'photo-proof',max_tokens:1100,response_format:format});
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].max_tokens,1100);
 assert.deepEqual(f.calls[0].response_format,format);assert.equal(o.cached,false);assert.equal(o.model_json_normalized,false);
});
test('private format diagnostics preserve finishreason and observed usage without shared raw logs',async()=>{
 const f=brokerFixture();let error;
 try{await f.brain.completeLegacy({system:'trusted',task:'photo-proof',max_tokens:700,response_format:format});}catch(e){error=e;}
 assert.ok(error?.неПоФорме);assert.equal(f.calls.length,1);
 assert.deepEqual(error.modelFormatDiagnostics.generation,{finish_reason:'length',requested_max_tokens:700,prompt_tokens:4522,completion_tokens:151});
 assert.equal(error.modelFormatDiagnostics.text,'{"reply":');
 assert.ok(f.logs.every(r=>!JSON.stringify(r).includes('{"reply":')));
});
test('an unchanged failed budget stays held; a changed real outputcap has its own existing cache identity',async()=>{
 const f=brokerFixture(),a={system:'trusted',task:'photo-proof',max_tokens:700,response_format:format};
 await assert.rejects(f.brain.completeLegacy(a));await assert.rejects(f.brain.completeLegacy(a));assert.equal(f.calls.length,1);
 const b={...a,max_tokens:1100};const fresh=await f.brain.completeLegacy(b);assert.equal(fresh.cached,false);assert.equal(f.calls.length,2);
 const cached=await f.brain.completeLegacy(b);assert.equal(cached.cached,true);assert.equal(f.calls.length,2);
 assert.deepEqual(f.calls.map(x=>x.max_tokens),[700,1100]);
});
test('the larger extension cap does not enable a hidden retry or send an incomplete candidate',async()=>{
 const f=extensionFixture(true);const o=await f.assistant({action:'preview',ctx:{}},'owner','normal');
 assert.equal(f.opts.length,1);assert.equal(f.requests.length,2);
 assert.equal(f.requests[1].action,'finalize');assert.equal(f.requests[1].model_failure,'format');
 assert.deepEqual(f.requests[1].candidate,{});assert.equal(o.reply,'');assert.equal(o.auto_enabled,false);
});
