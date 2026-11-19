'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create,style}=require('../ext/observer');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
const nodes=tree=>[tree,...(tree?.kids||[]).filter(x=>x&&typeof x==='object').flatMap(nodes)];
function fixture(){
 const calls=[],writes=[];
 const ui=create({h,list:async options=>{calls.push(options);return{items:Array.from({length:options.limit},(_,i)=>({id:'c'+(options.offset+i),state:'waiting',operator_id:'actor',version:1})),more:true}},
  loadContext:async id=>({clientName:'Клиент '+id,messages:[{id:'s',direction:'system',sender_type:'avito',body:'Системное событие'},{id:'m',direction:'in',sender_type:'client',body:'Подождите, отправлю фото'}]}),
  takeover:()=>writes.push('takeover'),inspect:()=>writes.push('inspect')});
 return{ui,calls,writes};
}
test('page size25 by default and100 distinct cards without enrollment or activation',async()=>{
 const f=fixture();await f.ui.refresh();assert.deepEqual(f.calls,[{limit:25,offset:0}]);
 await f.ui.pageSize('100');assert.equal(f.ui.state.rows.length,100);
 assert.equal(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).length,100);assert.deepEqual(f.writes,[]);
});
test('later pages use selected size and have no ten-dialogue offset cap',async()=>{
 const f=fixture();await f.ui.pageSize(100);await f.ui.refresh(200);
 assert.deepEqual(f.calls.at(-1),{limit:100,offset:200});assert.equal(f.ui.state.rows[0].id,'c200');
 assert.ok(JSON.stringify(f.ui.view()).includes('Страница 3'));
});
test('invalid page sizes do not send requests or change observation state',async()=>{
 const f=fixture();for(const size of [0,1,101,NaN,'all',-1])await f.ui.pageSize(size);
 assert.deepEqual(f.calls,[]);assert.equal(f.ui.state.pageSize,25);
});
test('at most four full histories are in flight even on100-card pages',async()=>{
 let active=0,peak=0,reads=0;
 const ui=create({h,list:async()=>({items:Array.from({length:100},(_,i)=>({id:'d'+i,state:'waiting',version:1})),more:false}),
  loadContext:async()=>{active++;reads++;peak=Math.max(peak,active);await new Promise(r=>setImmediate(r));active--;return{messages:[]}}});
 await ui.pageSize(100);assert.equal(reads,100);assert.equal(peak,4);
});
test('changing size fences late reads from old generation',async()=>{
 const f=fixture();let release;
 const ui=create({h,list:async({limit})=>({items:[{id:limit===25?'old':'new',state:'waiting',version:1}],more:false}),
  loadContext:async id=>id==='old'?new Promise(r=>release=r):{clientName:'Новый',messages:[]}});
 const previous=ui.refresh();await new Promise(r=>setImmediate(r));await ui.pageSize(50);release({clientName:'Старый',messages:[]});await previous;
 assert.equal(ui.state.rows[0].id,'new');assert.equal(ui.state.rows[0].ctx.clientName,'Новый');assert.deepEqual(f.writes,[]);
});
test('layout and density change only observation without fetching or starting workflow',async()=>{
 const f=fixture();await f.ui.refresh();const count=f.calls.length;
 f.ui.layout('list');f.ui.density('compact');assert.match(f.ui.view().attrs.class,/compact layout-list/);
 assert.equal(f.calls.length,count);assert.deepEqual(f.writes,[]);
 assert.ok(JSON.stringify(f.ui.view()).includes('Поиск и статусы — на текущей странице'));
});
test('keyboard labels remain unique for first10 even with100 displayed cards',async()=>{
 const f=fixture();await f.ui.pageSize(100);const shortcuts=nodes(f.ui.view()).filter(x=>x.tag==='kbd');
 assert.equal(shortcuts.length,10);assert.equal(new Set(shortcuts.map(x=>x.kids.join(''))).size,10);
});
test('service messages have distinct label and stable message keys',async()=>{
 const f=fixture();await f.ui.refresh();assert.ok(JSON.stringify(f.ui.view()).includes('Служебных событий: 1'));
 f.ui.focus('c0');const card=nodes(f.ui.view()).find(x=>x.attrs?.['data-observer-id']==='c0');
 const service=nodes(card).find(x=>x.attrs?.class==='observer-message service');assert.ok(service);
 assert.ok(JSON.stringify(service).includes('Система'));assert.equal(service.attrs['data-render-key'],'message-s');
});
test('the overview prioritizes latest conversation while focus retains all service events',async()=>{
 const f=fixture();await f.ui.refresh();let card=nodes(f.ui.view()).find(x=>x.attrs?.['data-observer-id']==='c0');
 assert.ok(JSON.stringify(card).includes('Подождите, отправлю фото'));
 assert.ok(!JSON.stringify(card).includes('Системное событие'));
 f.ui.focus('c0');assert.ok(JSON.stringify(f.ui.view()).includes('Системное событие'));
});
test('reduced motion and responsive layouts avoid global transitions',()=>{
 assert.match(style,/prefers-reduced-motion/);assert.match(style,/max-width:480px/);assert.match(style,/focus-visible/);
 assert.doesNotMatch(style,/transition:\s*all/);
});
test('unfinished ASR copy is not displayed as completed client speech',async()=>{
 const ui=create({h,list:async()=>({items:[{id:'voice',state:'waiting',version:1}],more:false}),
  loadContext:async()=>({messages:[{id:'v',direction:'in',body:'НЕЗАВЕРШЁННЫЕ СЛОВА',voice_transcript:'НЕЗАВЕРШЁННЫЕ СЛОВА',voice_transcript_status:'running'}]})});
 await ui.refresh();const text=JSON.stringify(ui.view());assert.ok(!text.includes('НЕЗАВЕРШЁННЫЕ СЛОВА'));assert.ok(text.includes('ещё не готова'));
});
test('completed history is read only after explicit focus, without resuming workflow',async()=>{
 let reads=0;const ui=create({h,list:async()=>({items:[{id:'done',state:'completed',version:1,crm_request_id:'123'}],more:false}),
  loadContext:async()=>{reads++;return{messages:[{id:'c',direction:'in',body:'Полная история'}]}}});
 await ui.refresh();assert.equal(reads,0);ui.focus('done');await new Promise(r=>setImmediate(r));
 assert.equal(reads,1);assert.ok(JSON.stringify(ui.view()).includes('Полная история'));assert.equal(ui.state.rows[0].state,'completed');
});
test('a context returned for another CID is rejected visibly',async()=>{
 const ui=create({h,list:async()=>({items:[{id:'expected',state:'waiting',version:1}],more:false}),
  loadContext:async()=>({convId:'another',messages:[{body:'Чужая история'}]})});
 await ui.refresh();assert.match(ui.state.rows[0].readError,/другому диалогу/);
 assert.ok(!JSON.stringify(ui.view()).includes('Чужая история'));
});
