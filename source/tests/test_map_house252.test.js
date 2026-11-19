'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const A=require('../ext/address'),R=require('../ext/addrrules');
const address=house=>({ok:true,street:'ул Ленина',house,city:'Тула'});
test('address agreement preserves letters, fractions and suffixes, not just digits',()=>{
 for(const [a,b] of [['12а','12б'],['5/2','5к2'],['5к2','5с2'],['169В/2','169Вк2']]){
  assert.equal(A.same(address(a),address(b)),false,a+' != '+b);
  assert.equal(A.combineMany([[address(a),'model'],[address(b),'rules']]).agree,false);
 }
 for(const [a,b] of [['005 / 2','5/2'],['5 корпус 2','5к2'],['28 литера А','28А']])assert.equal(A.same(address(a),address(b)),true);
});
test('OSM does not confirm a corpus as a fractional house',()=>{
 const data=[{address:{city:'Тула',road:'улица Ленина',house_number:'5к2'},lon:'1',lat:'2'}];
 assert.notEqual(A.osmJudge(data,address('5/2'),'Тула').status,'exact');
 assert.equal(A.osmJudge(data,address('5 корпус 2'),'Тула').status,'exact');
});
test('Yandex exact precision must also match the whole literal house',()=>{
 const data={response:{GeoObjectCollection:{featureMember:[{GeoObject:{Point:{pos:'1 2'},metaDataProperty:{GeocoderMetaData:{precision:'exact',Address:{Components:[{kind:'locality',name:'Тула'},{kind:'street',name:'улица Ленина'},{kind:'house',name:'5 корпус 2'}]}}}}}]}}};
 assert.notEqual(A.ygeoJudge(data,address('5/2'),'Тула').status,'exact');
 assert.equal(A.ygeoJudge(data,address('5к2'),'Тула').status,'exact');
});
test('DaData cannot discard an extra corpus or reinterpret a fraction',()=>{
 const data={suggestions:[{value:'Тула, Ленина, 5к2',data:{city:'Тула',street_with_type:'ул Ленина',house:'5',block_type:'к',block:'2',fias_level:'8',house_fias_id:'synthetic-only'}}]};
 for(const house of ['5','5/2'])assert.notEqual(A.dadataJudge(data,address(house),'Тула').status,'exact');
 assert.equal(A.dadataJudge(data,address('5 корпус 2'),'Тула').status,'exact');
});
