'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const territory=require(process.env.LEADBOT_TERRITORY_TEST_MODULE || '../ext/territory');

// DOC-L0629–0640, KP-L0444; owner18.10 includes 36.9, agreement starts at37.
// Artificial coordinates test the threshold, without reading held-out chats.
const origin=[10,0];
const point=distance=>[10,distance/6371*180/Math.PI];
const outside={inMap:false,branch:'Контрольный филиал',own:{},zones:[]};
const ctx=distance=>({city:'Контрольный филиал',locality:'Дальняя Деревня',cityPt:origin,pt:point(distance)});

for(const distance of [35.9,36,36.0001,36.4,36.49,36.9,36.99]) test('KP accepts '+distance+' km under the owner whole-kilometre rule',()=>{
 const r=territory.decide('kp',outside,ctx(distance));
 assert.equal(r.approval,false);assert.equal(r.far,true);assert.equal(r.по36,true);
 assert.equal(r.hours,'2–2,5');
});
for(const distance of [37,37.01,37.4]) test('KP requires agreement starting at '+distance+' km',()=>{
 const r=territory.decide('kp',outside,ctx(distance));
 assert.equal(r.approval,true);assert.equal(r.far,true);assert.notEqual(r.по36,true);
});
for(const dir of ['bt','mnc']) test(dir+' does not inherit the KP radius or far flag',()=>{
 const r=territory.decide(dir,outside,ctx(10));
 assert.equal(r.approval,true);assert.equal(r.far,false);
});
test('TV outside both territories needs agreement even within the KP radius',()=>{
 const r=territory.decide('kp',outside,{...ctx(10),tv:true});
 assert.equal(r.approval,true);assert.equal(r.far,true);assert.notEqual(r.по36,true);
});
test('an ordinary satellite receives the satellite slot without a far flag',()=>{
 const r=territory.decide('kp',outside,{...ctx(80),city:'Контрольный спутник',locality:'Контрольный спутник',mainCity:'Контрольный филиал',mainPt:origin});
 assert.equal(r.approval,false);assert.equal(r.far,false);assert.equal(r.hours,'2–2,5');assert.equal(r.earliest,'11:00');
});
test('the radius is measured from the main branch rather than the selected satellite',()=>{
 const r=territory.decide('kp',outside,{...ctx(10),city:'Контрольный спутник',mainCity:'Контрольный филиал',mainPt:point(80)});
 assert.equal(r.approval,true);assert.equal(r.far,true);
});
test('a custom map contour keeps precedence over a short distance',()=>{
 const r=territory.decide('kp',{...outside,own:{'контрольный филиал':{name:'Контрольный филиал'}}},ctx(10));
 assert.equal(r.approval,true);assert.equal(r.far,true);
});
test('Belgorod has no automatic far-trip acceptance',()=>{
 const c=territory.центр('Белгород');
 const r=territory.decide('kp',outside,{city:'Белгород',locality:'Контрольный посёлок',pt:[c[0],c[1]+.01]});
 assert.equal(r.approval,true);assert.equal(r.far,true);
});
test('unknown distance cannot be described as a measured distance above 36 km',()=>{
 const r=territory.decide('kp',outside,{city:'Контрольный филиал',locality:'Контрольный посёлок'});
 assert.equal(r.approval,true);assert.equal(r.far,true);
 assert.match(r.why.join(' '),/расстояние.{0,25}не (?:определено|подтверждено)/);
 assert.doesNotMatch(r.why.join(' '),/КП дальше 36 км/);
});
test('the37km boundary stays closed with an actual branch latitude',()=>{
 const c=territory.центр('Курск');
 const r=territory.decide('kp',outside,{city:'Курск',locality:'Дальняя Деревня',pt:[c[0],c[1]+37/6371*180/Math.PI]});
 assert.equal(r.approval,true);assert.notEqual(r.по36,true);
});
