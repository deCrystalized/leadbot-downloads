'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const x=require('../ext/extract');
const rows=(...pairs)=>pairs.map(([direction,body],i)=>({id:String(i),direction,body,sender_type:direction==='system'?'system':'operator'}));
const history=()=>rows(['in','Повесить две полки. Сколько стоит?'],['out','от 800р будет'],
 ['in','И до какой суммы предел? От чего зависит?'],['out','12000 рублей будет за две полки'],
 ['in','Не за 12 тысяч же две полки вешаются'],['out','1200р все верно, стандартный прайс по городу'],
 ['in','1200 или 12000?'],['system','Диалог принят'],['out','Я же написал, 1200']);
const voiced=h=>x.озвучкиПоСообщениям(h,['от 800','12000 р','1200 р']);
test('resolved correction keeps only1200 in the actual CRM comment',()=>{
 const h=history(),before=JSON.stringify(h),v=voiced(h);
 assert.deepEqual(v,['1200 р']);
 const comment=x.buildComment({problem:'Повесить две полки.',voiced:v});
 assert.match(comment,/Озвучено: 1200 р/);assert.doesNotMatch(comment,/12000|800/);assert.equal(JSON.stringify(h),before);
});
test('normal client repair discards stale server and AI voiced fields',()=>{
 const out=x.уточнитьОзвучки({ok:true,lead:{problem:'Повесить две полки.',voiced:['от 800','12000 р','1200 р']}},{messages:history()});
 assert.deepEqual(out.lead.voiced,['1200 р']);assert.doesNotMatch(out.lead.comment,/12000|800/);
});
test('two different prices alone are not an explicit correction',()=>{
 const v=voiced(history().slice(0,6));assert.ok(v.some(s=>s.includes('12000')));
});
test('accepted original price cannot be erased',()=>{
 const h=history();h.splice(4,0,{id:'accept',direction:'in',body:'Да, 12000 рублей устраивает'});
 assert.ok(voiced(h).some(s=>s.includes('12000')));
});
test('unrelated service price is retained',()=>{
 const h=history();h[1].body='Замена розетки от 800 рублей';
 const v=voiced(h);assert.ok(v.some(s=>s.includes('800')));assert.ok(v.some(s=>s.includes('1200')));assert.ok(!v.some(s=>s.includes('12000')));
});
test('fare and diagnostic conditions remain separately visible',()=>{
 const h=history();h[1].body='Выезд 800 рублей, при ремонте бесплатно';
 const v=voiced(h);assert.ok(v.some(s=>s.includes('800')));assert.ok(!v.some(s=>s.includes('12000')));
});
test('a new service between the minimum and total preserves its scope',()=>{
 const h=history();h[2].body='Ещё нужно установить розетку, сколько стоит?';assert.ok(voiced(h).some(s=>s.includes('800')));
});
test('wrong-chat correction across a separate filler is omitted from the comment',()=>{
 const h=rows(['out','От 2000 рублей'],['out','ой'],['out','не вам'],['out','От 500 рублей']);
 const v=x.озвучкиПоСообщениям(h,['от 2000','от 500']);assert.ok(!v.some(s=>s.includes('2000')));assert.ok(v.some(s=>s.includes('500')));
});
test('delivery pending does not retract a confirmed amount',()=>{
 const h=history();h.at(-1).out_pending=true;assert.ok(voiced(h).some(s=>s.includes('12000')));
});
