'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../ext/actions'),core=require('../ext/crmact');
const snap=()=>({id:'1234567',dir:'mnc',statusCode:1,statusName:'Ожидает',cityName:'Тула',cityId:'1',visitDate:'2026-10-19',visitTime:'12:00',type:10,
 flags:{callCheck:false,callBeforeVisit:false},flagsEnabled:{callCheck:true,callBeforeVisit:true},buttons:{s1:true,saveComment:true},requiredOk:true});
const context={сейчас:{date:'2026-10-18',time:'15:00'}};
const plan=(v,s=snap())=>A.план('edit',s,v,context);
test('time, call flag and appended comment become one CRM form step, with verified targets',()=>{
 const p=plan({date:'2026-10-19',time:'14:00',callCheck:true,text:'Позвонить по приезде',field:'comment'});
 assert.equal(p.ok,true);assert.equal(p.steps.length,1);assert.equal(p.steps[0].action,'fields');
 const s=p.steps[0];assert.equal(s.params.time,'14:00');assert.equal(s.params.flags.callCheck,true);assert.equal(s.params.addComment,'Позвонить по приезде');
 assert.equal(s.expect.visitTime,'14:00');assert.equal(s.expect.changesCountPlus,1);assert.equal(s.expect.flags.callCheck,true);assert.equal(s.expect.comment,true);
 assert.equal(p.client.on,false);assert.equal(p.client.text,'');assert.ok(!p.tg.text.includes('клиент позвонит'));
 assert.equal(A.текстПослеCRM(p,{lastChange:'Реальная строка переноса CRM'}).includes('Реальная строка переноса CRM'),true);
 assert.equal(A.текстПослеCRM(p,{lastChange:'Реальная строка переноса CRM'}).split('Позвонить по приезде').length,2);
});
test('prefilled unchanged controls produce no action and no saved timestamp or duplicate comment',()=>{
 const p=plan({date:'2026-10-19',time:'12:00',callCheck:false,callBeforeVisit:false,text:''});assert.equal(p.ok,false);assert.equal(p.steps.length,0);assert.deepEqual(p.missing,['что поменять']);
});
test('comment-only append keeps visit and flags unchanged; service stays out of the city message',()=>{
 for(const field of ['comment','service','partner']){
  const p=plan({date:'2026-10-19',time:'12:00',callCheck:false,callBeforeVisit:false,text:'Дополнение',field});
  assert.equal(p.ok,true);assert.equal(p.steps.length,1);assert.equal(p.steps[0].params.time,undefined);assert.equal(p.steps[0].params.flags,undefined);assert.equal(p.tg.on,field==='comment');
  const normalized=core.нормПарамы('fields',p.steps[0].params);assert.equal(normalized.error||normalized.ошибка||'', '');
 }
});
test('turning call on clears before-visit in the same write; known caller wording is explicit',()=>{
 const s=snap();s.flags.callBeforeVisit=true;
 const p=plan({callCheck:true,ктоЗвонит:'мы',time:'14:00'},s);assert.equal(p.ok,true);assert.equal(p.steps.length,1);
 assert.equal(p.steps[0].params.flags.callBeforeVisit,false);assert.equal(p.steps[0].params.flags.callCheck,true);assert.ok(!p.tg.text.includes('клиент позвонит'));
});
test('turning call off and rescheduling reuses the exact flag-removal warning and one save',()=>{
 const s=snap();s.flags.callCheck=true;const p=plan({callCheck:false,time:'14:00'},s);assert.equal(p.ok,true);assert.equal(p.steps.length,1);assert.equal(p.steps[0].params.flags.callCheck,false);assert.ok(p.warnings.some(x=>/Прозвон снимают/.test(x)));
});
test('invalid date/time and read-only controls cannot be hidden by adding a comment',()=>{
 for(const input of [{time:'25:99'},{date:'2026-02-31'},{callCheck:true}]){
  const s=snap();if(input.callCheck)s.flagsEnabled.callCheck=false;
  assert.equal(plan({...input,text:'Добавить',field:'comment'},s).ok,false);
 }
 assert.equal(plan({text:'Добавить',field:'unknown'}).ok,false);
});
test('the editor is exposed only for supported status/save capability and never fabricates new customer consent',()=>{
 for(const status of [2,3,8,9,20,1001]){const s=snap();s.statusCode=status;assert.equal(plan({text:'Добавить'},s).ok,false)}
 const s=snap();s.buttons.s1=false;assert.equal(plan({time:'14:00'},s).ok,false);
 const fields=A.поля('edit',snap(),context);assert.equal(fields.find(x=>x.name==='ктоЗвонит').value,'');
 assert.equal(fields.find(x=>x.name==='text').required,undefined);assert.equal(A.доступные(snap(),context).some(x=>x.key==='edit'),true);
});
test('the actual fields recipe submits the combined edit exactly once and checks all changed scalar targets',async()=>{
 const p=plan({time:'14:00',callCheck:true,text:'Дополнение',field:'comment'}),normalized=core.нормПарамы('fields',p.steps[0].params);
 assert.ok(normalized.p);const params=normalized.p,posts=[];let state=snap();
 const form={},ctx={params,base:'https://synthetic.invalid',warnings:[]};
 const source=fs.readFileSync(require.resolve('../ext/crmact'),'utf8'),start=source.indexOf('    fields(к, doc, card)'),end=source.indexOf('    /* Перенос —',start);
 const s={ПОЛЕ:{callCheck:'CustomerRequest[is_need_call_check]',callBeforeVisit:'CustomerRequest[is_need_call_before_visit]'},ГАЛОЧКА:{callCheck:'Прозвон',callBeforeVisit:'Перед выездом'},
  своиКоды:()=>null,нужныКомментарии:()=>true,времяСтоит:(c,p)=>c.visitDate===p.date&&c.visitTime===p.time,проверитьВремя:()=>'',
  поставить:(_f,k,v)=>{state.flags[k.includes('before')?'callBeforeVisit':'callCheck']=v==='1';return ''},поле:()=>null,
  времяВФорму:(_f,p)=>{state.visitDate=p.date;state.visitTime=p.time;return ''},комментарииВФорму:(_c,_f,p)=>{state.comment=p.addComment;return [p.addComment]},
  действиеФормы:()=> 'https://synthetic.invalid/save',предупредитьКомментарии:()=>{},послеВремени:()=>()=>({lastChange:'Verified CRM transfer'}),
  отправитьФорму:async(_c,_f,url,allowed,_unused,goal,details)=>{posts.push({url,allowed:[...allowed]});assert.equal(goal(state),true);assert.equal(state.comment,'Дополнение');return {ok:true,...await details.после({doc:{},card:state})}}};
 vm.createContext(s);vm.runInContext('globalThis.make=({'+source.slice(start,end)+'}).fields;',s);
 const result=await s.make(ctx,{querySelector:()=>form},snap()).сделать();assert.equal(result.ok,true);assert.equal(posts.length,1);assert.equal(result.lastChange,'Verified CRM transfer');
});
