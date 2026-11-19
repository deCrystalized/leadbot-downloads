'use strict';
const {создатьСеть}=require('../extension-server/brain/net');
const {создатьХранилище}=require('../extension-server/brain/store');
const {создатьБюджет}=require('../extension-server/brain/budget');
const {создатьКэш}=require('../extension-server/brain/cache');
const {создатьИИ}=require('../extension-server/brain/ai');
const {createAssistant}=require('../extension-server/brain/assistant');
const env={...process.env, LEADBOT_ASSISTANT_URL:'http://127.0.0.1:8789/api/extension/assistant'};
const запрос=создатьСеть(),store=создатьХранилище({запрос,bucket:env.BUCKET,iam:()=>env.IAM_TOKEN||'',s3:env.S3_URL});
const budget=создатьБюджет({store,env,уведомить:async()=>{},log:()=>{}}),cache=создатьКэш({store,log:()=>{}}),ai=создатьИИ({запрос,env,budget,cache,iam:()=>env.IAM_TOKEN||'',log:x=>console.log(JSON.stringify({type:'ai-log',...x}))});
const originalAsk=ai.спросить; ai.спросить=async(op,sys,task,opt)=>{const valid=opt.годен;opt.годен=text=>{const ok=valid(text);if(!ok)console.log(JSON.stringify({type:'invalid-synthetic-answer',text}));return ok};return originalAsk(op,sys,task,opt)};
const assistant=createAssistant({env,запрос,ai});
const base={city:'Чита',dir:'kp',partner:'7',accountTitle:'Денис КП',itemTitle:'Ремонт компьютеров',adIdentity:'Денис'};
(async()=>{const b=await budget.состояние();console.log(JSON.stringify({type:'budget',mode:b.mode,unknown:!!b.unknown}));
const samples=[['pc',base,'В Чите компьютер шумит при включении. Вы делаете чистку?'],['bt',{...base,dir:'bt',itemTitle:'Ремонт стиральных машин'},'Стиральная машина не сливает воду в Чите'],['mnc',{...base,dir:'mnc',itemTitle:'Электрик'},'Нужно установить люстру, нахожусь в Чите'],['620',{...base,dir:'mnc',partner:'620',itemTitle:'Сантехник'},'В Чите нужно поменять смеситель'],['tvrefuse',{...base,itemTitle:'Ремонт телевизоров'},'В Чите телевизор с разбитой матрицей']];
for(const[name,known,text]of samples){const t=Date.now();const ctx={...known,convId:'synthetic-stage-'+name+'-v4',messages:[{id:'m1',direction:'in',body:text}]};const r=await assistant({action:'preview',ctx},'synthetic-stage-owner',b.mode);console.log(JSON.stringify({type:'case',name,ok:r.ok,reply:r.reply,needs_operator:r.needs_operator,validation:r.validation,model:r.model,rub:r.model_rub,auto_enabled:r.auto_enabled,ms:Date.now()-t}));}
await budget.сохранить();})().catch(e=>{console.log(JSON.stringify({type:'error',name:e.name}));process.exitCode=1});
