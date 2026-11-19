'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{create}=require('../ext/observer');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
async function fixture(){let revision='r1';const ui=create({h,list:async()=>({items:[{id:'c',state:'waiting',version:1,source_revision:revision}],more:false,total:1}),loadContext:async()=>({messages:[]})});await ui.refresh();return{ui,rev:r=>revision=r,text:()=>JSON.stringify(ui.view())}}
test('screening success cannot overwrite actual model admission or root-review wait',async()=>{
 const f=await fixture();for(const state of ['awaiting_admission','awaiting_root']){
  f.ui.update([{id:'c',step:'wait',research_state:state,reason:'Actual '+state}]);
  f.ui.update([{id:'c',eligible:true,reason:'Профильная работа без выявленных согласований'}]);
  assert.ok(f.text().includes('Actual '+state));assert.ok(!f.text().includes('Профильная работа'));
 }
});
test('a failed current screen removes an old prepared answer instead of being hidden by progress',async()=>{
 const f=await fixture();f.ui.update([{id:'c',step:'reply',reason:'Old worker',reply:'Old draft'}]);
 f.ui.update([{id:'c',eligible:false,reason:'Current history unavailable'}]);
 assert.ok(f.text().includes('Current history unavailable'));assert.ok(!f.text().includes('Old draft'));
});
test('a new native source revision clears the old workflow result without claiming or reusing its draft',async()=>{
 const f=await fixture();f.ui.update([{id:'c',step:'reply',reason:'Old worker',reply:'Old draft'}]);
 f.rev('r2');await f.ui.refresh();assert.ok(!f.text().includes('Old draft'));assert.ok(!f.text().includes('Old worker'));
});
test('returning to a paginated conversation clears its old draft when its source changed off-page',async()=>{
 let onPage=true,revision='r1';const ui=create({h,list:async()=>({items:onPage?[{id:'c',state:'waiting',version:1,source_revision:revision}]:[],more:false,total:onPage?1:0}),loadContext:async()=>({messages:[]})});
 await ui.refresh();ui.update([{id:'c',step:'reply',reply:'Old draft'}]);onPage=false;await ui.refresh();
 revision='r2';onPage=true;await ui.refresh();assert.ok(!JSON.stringify(ui.view()).includes('Old draft'));
});
test('returning to an unchanged cached conversation retains its actual API wait',async()=>{
 let onPage=true;const ui=create({h,list:async()=>({items:onPage?[{id:'c',state:'waiting',version:1,source_revision:'r1'}]:[],more:false,total:onPage?1:0}),loadContext:async()=>({messages:[]})});
 await ui.refresh();ui.update([{id:'c',step:'wait',research_state:'awaiting_admission',reason:'Actual wait'}]);onPage=false;await ui.refresh();
 onPage=true;await ui.refresh();assert.ok(JSON.stringify(ui.view()).includes('Actual wait'));
});
