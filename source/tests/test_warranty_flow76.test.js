'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const repeat=require('../ext/repeat');
const current={dir:'mnc',appl:'Смеситель',sub:'Замена',partner:'7',src:'С1',now:Date.parse('2026-10-19T12:00:00Z')};
const card=(extra={})=>({id:'1000001',dir:'mnc',appl:'Смеситель',sub:'Замена',partner:'7',src:'С1',status:'Готов',typeText:'Впервые',closedAt:'2026-10-01',...extra});
const same=[{direction:'in',body:'После вашего ремонта смеситель снова течёт'}];

test('same problem after our work is first warranty, another task is repeat',()=>{
 const first=repeat.оценить([card()],{...current,messages:same});
 assert.equal(first.type,'Гарантия');assert.equal(first.approval,'');
 const another=repeat.оценить([card()],{...current,messages:[{direction:'in',body:'Вы меняли смеситель, теперь нужно собрать шкаф'}]});
 assert.equal(another.type,'Повтор');
});
test('later technical warranty requires branch approval; financial OKK marker does not use first technical warranty',()=>{
 const second=repeat.оценить([card({typeText:'Гарантия'})],{...current,messages:same});
 assert.equal(second.type,'Гарантия');assert.match(second.approval,/согласован.*филиал/);
 const afterFinancial=repeat.оценить([card({typeText:'Гарантия ОКК',okk:true})],{...current,messages:same});
 assert.equal(afterFinancial.type,'Гарантия');assert.equal(afterFinancial.approval,'');
});
test('existing claim always routes to OKK even when a later warranty also needs the branch',()=>{
 const out=repeat.оценить([card({typeText:'Гарантия',hasClaim:true})],{...current,messages:same});
 assert.equal(out.okk,true);assert.match(out.approval,/ОКК/);assert.match(out.branchApproval,/филиал/);
 assert.match(out.tg,/ОКК|претензия/);
});
test('existing claim cannot be hidden by refusal approval either',()=>{
 const out=repeat.оценить([card({status:'Отказ',hasClaim:true})],{...current,messages:same});
 assert.equal(out.okk,true);assert.match(out.approval,/ОКК/);assert.match(out.branchApproval,/филиал/);
});
test('three calendar months boundary retains warranty until the boundary date ends',()=>{
 for(const [closedAt,day,wanted] of [['2026-07-19','2026-10-19','Гарантия'],['2026-07-18','2026-10-19','Повтор'],
  ['2026-04-30','2026-07-30','Гарантия'],['2026-04-30','2026-07-31','Повтор'],
  ['2026-01-31','2026-04-30','Гарантия'],['2026-01-31','2026-05-01','Повтор']]){
  const out=repeat.оценить([card({closedAt})],{...current,now:Date.parse(day+'T12:00:00Z'),messages:same});
  assert.equal(out.type,wanted,closedAt+' to '+day);
 }
});
test('hypothetical or prospective warranty question does not prove an after-service failure',()=>{
 for(const body of ['Какая у вас гарантия?','Если после вашего ремонта снова потечёт, что делать?',
                    'После вашего ремонта больше не течёт']){
  assert.equal(!!repeat.кКомуОбращается([{direction:'in',body}],{prev:[card()]}).гарантия,false,body);
 }
});
