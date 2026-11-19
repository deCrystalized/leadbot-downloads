'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создать}=require('../extension-server/brain/index');
const {createAssistant}=require('../extension-server/brain/assistant');
const {ключ}=require('../extension-server/brain/cache');
const format={type:'json_schema',strict:true,schema:{type:'object',properties:{
  context_review:{type:'object',properties:{selected_step_fits:{type:'boolean'}},required:['selected_step_fits']},
  reply:{type:'string'},needs_operator:{type:'boolean'}},required:['context_review','reply','needs_operator'],additionalProperties:false}};
const candidate=(fits=true,reply='Номер для связи подскажите?',operator=false)=>({context_review:{
  last_intent:'Помощь с медленным сливом, без замены унитаза',latest_client_meaning:'Причина неизвестна; клиент спрашивает, сможем ли помочь.',
  selected_step_fits:fits,evidence_ids:['improv-client-5'],note:'Уместность контакта оценена отдельно от причины.'},reply,needs_operator:operator});
const response=data=>({ok:true,status:200,json:async()=>data});
function fixture(value,{legacy=false,status=200}={}){
  const memory=new Map(),calls=[],logs=[];
  const raw=typeof value==='string'?value:JSON.stringify(value);
  const brain=создать({env:{GIGACHAT_KEY:'synthetic-only'},log:r=>logs.push(r),
    store:{get:async(k,d)=>structuredClone(memory.get(k)||d),put:async(k,v)=>memory.set(k,structuredClone(v))},
    запрос:async(url,opt)=>{
      if(url.includes('/oauth'))return response({access_token:'synthetic-only',expires_at:Date.now()+1800000});
      calls.push(JSON.parse(opt.body));
      if(status!==200)return{ok:false,status,headers:{get:()=>null},json:async()=>({error:'synthetic schema refusal'})};
      return response({choices:[{message:{content:raw},finish_reason:'stop'}],usage:{prompt_tokens:6215,completion_tokens:171}});
    }});
  const args={system:'trusted',task:'coherence212',max_tokens:700,...(!legacy?{response_format:structuredClone(format)}:{})};
  return{brain,args,calls,logs,memory,raw};
}
for(const fits of [true,false])for(const operator of [true,false])for(const reply of ['','Номер для связи подскажите?']){
  const good=fits?(!operator&&reply!==''):(operator&&reply==='');
  test(`typed joint state fits=${fits} operator=${operator} empty=${reply===''} is ${good?'accepted':'held'}`,async()=>{
    const value=candidate(fits,reply,operator),f=fixture(value);
    if(good){const out=await f.brain.completeLegacy(f.args);assert.deepEqual(JSON.parse(out.text),value);assert.equal(out.auto_enabled,false);}
    else{await assert.rejects(f.brain.completeLegacy(f.args),e=>e.неПоФорме&&e.modelFormatDiagnostics?.text===f.raw);}
    assert.equal(f.calls.length,1);
  });
}
for(const [name,value]of [
  ['whitespace',candidate(true,' \n\t',false)],['missing review',{reply:'Вопрос?',needs_operator:false}],
  ['null review',{...candidate(),context_review:null}],['string fit',candidate('true')],
  ['string operator',candidate(true,'Вопрос?','false')],['null reply',candidate(true,null,false)],
  ['absent fit',{...candidate(),context_review:{evidence_ids:['client']}}],
])test('typed invalid '+name+' is not cached as success',async()=>{
  const f=fixture(value);await assert.rejects(f.brain.completeLegacy(f.args),e=>!!e.неПоФорме);
  await assert.rejects(f.brain.completeLegacy(f.args),e=>!!e.неПоФорме);assert.equal(f.calls.length,1);
  assert.ok(f.logs.every(r=>!JSON.stringify(r).includes('Причина неизвестна')));
});
test('actual211 empty-positive is preserved with charged safe metadata and negative cached without regeneration',async()=>{
  const f=fixture(candidate(true,'',false));let error;
  try{await f.brain.completeLegacy(f.args);}catch(e){error=e;}
  assert.ok(error?.неПоФорме);assert.equal(error.modelFormatDiagnostics.text,f.raw);
  assert.deepEqual(error.modelFormatDiagnostics.generation,{finish_reason:'stop',requested_max_tokens:700,prompt_tokens:6215,completion_tokens:171});
  await assert.rejects(f.brain.completeLegacy(f.args));assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].max_tokens,700);assert.equal(f.calls[0].model,'GigaChat-2-Pro');
});
test('coherent fresh and cached outputs preserve observed generation metadata',async()=>{
  const value=candidate(),f=fixture(value);
  const first=await f.brain.completeLegacy(f.args),second=await f.brain.completeLegacy(f.args);
  assert.equal(first.cached,false);assert.equal(second.cached,true);assert.equal(f.calls.length,1);
  assert.deepEqual(second.generation,first.generation);
  assert.deepEqual(first.generation,{finish_reason:'stop',requested_max_tokens:700,prompt_tokens:6215,completion_tokens:171});
});
test('previously success-cached incoherent typed output is held without another generation',async()=>{
  const f=fixture(candidate(true,'',false));
  const base=ключ('assistant','GigaChat-2-Pro',f.args.system,f.args.task,'','',700);
  const key='brain/cache/'+ключ(base,'response_format',JSON.stringify(format))+'.json';
  f.memory.set(key,{text:f.raw,model:'GigaChat-2-Pro',at:Date.now()});
  await assert.rejects(f.brain.completeLegacy(f.args),e=>!!e.неПоФорме);
  assert.equal(f.calls.length,0);assert.equal(f.memory.get(key).bad,true);
  await assert.rejects(f.brain.completeLegacy(f.args));assert.equal(f.calls.length,0);
});
test('legacy JSON-only and differently shaped schemas keep their existing contracts',async()=>{
  for(const value of [{other:1},candidate(true,'',false),{reply:'Вопрос?',needs_operator:false}]){
    const f=fixture(value,{legacy:true});assert.deepEqual(JSON.parse((await f.brain.completeLegacy(f.args)).text),value);
  }
  const f=fixture({other:1});f.args.response_format.schema={type:'object',properties:{other:{type:'integer'}},required:['other'],additionalProperties:false};
  assert.deepEqual(JSON.parse((await f.brain.completeLegacy(f.args)).text),{other:1});
});
test('native grammar incompatibility is a single400 without free-text fallback',async()=>{
  const f=fixture(candidate(),{status:400});f.args.response_format.schema.anyOf=[{required:['reply']}];
  await assert.rejects(f.brain.completeLegacy(f.args));assert.equal(f.calls.length,1);
  assert.deepEqual(f.calls[0].response_format,f.args.response_format);
});
for(const fits of [true,false])test('ordinary extension applies the same joint state check, independent veto='+!fits,async()=>{
  const value=candidate(fits,'',!fits),requests=[],opts=[];
  const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-only'},
    запрос:async(_url,opt)=>{const b=JSON.parse(opt.body);requests.push(b);return response(b.action==='preview'
      ?{pending_model:true,request_id:'r',revision:'v',model_task:{system:'s',task:'t',max_tokens:700,response_format:format}}
      :{ok:true,reply:b.candidate.reply||'',auto_enabled:false});},
    ai:{спросить:async(_op,_system,_task,opt)=>{opts.push(opt);const raw=JSON.stringify(value);
      if(!opt.годен(raw))throw Object.assign(new Error('invalid'),{неПоФорме:true});return{text:raw,model:'GigaChat-2-Pro'};}}});
  await assistant({action:'preview',ctx:{}},'owner','normal');assert.equal(opts.length,1);
  const finalize=requests[1];assert.equal(finalize.action,'finalize');assert.equal(opts[0].singleAttempt,true);
  if(fits){assert.deepEqual(finalize.candidate,{});assert.equal(finalize.model_failure,'format');}
  else{assert.deepEqual(finalize.candidate,value);assert.equal(finalize.model_failure,'');}
});
