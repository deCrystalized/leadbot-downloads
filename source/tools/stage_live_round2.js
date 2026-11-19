'use strict';
const {создатьСеть}=require('../extension-server/brain/net'),{создатьХранилище}=require('../extension-server/brain/store'),{создатьБюджет}=require('../extension-server/brain/budget'),{создатьКэш}=require('../extension-server/brain/cache'),{создатьИИ}=require('../extension-server/brain/ai'),{createAssistant}=require('../extension-server/brain/assistant');
const env={...process.env,LEADBOT_ASSISTANT_URL:'http://127.0.0.1:8789/api/extension/assistant'};
if(!env.BUCKET||!env.S3_URL)throw Error('Missing existing budget store configuration');
const запрос=создатьСеть(),store=создатьХранилище({запрос,bucket:env.BUCKET,iam:()=>env.IAM_TOKEN||'',s3:env.S3_URL}),budget=создатьБюджет({store,env,уведомить:async()=>{},log:()=>{}}),cache=создатьКэш({store,log:()=>{}}),ai=создатьИИ({запрос,env,budget,cache,iam:()=>env.IAM_TOKEN||'',log:e=>{if(e.ok===false)console.log(JSON.stringify({type:'provider_diagnostic',http:(String(e.err||'').match(/\b(?:HTTP )?(429|503|502|401|403)\b/)||[])[1]||'unavailable'}))}}),assistant=createAssistant({env,запрос,ai});
const base={city:'Чита',dir:'kp',partner:'7',accountTitle:'Денис КП',itemTitle:'Ремонт компьютеров',adIdentity:'Денис'},m=(body,direction='in',id='m1')=>({body,direction,id});
const price=[m('Установить Windows на ноутбук в Чите. Сколько стоит?'),m('После осмотра','out','m2'),m('А примерно какая цена?','in','m3'),m('От 500 рублей','out','m4'),m('Согласен, но какая точная стоимость?','in','m5')];
const cases=[
 ['greeting',{},[m('Здравствуйте!')],false],
 ['pc',{},[m('Компьютер не включается в Чите')],false],
 ['washer',{dir:'bt',itemTitle:'Ремонт бытовой техники'},[m('Стиральная машина Samsung WW60A не сливает в Чите')],false],
 ['stretch',{dir:'mnc',itemTitle:'Электрик'},[m('Установить люстру в Чите, потолок натяжной')],false],
 ['620',{dir:'mnc',partner:'620',itemTitle:'Сантехник'},[m('Поменять смеситель в Чите')],false],
 ['followup',{},[m('Компьютер не включается в Чите'),m('Здравствуйте! Что происходит при включении?','out','m2'),m('Никакой реакции','in','m3')],false],
 ['router-no-internet',{},[m('В Чите настроить роутер, интернет не проведен')],true],
 ['oven-door',{dir:'bt',itemTitle:'Ремонт плит'},[m('В Чите нужно заменить дверцу духовки')],true],
 ['cartridge',{},[m('В Чите заправить картридж принтера')],true],
 ['mixed',{},[m('В Чите починить компьютер и стиральную машину')],true],
 ['723',{partner:'723'},price,false],
 ['price-declined',{},[m('Видеокарта не работает в Чите'),m('Стоимость услуги от 5000 рублей','out','m2'),m('Нет, не согласен, дорого','in','m3')],true],
 ['matrix',{},[m('В Чите разбита матрица ЖК телевизора')],false],
 ['name',{},[m('Компьютер не включается в Чите. Как вас зовут?')],true]
];
(async()=>{const b=await budget.состояние();console.log(JSON.stringify({type:'budget',mode:b.mode,unknown:!!b.unknown}));let failed=0;
 for(const[name,k,messages,needsOperator]of cases){const ctx={...base,...k,convId:'synthetic-round2-'+name+'-v3',messages};const start=Date.now();const r=await assistant({action:'preview',ctx},'synthetic-round2-owner',b.mode);const passed=(name!=='723'||String(r.reply).includes('2000'))&&(name!=='followup'||!/здравств/i.test(r.reply||''))&&r.ok&&r.auto_enabled===false&&r.needs_operator===needsOperator&&(!r.validation||!r.validation.length);if(!passed)failed++;console.log(JSON.stringify({type:'case',name,passed,reply:r.reply,needs_operator:r.needs_operator,validation:r.validation,model:r.model,response_source:r.response_source,model_status:r.model_status,rub:r.model_rub,auto_enabled:r.auto_enabled,ms:Date.now()-start}));}
 await budget.сохранить();console.log(JSON.stringify({type:'summary',cases:cases.length,failed}));if(failed)process.exitCode=1;
})().catch(e=>{console.log(JSON.stringify({type:'error',name:e.name}));process.exitCode=1});
