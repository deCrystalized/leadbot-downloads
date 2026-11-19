'use strict';
const fs=require('fs');
const {создатьСеть}=require('../extension-server/brain/net'),{создатьХранилище}=require('../extension-server/brain/store'),{создатьБюджет}=require('../extension-server/brain/budget'),{создатьКэш}=require('../extension-server/brain/cache'),{создатьИИ}=require('../extension-server/brain/ai'),{createAssistant}=require('../extension-server/brain/assistant');
const env={...process.env,LEADBOT_ASSISTANT_URL:'http://127.0.0.1:8789/api/extension/assistant',LEADBOT_PERSONAL_OWNER_ID:'evaluation'};
let rawCandidate='';
const запрос=создатьСеть(),store=создатьХранилище({запрос,bucket:env.BUCKET,iam:()=>env.IAM_TOKEN||'',s3:env.S3_URL}),budget=создатьБюджет({store,env,уведомить:async()=>{},log:()=>{}}),cache=создатьКэш({store,log:()=>{}}),underlying=создатьИИ({запрос,env,budget,cache,iam:()=>env.IAM_TOKEN||'',log:e=>{if(e.ok===false)console.log(JSON.stringify({diagnostic_http:(String(e.err||'').match(/\b(?:HTTP )?(429|503|502|401|403)\b/)||[])[1]||'unavailable'}))}}),ai={async спросить(...args){const r=await underlying.спросить(...args);rawCandidate=r.text;return r}},assistant=createAssistant({env,запрос,ai});
const input=JSON.parse(fs.readFileSync('test-artifacts/personal/real-cases-private.json','utf8'));
const output='test-artifacts/personal/real-results-private.json';
let phase='budget';
fs.writeFileSync(output,JSON.stringify({round:process.env.REVIEW_ROUND||'initial',cases:[],completed:false}));fs.chmodSync(output,0o600);
(async()=>{
 const state=await budget.состояние();if(state.unknown||state.mode==='rules')throw Error('Existing budget does not permit model review');
 const results=[];let modelResponses=0,rub=0;
 for(const row of input.cases){
  phase='assistant:'+row.review_number;
  rawCandidate='';
  if(row.category.startsWith('model:')&&(modelResponses>=25||rub>=10))throw Error('Evaluation cap reached');
  const ctx={...row.ctx,convId:row.ctx.convId+(process.env.REVIEW_ROUND?'-'+process.env.REVIEW_ROUND:'')};
  const r=await assistant({action:'preview',ctx},'evaluation',state.mode);
  if(r.model)modelResponses++;rub+=Number(r.model_rub)||0;
  results.push({case_id:row.case_id,number:row.review_number,category:row.category,raw_candidate_private:rawCandidate,reply:r.reply||'',action:r.action,needs_operator:r.needs_operator,reason:r.reason,validation:r.validation||[],model:r.model,model_cached:!!r.model_cached,response_source:r.response_source||'rules',model_status:r.model_status||'',rub:r.model_rub||0,auto_enabled:r.auto_enabled,ok:r.ok});
  fs.writeFileSync(output,JSON.stringify({round:process.env.REVIEW_ROUND||'initial',cases:results,model_responses:modelResponses,recorded_rub:rub,auto_enabled:false,completed:results.length===input.cases.length},null,2));fs.chmodSync(output,0o600);
  console.log(JSON.stringify({reviewed:results.length,total:input.cases.length,model_responses:modelResponses,auto_enabled:r.auto_enabled}));
 }
 await budget.сохранить();console.log(JSON.stringify({completed:true,cases:results.length,model_responses:modelResponses,recorded_rub:rub,customer_sends:0}));
})().catch(e=>{console.log(JSON.stringify({completed:false,phase,error:e.message,cause:e.cause&&e.cause.code}));process.exitCode=1});
