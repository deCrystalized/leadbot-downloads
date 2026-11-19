'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const M=require('../extension-server/brain/modules').загрузитьМодули(path.resolve(__dirname,'../ext'));
const rules=require('../extension-server/brain/rules').создатьПравила(M);
test('a labelled colloquial clock range is a window; durations and quantities remain unrelated',()=>{
 for(const text of ['В часов 5-6 получится у вас?','Часов в 5–6 удобно?']){
  const w=M.LC_EXTRACT.окноИзТекста(text);assert.equal(w.from,'17:00');assert.equal(w.until,'18:00');
 }
 for(const text of ['На работу потребуется 5-6 часов','В 5-6 дней уложимся','Нужно заменить 5-6 ручек','В часов 6-5 получится?'])assert.equal(M.LC_EXTRACT.окноИзТекста(text),null);
});
test('a newer client window accepted by the operator replaces an old tomorrow and never becomes current nearest time',()=>{
 const messages=[['out','Когда удобно?', '2026-10-17T06:00:00Z'],['in','А если завтра?', '2026-10-17T06:01:00Z'],
  ['out','Во сколько удобно?', '2026-10-17T06:02:00Z'],['in','В часов 5-6 получится у вас?', '2026-10-18T05:21:32Z'],
  ['out','Да', '2026-10-18T05:22:14Z'],['out','Подскажите номер и адрес', '2026-10-18T05:22:16Z'],
  ['in','Троицк 10 квартал дом 28 3 подъезд кв 60', '2026-10-18T05:22:56Z']]
  .map(([direction,body,created_at],i)=>({id:String(i),direction,body,created_at}));
 const out=rules.extract({convId:'synthetic-window',messages,city:'Троицк',tz:'Asia/Yekaterinburg',dir:'kp',now:new Date('2026-10-18T05:26:00Z')});
 assert.equal(out.lead.time_window.from,'17:00');assert.equal(out.lead.time_window.until,'18:00');assert.equal(out.lead.time_window.date,'2026-10-18');
 assert.equal(out.lead.visit_time,'');
 const selection=M.LC_EXTRACT.времяВОкне({iso:'2026-10-18',now:'10:26'},out.lead.time_window,{минимум:60});
 assert.equal(selection.time,'17:00');
});
