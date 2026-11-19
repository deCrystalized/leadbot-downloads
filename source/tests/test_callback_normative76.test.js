'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const extract=require('../ext/extract');
const content=fs.readFileSync(require.resolve('../ext/content.js'),'utf8');
const start=content.indexOf('  function своёВремя('),end=content.indexOf('  // заявка из разбора:',start);
assert.ok(start>0&&end>start);
const sandbox={LC_EXTRACT:extract,окноКлиента:l=>l.window||null,зонаБлижайшего:()=>({плюс:60,ранняя:'10:00'}),Date};
vm.createContext(sandbox);vm.runInContext(content.slice(start,end)+';globalThis.plan=своёВремя;',sandbox);
const lead={clock:{iso:'2026-10-19',now:'10:15'}};

test('callback keeps normative city lead time instead of four hours',()=>{
 for(const [minutes,time] of [[60,'11:15'],[120,'12:15'],[180,'13:15']]){
  const out=sandbox.plan(lead,'прозвон','',{плюс:minutes,ранняя:'10:00',где:'проверенная зона',известна:true});
  assert.equal(out.visit_time,time);assert.equal(out.visit_auto.kind,'прозвон');
  assert.equal(out.visit_auto.плюс,minutes);
 }
});
test('callback and ordinary nearest time share closing time and next-day policy',()=>{
 const l={clock:{iso:'2026-10-19',now:'20:15'}},zone={плюс:120,ранняя:'10:00'};
 const callback=sandbox.plan(l,'прозвон','',zone),ordinary=sandbox.plan(l,'ближайшее','',zone);
 assert.equal(callback.visit_date,ordinary.visit_date);assert.equal(callback.visit_time,ordinary.visit_time);
 assert.equal(callback.visit_date,'2026-10-20');assert.equal(callback.visit_time,'10:00');
});
test('client window is respected for a callback as well',()=>{
 const window=extract.окноИзТекста('Сегодня с 13 до 15');assert.ok(window);
 const l={...lead,window},zone={плюс:60,ранняя:'10:00'};
 const callback=sandbox.plan(l,'прозвон','',zone),ordinary=sandbox.plan(l,'ближайшее','',zone);
 assert.equal(callback.visit_time,ordinary.visit_time);assert.equal(callback.visit_time,'13:00');
});
test('a different unspecified day is not assigned a fabricated hour',()=>{
 assert.equal(sandbox.plan(lead,'прозвон','2026-10-20',{плюс:60}),null);
});

test('normal form marks unconfirmed callback time and removes only its own generated line',()=>{
 const workflow=require('../ext/workflow');
 const original={comment:'Заменить смеситель',call_check:true,visit_date:'2026-10-19',visit_time:'11:15',visit_auto:{date:'2026-10-19',time:'11:15',kind:'прозвон'}};
 const first=workflow.callbackComment(original);assert.match(first.comment,/время с клиентом не согласовано/);
 assert.equal(original.comment,'Заменить смеситель');assert.equal(workflow.callbackComment(first).comment,first.comment);
 const removed=workflow.callbackComment({...first,call_check:false});assert.equal(removed.comment,original.comment);assert.equal(removed.callback_comment_auto,undefined);
 const edited=workflow.callbackComment({...first,visit_time:'15:00'});assert.equal(edited.comment,original.comment);
 const manual=workflow.callbackComment({comment:first.comment,call_check:false});assert.equal(manual.comment,first.comment);
});

test('a client or manually selected hour is not labelled as an unconfirmed normative time',()=>{
 const workflow=require('../ext/workflow');
 const fixed={comment:'Клиент просил созвониться',call_check:true,visit_date:'2026-10-19',visit_time:'17:00'};
 assert.equal(workflow.callbackComment(fixed).comment,fixed.comment);
});

test('actual checkbox handler uses the current map zone and preserves a manually chosen hour',()=>{
 const a=content.indexOf('  function автоПоЗвонку()'),b=content.indexOf('  function обновитьЗвонок(',a);
 const fields={call_check:{checked:true},visit_date:{value:'2026-10-19'},visit_time:{value:'11:15'}};
 const l={...lead,visit_date:'2026-10-19',visit_time:'11:15',visit_auto:{date:'2026-10-19',time:'11:15',kind:'ближайшее'}};
 const state={lead:l,terr:{minimum:120},prep:{cityText:'Проверенный филиал'}};
 const s={S:state,panel:{querySelector:selector=>fields[(selector.match(/"([^"]+)"/)||[])[1]]},формаЭтого:()=>true,
  визитАвто:x=>x.visit_auto?.date===x.visit_date&&x.visit_auto?.time===x.visit_time,
  своёВремя:sandbox.plan,зонаБлижайшего:(_l,terr,prep)=>{assert.equal(prep,state.prep);return{плюс:terr.minimum,ранняя:'10:00'};},
  вПоле:(field,value)=>{fields[field].value=value;}};
 vm.createContext(s);vm.runInContext(content.slice(a,b)+';globalThis.toggle=автоПоЗвонку;',s);s.toggle();
 assert.equal(fields.visit_time.value,'12:15');assert.equal(state.lead.visit_auto.kind,'прозвон');
 fields.visit_time.value='17:00';s.toggle();assert.equal(fields.visit_time.value,'17:00');
});

test('actual normal form serializes the unconfirmed callback note',()=>{
 const a=content.indexOf('  function readForm()'),b=content.indexOf('  /* Код источника',a);
 const values={phone:'9990000001',name:'Иван',comment:'Заменить смеситель',visit_date:'2026-10-19',visit_time:'11:15',call_check:true};
 const s={S:{lead:{...lead,visit_auto:{date:'2026-10-19',time:'11:15',kind:'прозвон'}},prep:{}},
  panel:{querySelector:selector=>{const key=(selector.match(/"([^"]+)"/)||[])[1];if(!(key in values))return null;return key==='call_check'?{type:'checkbox',checked:values[key]}:{type:'text',value:values[key]};}},
  LC_EXTRACT:extract,LC_WORKFLOW:require('../ext/workflow')};
 vm.createContext(s);vm.runInContext(content.slice(a,b)+';globalThis.read=readForm;',s);
 const out=s.read();assert.equal(out.lead.call_check,true);assert.equal(out.lead.visit_time,'11:15');
 assert.match(out.lead.comment,/время с клиентом не согласовано/);
});
