'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/observer');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
const tick=()=>new Promise(r=>setImmediate(r));
function nodes(x){return[x,...(x?.kids||[]).filter(x=>x&&typeof x==='object').flatMap(nodes)]}
test('next page publishes while previous full histories are still pending',async()=>{
 let release;const ui=create({h,list:async({offset})=>({items:[{id:offset?'new':'old',state:'waiting',version:1}],more:true}),
  loadContext:async id=>id==='old'?new Promise(r=>release=r):{convId:id,clientName:'Новый',messages:[]}});
 const old=ui.refresh();await tick();
 try{
  const next=nodes(ui.view()).find(x=>x.tag==='button'&&x.kids.includes('Далее'));
  assert.equal(next.attrs.disabled,false);
  await ui.refresh(25);assert.equal(ui.state.rows[0].id,'new');
 }finally{release({convId:'old',clientName:'Старый',messages:[]});await old}
 assert.equal(ui.state.rows[0].ctx.clientName,'Новый');
});
test('old history completion cannot clear a new roster loading flag',async()=>{
 let releaseOld,releaseList;const ui=create({h,list:async({offset})=>offset?new Promise(r=>releaseList=r):{items:[{id:'old',state:'waiting',version:1}],more:true},
  loadContext:async()=>new Promise(r=>releaseOld=r)});
 const first=ui.refresh();await tick();const second=ui.refresh(25);await tick();
 try{
  assert.ok(releaseList,'new roster request starts before old hydration ends');
  releaseOld({messages:[]});await first;
  const next=nodes(ui.view()).find(x=>x.tag==='button'&&x.kids.includes('Далее'));
  assert.equal(next.attrs.disabled,true);
 }finally{
  if(releaseList)releaseList({items:[],more:false});if(releaseOld)releaseOld({messages:[]});await Promise.all([first,second]);
 }
 assert.equal(ui.state.busy,false);
});
test('history read admission stays bounded across navigation generations',async()=>{
 let active=0,peak=0;const releases=[];
 const ui=create({h,list:async({offset})=>({items:Array.from({length:4},(_,i)=>({id:String(offset+i),state:'waiting',version:1})),more:true}),
  loadContext:async id=>{active++;peak=Math.max(peak,active);await new Promise(r=>releases.push(r));active--;return{convId:id,messages:[]}}});
 const first=ui.refresh();await tick();const second=ui.refresh(25);await tick();
 try{assert.equal(ui.state.offset,25);assert.equal(peak,4)}
 finally{for(let i=0;i<8;i++){releases.splice(0).forEach(r=>r());await tick()}await Promise.all([first,second])}
 assert.equal(peak,4);
});
test('same-page periodic refresh does not overlap pending hydration',async()=>{
 let calls=0,release;const ui=create({h,list:async()=>{calls++;return{items:[{id:'c',state:'waiting',version:1}],more:false}},
  loadContext:async()=>new Promise(r=>release=r)});
 const first=ui.refresh();await tick();await ui.refresh();assert.equal(calls,1);release({messages:[]});await first;
});
test('a dialogue repeated on the next roster does not inherit an obsolete loading flag',async()=>{
 let release,reads=0;const ui=create({h,list:async()=>({items:[{id:'same',state:'waiting',version:1}],more:true}),
  loadContext:async()=>++reads===1?new Promise(r=>release=r):{convId:'same',clientName:'Свежая',messages:[]}});
 const old=ui.refresh();await tick();
 try{await ui.refresh(25);assert.equal(reads,2);assert.equal(ui.state.rows[0].ctx?.clientName,'Свежая')}
 finally{release({convId:'same',clientName:'Старая',messages:[]});await old}
 assert.equal(ui.state.rows[0].loading,false);assert.equal(ui.state.rows[0].ctx.clientName,'Свежая');
});
