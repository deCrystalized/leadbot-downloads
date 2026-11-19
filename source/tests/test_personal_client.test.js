'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/personal');
function fixture(overrides={}){
 const calls=[],loaded=[];let identity='george';
 const deps={getIdentity:async()=>({id:identity,full_name:'Георгий'}),loadQueue:async()=>({mineCount:1,total:3,rows:[{id:'free',name:'Свободный'},{id:'other',assigneeId:'colleague'},{id:'mine',assigneeId:'george'}]}),
  loadContext:async(id)=>{loaded.push(id);return{convId:id}},visible:()=>true,
  send:async({args:a})=>{calls.push(a);assert.ok(['personal_start','personal_stop','personal_heartbeat','screen'].includes(a.action));return a.action==='screen'?{ok:true,eligible:true,scope:a.ctx.convId==='mine'?'mine':'free'}:{ok:true,active:a.action!=='personal_stop',max_dialogs:3,owner_name:'Георгий'}},...overrides};
 return{ui:create(deps),calls,loaded,changeIdentity:v=>{identity=v}};
}
test('owner API allowance is a bounded launch reservation and clears on stop',async()=>{
 const f=fixture({send:async()=>({ok:true,active:true,auto_enabled:true,research_auto:{available:true,active:true,limit:128,remaining_calls:124,blocked:false}})});
 try{await f.ui.start();assert.deepEqual(f.ui.state.apiAllowance,{limit:128,remaining:124,blocked:false})}
 finally{await f.ui.stop()}
 assert.equal(f.ui.state.apiAllowance,null);
});
test('a later review heartbeat removes the preceding launch allowance',async()=>{
 let auto=true;const f=fixture({send:async()=>({ok:true,active:true,auto_enabled:auto,research_auto:auto?{available:true,active:true,limit:128,remaining_calls:120,blocked:false}:{available:true,active:false}})});
 try{await f.ui.start();assert.equal(f.ui.state.apiAllowance.remaining,120);auto=false;await f.ui.heartbeat();assert.equal(f.ui.state.apiAllowance,null)}finally{await f.ui.stop()}
});
test('malformed API allowance is never displayed as money or authority',async()=>{
 for(const value of [{limit:'128',remaining_calls:4},{limit:128,remaining_calls:-1},{limit:128,remaining_calls:129},{limit:4097,remaining_calls:4}]){
  const f=fixture({send:async()=>({ok:true,active:true,auto_enabled:true,research_auto:{available:true,active:true,...value}})});
  try{await f.ui.start();assert.equal(f.ui.state.apiAllowance,null)}finally{await f.ui.stop()}
 }
});
test('personal queue preserves incoming priority and excludes foreign dialogs without writes',async()=>{
 const f=fixture();try{await f.ui.start();await f.ui.scan();assert.deepEqual(f.loaded,['free','mine']);assert.equal(f.ui.state.rows.length,2);assert.equal(f.ui.state.checked,2);assert.ok(f.calls.every(a=>!['claim','send','preview','crm_write','enable'].includes(a.action)))}finally{await f.ui.stop()}
});
test('at the personal limit a free dialogue is skipped without fetching its history',async()=>{
 const f=fixture({loadQueue:async()=>({mineCount:3,total:1,rows:[{id:'free'}]})});try{await f.ui.start();f.ui.state.managed=3;await f.ui.scan();assert.deepEqual(f.loaded,[]);assert.equal(f.ui.state.rows[0].admission,'capacity')}finally{await f.ui.stop()}
});
test('unknown load prevents all queue screening',async()=>{
 const f=fixture({loadQueue:async()=>({rows:[{id:'free'}]})});try{await f.ui.start();await f.ui.scan();assert.equal(f.ui.state.checked,0);assert.match(f.ui.state.error,/нагрузку/)}finally{await f.ui.stop()}
});
test('closing or hiding the tab stops the personal session',async()=>{
 const f=fixture({visible:()=>false});await f.ui.start();await f.ui.heartbeat();assert.equal(f.ui.state.active,false);assert.equal(f.calls.at(-1).action,'personal_stop')
});
test('a changed LeadChat login invalidates the personal session',async()=>{
 const f=fixture();await f.ui.start();f.changeIdentity('colleague');await f.ui.heartbeat();assert.equal(f.ui.state.active,false);assert.match(f.ui.state.error,/Аккаунт/);await f.ui.stop()
});
test('expired server lease cannot keep the browser session active',async()=>{
 const f=fixture({send:async({args:a})=>a.action==='personal_heartbeat'?{ok:false,error:'Сессия истекла'}:{ok:true,active:true,max_dialogs:3}});await f.ui.start();await f.ui.heartbeat();assert.equal(f.ui.state.active,false);assert.match(f.ui.state.error,/истекла/);await f.ui.stop()
});
test('pause during history retrieval prevents later screening and stale rows',async()=>{
 let release;const f=fixture({loadQueue:async()=>({mineCount:0,rows:[{id:'free'}]}),loadContext:async()=>new Promise(r=>{release=r})});await f.ui.start();const scan=f.ui.scan();await new Promise(r=>setImmediate(r));await f.ui.stop();release({convId:'free'});await scan;assert.deepEqual(f.ui.state.rows,[]);assert.equal(f.calls.filter(c=>c.action==='screen').length,0)
});
test('each scan is bounded and deduplicated',async()=>{
 const rows=Array.from({length:30},(_,i)=>({id:'free-'+i}));const f=fixture({loadQueue:async()=>({mineCount:0,total:31,rows:[rows[0],...rows]})});try{await f.ui.start();await f.ui.scan();assert.equal(f.loaded.length,12);assert.equal(new Set(f.loaded).size,12)}finally{await f.ui.stop()}
});
test('history screening uses at most three concurrent reads and preserves queue order',async()=>{let reads=0,max=0;const rows=Array.from({length:12},(_,i)=>({id:String(i)}));const f=fixture({loadQueue:async()=>({mineCount:0,rows}),loadContext:async id=>{max=Math.max(max,++reads);await new Promise(r=>setImmediate(r));reads--;return{convId:id}}});try{await f.ui.start();await f.ui.scan();assert.equal(max,3);assert.deepEqual(f.ui.state.rows.map(r=>r.id),rows.map(r=>r.id))}finally{await f.ui.stop()}});
test('new message priority comes first without losing the queue cursor or reading unknown IDs',async()=>{const rows=Array.from({length:30},(_,i)=>({id:'c'+i}));const f=fixture({loadQueue:async()=>({mineCount:0,rows})});try{await f.ui.start();await f.ui.scan(['c25','not-in-own-or-free-queue']);assert.equal(f.ui.state.rows[0].id,'c25');assert.equal(f.ui.state.offset,11);assert.ok(!f.loaded.includes('not-in-own-or-free-queue'));await f.ui.scan();assert.equal(f.ui.state.rows[0].id,'c11')}finally{await f.ui.stop()}});
test('session failure is visible and does not disable manual extension tools',async()=>{
 const f=fixture({send:async()=>({ok:false,error:'Другая вкладка'})});await f.ui.start();assert.equal(f.ui.state.active,false);assert.match(f.ui.state.error,/Другая/);assert.equal(f.loaded.length,0);await f.ui.stop()
});
test('connecting personal review explicitly stops the previous auto-claim path',async()=>{
 let stopped=0;const f=fixture({onStart:async()=>{stopped++}});try{await f.ui.start();assert.equal(stopped,1);assert.equal(f.ui.state.active,true)}finally{await f.ui.stop()}
});
test('next review batch advances instead of screening the same first dialogues forever',async()=>{
 const rows=Array.from({length:25},(_,i)=>({id:'free-'+i}));const f=fixture({loadQueue:async()=>({mineCount:0,total:25,rows})});
 try{await f.ui.start();await f.ui.scan();assert.equal(f.ui.state.more,true);await f.ui.scan();assert.equal(f.loaded.length,24);assert.equal(new Set(f.loaded).size,24);assert.equal(f.ui.state.offset,24);await f.ui.scan();assert.equal(f.loaded.length,25);assert.equal(f.ui.state.more,false)}finally{await f.ui.stop()}
});
test('a changing queue is logged and stays in read-only review for the next fresh cycle',async()=>{const events=[];const f=fixture({loadQueue:async()=>({mineCount:0,total:2,rows:[],paged:true,nextOffset:0,more:true,queueChanged:true}),logEvent:async(...event)=>{events.push(event)}});try{await f.ui.start();await f.ui.scan();assert.equal(f.ui.state.active,true);assert.equal(f.ui.state.auto,false);assert.equal(f.ui.state.error,'');assert.equal(f.ui.state.offset,0);assert.deepEqual(f.loaded,[]);assert.equal(events[0][2].operation,'queue_read_retry');assert.ok(f.calls.every(a=>!['claim','reply','create_crm'].includes(a.action)))}finally{await f.ui.stop()}});
