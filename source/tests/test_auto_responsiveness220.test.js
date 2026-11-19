'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Personal=require('../ext/personal'),Runner=require('../ext/assistant-runner'),Observer=require('../ext/observer');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:v=>resolve(v)}};
function personal(loadContext,rows){return Personal.create({getIdentity:async()=>({id:'actor'}),
 loadQueue:async()=>({mineCount:0,total:rows.length,rows}),loadContext,visible:()=>true,
 send:async({args:a})=>a.action==='screen'?{ok:true,eligible:true}:{ok:true,active:a.action!=='personal_stop',max_dialogs:0}})}

test('ready chat reaches auto worker before another history finishes, once with bounded parallelism',async()=>{
 const slow=deferred(),actions=[],timers=new Map();let id=0;
 const client=personal(async chat=>chat==='slow'?slow.promise:{convId:chat},[{id:'slow'},{id:'ready'}]);
 await client.start();
 const runner=Runner.create({active:()=>client.state.active,visible:()=>true,setMode:async()=>({ok:true,auto_enabled:true}),
  stopWorkflow:()=>{},schedule:(fn,delay)=>{timers.set(++id,{fn,delay});return id},clear:key=>timers.delete(key),
  scan:async(ids,onReady)=>{await client.scan(ids,onReady);return client.state.rows},
  step:async chat=>{actions.push(chat);return{step:'wait'}},inspect:async()=>({step:'wait'})});
 const run=runner.start('auto');await flush();await flush();
 const early=actions.includes('ready');slow.resolve({convId:'slow'});await run;
 runner.stop();await client.stop();
 assert.equal(early,true,'An unrelated slow history blocked the ready chat');
 assert.deepEqual(actions.sort(),['ready','slow']);
});

test('one unread history is ineligible and visible while other chats finish screening',async()=>{
 const client=personal(async id=>{if(id==='broken')throw Error('История недоступна');return{convId:id}},
  [{id:'broken'},{id:'ready-a'},{id:'ready-b'},{id:'ready-c'}]);
 try{await client.start();await client.scan();
  assert.equal(client.state.error,'');assert.equal(client.state.active,true);assert.equal(client.state.rows.length,4);
  const broken=client.state.rows.find(row=>row.id==='broken');assert.equal(broken.eligible,false);assert.equal(broken.needs_operator,true);
  assert.match(broken.reason,/История недоступна/);assert.equal(client.state.rows.filter(row=>row.eligible).length,3);
 }finally{await client.stop()}
});

test('global authorization loss still stops the queue rather than admitting unread chats',async()=>{
 const client=personal(async()=>{throw Object.assign(Error('Войдите снова'),{status:401})},[{id:'first'},{id:'second'}]);
 try{await client.start();await client.scan();assert.match(client.state.error,/Войдите/);assert.equal(client.state.rows.filter(row=>row.eligible).length,0)}finally{await client.stop()}
});

test('screening deadline never turns a late unread history into an eligible chat',async()=>{
 const slow=deferred(),timers=new Map();let next=0,screens=0;
 const client=Personal.create({getIdentity:async()=>({id:'actor'}),loadQueue:async()=>({mineCount:0,rows:[{id:'slow'}]}),
  loadContext:()=>slow.promise,visible:()=>true,historyTimeout:20,
  schedule:(fn,delay)=>{timers.set(++next,{fn,delay});return next},clear:id=>timers.delete(id),
  send:async({args})=>{if(args.action==='screen')screens++;return{ok:true,active:args.action!=='personal_stop',max_dialogs:0}}});
 try{await client.start();const scan=client.scan();await flush();assert.equal(timers.size,1);[...timers.values()][0].fn();await scan;
  assert.equal(client.state.rows[0].eligible,false);assert.match(client.state.rows[0].reason,/долго/);
  slow.resolve({convId:'slow',messages:[]});await flush();assert.equal(screens,0);assert.equal(client.state.rows[0].eligible,false);
 }finally{await client.stop()}
});

test('confirmed takeover during a history refresh remains paused after the late read',async()=>{
 const pending=deferred();let calls=0;
 const observer=Observer.create({list:async()=>({items:[{id:'chat',state:'waiting',operator_id:'actor',version:1}],more:false}),
  loadContext:()=>{calls++;return pending.promise},takeover:async()=>({id:'chat',operator_id:'actor',state:'paused',version:2})});
 const refresh=observer.refresh();await flush();await observer.takeover('chat');
 const paused=observer.state.rows[0].state;pending.resolve({messages:[]});await refresh;
 assert.equal(paused,'paused');assert.equal(observer.state.rows[0].state,'paused');assert.equal(calls,1);
 await observer.refresh();assert.equal(observer.state.rows[0].state,'paused');
});

test('candidate focus has a bounded history wait and can retry after timeout',async()=>{
 const timers=new Map();let next=0,calls=0;const slow=deferred();
 const observer=Observer.create({listCandidates:async()=>({items:[{id:'candidate',state:'candidate',version:1}],more:false}),
  loadContext:()=>{calls++;return calls===1?slow.promise:Promise.resolve({messages:[]})},
  schedule:(fn,delay)=>{timers.set(++next,{fn,delay});return next},clear:id=>timers.delete(id),historyTimeout:20});
 await observer.source('incoming');observer.focus('candidate');await flush();
 const bounded=timers.size===1;if(bounded){[...timers.values()][0].fn();await flush()}
 const row=observer.state.rows[0],error=row.readError;observer.focus('candidate');await flush();
 slow.resolve({messages:[{body:'late obsolete result'}]});await flush();
 assert.equal(bounded,true,'Focused history had no deadline');assert.match(error,/долго/);
 assert.equal(calls,2);assert.deepEqual(row.ctx,{messages:[]});assert.equal(row.loading,false);
});

test('polling during focused history read keeps the same pending card and displays the result',async()=>{
 const slow=deferred();let calls=0;
 const observer=Observer.create({listCandidates:async()=>({items:[{id:'candidate',state:'candidate',version:1}],more:false}),
  loadContext:()=>{calls++;return slow.promise}});
 await observer.source('incoming');observer.focus('candidate');await flush();await observer.refresh();
 slow.resolve({messages:[{id:'fresh-message',body:'Текущий клиентский вопрос'}]});await flush();
 assert.equal(calls,1);assert.equal(observer.state.rows[0].ctx?.messages[0]?.id,'fresh-message');
});

test('a new candidate message invalidates the old focused context and reads fresh history',async()=>{
 let version=1,calls=0;
 const observer=Observer.create({listCandidates:async()=>({items:[{id:'candidate',state:'candidate',version}],more:false}),
  loadContext:async()=>({messages:[{id:'read-'+(++calls)}]})});
 await observer.source('incoming');observer.focus('candidate');await flush();assert.equal(calls,1);
 version++;await observer.refresh();
 assert.equal(calls,2);assert.equal(observer.state.rows[0].ctx.messages[0].id,'read-2');
});
