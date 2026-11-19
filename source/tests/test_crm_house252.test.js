'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const h=require('../ext/crm')._внутр;
function form(building){
 const fields={street:'Ленина',building,office:'12',entrance:'3',floor:'4',fias:'old-fias',location:'old-point'};
 const elements=Object.entries(fields).map(([k,value])=>({name:'Customer[address_'+k+']',tagName:'INPUT',type:'text',value}));
 elements.push({name:'Customer[location]',tagName:'INPUT',type:'text',value:'old-point'});
 for(const e of elements)elements[e.name]=e;
 return {elements};
}
test('a fractional house is preserved when an existing customer has a corpus number',()=>{
 for(const [old,want] of [['5 корпус 2','5/2'],['169В корпус 2','169В/2']]){
  const p=h.планКлиента(form(old),{street:'Ленина',building:want},[]);
  assert.equal(p.house,true);assert.equal(p.ставим['Customer[address_building]'],want);
  for(const part of ['office','entrance','floor','fias'])assert.equal(p.ставим['Customer[address_'+part+']'],'');
  assert.equal(p.ставим['Customer[location]'],'');
 }
});
test('readback must reject a different corpus instead of confirming the requested fraction',()=>{
 assert.deepEqual(h.несохранено(form('5к2'),{'Customer[address_building]':'5/2'}),['дом «5к2»']);
 assert.deepEqual(h.несохранено(form('169В корпус 2'),{'Customer[address_building]':'169В/2'}),['дом «169В корпус 2»']);
});
test('literal fraction formatting and explicit corpus abbreviations remain equivalent',()=>{
 for(const [old,want] of [[' 005 / 2 ','5/2'],['169в / 2','169В/2'],['5 корпус 2','5к2'],['5 строение 2','5с2']]){
  const p=h.планКлиента(form(old),{street:'Ленина',building:want},[]);
  assert.equal(p.house,false,old);assert.equal(p.ставим['Customer[address_building]'],undefined);
  assert.deepEqual(h.несохранено(form(old),{'Customer[address_building]':want}),[]);
 }
});
