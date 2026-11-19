'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/observer');
const Native=require('../ext/assistant-native');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
const nodes=x=>[x,...(x?.kids||[]).filter(x=>x&&typeof x==='object').flatMap(nodes)];
test('manual source revision invalidates history even without a message or job-version change',async()=>{
 let revision='old',reads=0;
 const ui=create({h,list:async()=>({items:[{id:'c',version:1,state:'waiting',source_revision:revision,conversation_status:'in_progress'}],more:false,total:1}),
  loadContext:async()=>({messages:[],clientName:'Version '+(++reads)})});
 await ui.refresh();revision='new';await ui.refresh();assert.equal(reads,2);
 assert.equal(ui.state.rows[0].ctx.clientName,'Version 2');
});
test('archive is a separate server-filtered view; a manually closed conversation is not waiting or a created order',async()=>{
 const calls=[];let reads=0;
 const ui=create({h,list:async args=>{calls.push(args);return args.view==='archive'?{items:[{id:'old',state:'closed',conversation_status:'closed',version:1}],more:false,total:1}:{items:[],more:false,total:0}},
  loadContext:async()=>{reads++;return{messages:[]}}});
 await ui.refresh();assert.equal(ui.state.rows.length,0);
 await ui.source('archive');assert.equal(ui.state.rows[0]?.state,'closed');assert.equal(calls.at(-1).view,'archive');
 assert.equal(reads,0,'Closed archive must not hydrate old full histories automatically');
 const text=JSON.stringify(ui.view());assert.ok(text.includes('Закрыт'));assert.ok(!text.includes('Ожидает запуска или следующего шага'));
});
test('removals on a later page return to a valid page using the current total',async()=>{
 const calls=[];const ui=create({h,list:async args=>{calls.push(args.offset);return{items:args.offset?[]:[{id:'live',state:'waiting',version:1}],more:false,total:1}},loadContext:async()=>({messages:[]})});
 await ui.refresh(25);assert.equal(ui.state.offset,0);assert.equal(ui.state.rows[0]?.id,'live');assert.deepEqual(calls,[25,0]);
});
test('the native listing binds selected author and archive scope without mutating a job',async()=>{
 const calls=[];const native=Native.create({operator:()=> 'author',get:async url=>{calls.push(url);return{items:[],more:false,total:0,view:'archive'}},post:()=>assert.fail('Readonly observation cannot post')});
 await native.list({limit:25,offset:0,view:'archive'});
 assert.ok(calls[0].includes('view=archive'));assert.ok(calls[0].includes('operator_id=author'));
});
test('an old unfiltered server cannot pretend that its historical roster is the current active queue',async()=>{
 const native=Native.create({operator:()=> 'author',get:async()=>({items:[{id:'old',state:'paused'}],more:false})});
 await assert.rejects(native.list(),/не подтвердил актуальную очередь/);
});
test('empty roster says no dialogues instead of showing page one as a misleading count',async()=>{
 const ui=create({h,list:async()=>({items:[],more:false,total:0}),loadContext:()=>assert.fail('Empty roster has no bodies')});
 await ui.refresh();const text=JSON.stringify(ui.view());assert.ok(text.includes('Нет диалогов'));assert.ok(!text.includes('Страница 1'));
});
test('a released dialogue is archived without stale attention, draft or history hydration',async()=>{
 let reads=0;const ui=create({h,list:async()=>({items:[{id:'c',state:'released',version:1}],more:false,total:1}),loadContext:()=>{reads++;return{messages:[]}}});
 ui.update([{id:'c',needs_operator:true,reply:'Old draft'}]);await ui.source('archive');
 const text=JSON.stringify(ui.view());assert.ok(text.includes('Не у бота'));assert.ok(!text.includes('Old draft'));assert.equal(reads,0);
});
