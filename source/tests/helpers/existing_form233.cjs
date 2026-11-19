'use strict';
// Execute the existing extension preparation/readiness functions. Only
// read-only LeadChat/CRM/map/TG dependencies are doubles. No create transport.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const Workflow=require('../../ext/workflow'),Extract=require('../../ext/extract');
function existingForm(ctx,options={}){
 const source=fs.readFileSync(require.resolve('../../ext/content'),'utf8'),calls=[];
 const conv={id:ctx.convId,crm_request_id:ctx.crmRequestId||'',client:{name:ctx.clientName||'Иван'},item:{title:ctx.itemTitle,city:'Чита'},
  account:{title:ctx.accountTitle,lead_origin:'С1',lead_partner_number:'7'}};
 const detail={conv,msgs:ctx.messages,identity:{}};
 const prep={ok:true,cityText:'Чита',cityId:'1',applId:'2',subId:'3',applRule:true,subRule:true,
  partnerFound:true,found:[],unchecked:[],appl:[{id:'2',text:'Компьютерная помощь'}],sub:[{id:'3',text:'Ремонт компьютера'}]};
 const territory={ok:true,hours:'10:00-21:30',earliest:'10:00',approval:false};
 const scope={LC_WORKFLOW:Workflow,LC_EXTRACT:Extract,LC_TERRITORY:{сТВ:t=>t},
  LC_TG:{кодИсточника:s=>s},LC_LINKS:{find:()=>null,isWhite:()=>false},
  location:{origin:'https://lead.invalid'},ПОЯС_ДИАЛОГА:new Map(),ОТКРЫТАЯ_У_НОМЕРА:new Map(),
  ПОЧЕМУ:{},копия:structuredClone,ctxOf:()=>structuredClone(ctx),
  объявлениеДиалога:c=>c.item,поясОбъявления:()=> 'Asia/Chita',каналИсточника:c=>c.account,
  заявкаLC:c=>c.crm_request_id?{id:c.crm_request_id}:null,
  исход:(base,st,why,extra)=>({...base,st,why,...extra}),
  шаг:async(key,_ttl,fn)=>{calls.push({kind:'cache-key',key});return fn()},когдаШаг:()=>Date.now(),
  personalDialog:async()=>detail,наДваДня:()=>false,техника:()=>'',партнёрКодом:()=> 'С1',
  группыTG:async()=>({ok:true}),чатАвито:()=>['synthetic-TG'],разделСозданных:async()=>true,
  территория:async args=>{calls.push({kind:'map',args});return options.territory||territory},
  историяПо:()=>null,белаяНаБТ:()=>false,белыйИсточник:()=>false,отзывНужен:()=>true,
  linkLines:comment=>comment,авитоДиалога:()=>true,
  безСкобокГород:s=>String(s).split('(')[0].trim(),dirName:s=>s,fmtPhone:s=>s,
  адресНазван:()=>true,клиентСейчас:()=>({iso:new Date().toISOString().slice(0,10)}),
  окноКлиента:()=>null,зонаБлижайшего:()=>({плюс:60,ранняя:'10:00'}),
  поЗаявке:async()=>null,городВБазе:async()=>true,
  разборИИ:()=>assert.fail('Reviewed bot form reached the legacy model'),
  разборПравилами:()=>assert.fail('No silent alternative extraction'),
  сТаймаутом:p=>p,послеРазбора:()=>assert.fail('Do not rewrite the accepted work description'),
  send:async req=>{calls.push(req);assert.equal(req.kind,'lcz-crm');return options.prep||prep},
  спросить:async req=>{calls.push(req);
   if(req.kind==='lcz-checklist')return options.checklist||{ok:true,results:[]};
   assert.equal(req.kind,'lcz-crm');return req.op==='existing'?{ok:true,found:[],unchecked:[]}:options.prep||prep},
 };
 vm.createContext(scope);
 for(const [start,end]of [
  ['  const сообщенияРазбора =', '  // объявление и канал-источник'],
  ['  const ОТКАЗ_ОПЕРАТОРА =', '  /* ЛИД-БОТ:'],
  ['  const ЛИДБОТ_ГОТОВ =', '  // заявка в «Модерации»'],
  ['  function withSource(', '  // источник «Белый'],
  ['  async function разобратьГотовность(', '  /* Клиент с уже созданной'],
  ['  async function workflowPrepare(', '  const workflowAdapters=']]){
  const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a,start);
  vm.runInContext(source.slice(a,b),scope);
 }
 vm.runInContext('globalThis.prepare=workflowPrepare;',scope);
 return {calls,run:(s,p,form)=>scope.prepare(s,p,form)};
}
module.exports={existingForm};
