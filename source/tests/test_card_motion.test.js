'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const src=fs.readFileSync(require.resolve('../ext/content'),'utf8');
function fixture(reduced=false){
 let opened=false;const animations=[],calls=[],row={hidden:false},body={hidden:true,contains:()=>true},ed={setAttribute:(k,v)=>calls.push([k,v]),focus:()=>calls.push('focus')};
 const sec={style:{overflow:''},getAttribute:()=> 'client',getBoundingClientRect:()=>({height:opened?200:48}),querySelector:q=>q.includes('.cz-ed')?ed:q.includes('.cz-row')?row:body,
  classList:{toggle:(_k,v)=>{opened=v}},animate:(frames,options)=>{const a={frames,options,cancel(){this.oncancel?.()}};animations.push(a);return a}};
 const s={S:{},root:{activeElement:{}},window:{matchMedia:()=>({matches:reduced})},WeakMap};vm.createContext(s);
 const a=src.indexOf('  const ДВИЖЕНИЯ_СЕКЦИЙ ='),b=src.indexOf('  const открыта =',a);vm.runInContext(src.slice(a,b),s);
 return{s,sec,row,body,ed,calls,animations};
}
test('disclosure preserves DOM fields and returns keyboard focus on collapse',()=>{
 const f=fixture();f.s.открытьСекцию(f.sec,true);assert.equal(f.body.hidden,false);assert.equal(f.row.hidden,true);assert.equal(f.s.S.раскрыто.client,true);
 f.s.открытьСекцию(f.sec,false);assert.equal(f.body.hidden,true);assert.equal(f.row.hidden,false);assert.equal(f.s.S.раскрыто.client,false);assert.ok(f.calls.includes('focus'));
 assert.equal(f.animations.length,2);f.animations[1].onfinish();assert.equal(f.sec.style.overflow,'');
});
test('rapid reverse leaves the final layout unconstrained and ignores the old finish callback',()=>{
 const f=fixture();f.s.открытьСекцию(f.sec,true);const old=f.animations[0];f.s.открытьСекцию(f.sec,false);
 old.onfinish();assert.equal(f.sec.style.overflow,'hidden');f.animations[1].onfinish();assert.equal(f.sec.style.overflow,'');assert.equal(f.body.hidden,true);
});
test('reduced motion updates state immediately without starting an animation',()=>{
 const f=fixture(true);f.s.открытьСекцию(f.sec,true);assert.equal(f.animations.length,0);assert.equal(f.body.hidden,false);assert.equal(f.sec.style.overflow,'');
});
test('missing animation API remains a usable direct disclosure',()=>{
 const f=fixture();delete f.sec.animate;f.s.открытьСекцию(f.sec,true);assert.equal(f.body.hidden,false);assert.equal(f.s.S.раскрыто.client,true);
});
