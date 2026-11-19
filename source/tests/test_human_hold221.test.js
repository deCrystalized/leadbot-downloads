'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Workflow=require('../ext/workflow'),Runner=require('../ext/assistant-runner');
const Native=require('../ext/assistant-native');
function fixture(){
 const db=new Map(),calls=[],native={ok:true,id:'chat',operator_id:'actor',principal_id:'principal',state:'waiting',version:1};let previews=0;
 const deps={operator:()=> 'actor',visible:()=>true,read:async k=>db.get(k),save:async(k,v)=>db.set(k,structuredClone(v)),lock:async(_k,fn)=>fn(),
  pauseForHuman:async()=>{calls.push('native-pause');native.state='paused';native.version++;return structuredClone(native)},
  snapshot:async()=>({operatorId:'actor',active:true,mineCount:0,ctx:{convId:'chat',assigneeId:'actor',revision:'r1'}}),
  plan:async()=>({ok:true,eligible:true,operator_id:'actor',scope:'mine',step:'reply',revision:'r1',operation_id:'op'}),
  pending:async()=>[],preview:async()=>{previews++;return{ok:true,needs_operator:true,reason:'Настоящая проверка человеком'}}};
 let workflow=Workflow.create(deps);const timers=new Map();let next=0;
 const runner=Runner.create({active:()=>true,visible:()=>true,setMode:async()=>({ok:true,auto_enabled:true}),stopWorkflow:()=>workflow.stop(),
  scan:async()=>{const hold=await workflow.held?.('chat','actor');return[{id:'chat',eligible:!hold}]},
  park:(id,result)=>workflow.park(id,result,'actor'),step:id=>workflow.step(id),inspect:id=>workflow.inspect(id),
  schedule:(fn,delay)=>{timers.set(++next,{fn,delay});return next},clear:id=>timers.delete(id)});
 return{db,calls,native,deps,runner,get workflow(){return workflow},get previews(){return previews},restart:()=>{workflow=Workflow.create(deps)}};
}

test('true human handoff parks once across timers, messages and controller restart until explicit return',async()=>{
 const f=fixture();try{await f.runner.start('auto');await f.runner.tick();f.restart();await f.runner.tick();
  assert.equal(f.previews,1);assert.deepEqual(f.calls,['native-pause']);assert.equal(f.native.state,'paused');
  const hold=await f.workflow.held('chat','actor');assert.equal(hold.state,'held');assert.equal(hold.reason,'Настоящая проверка человеком');
  await Workflow.releaseHumanHold(f.deps,'actor','chat',{...f.native,state:'waiting',version:f.native.version+1});
  f.native.state='waiting';f.native.version++;await f.runner.tick();assert.equal(f.previews,2);assert.equal(f.calls.length,2);
 }finally{f.runner.stop()}
});

test('another actor or stale native receipt cannot clear the human hold or unknown write journal',async()=>{
 const f=fixture();await f.workflow.park('chat',{step:'handoff',reason:'Проверить'},'actor');
 const unknown='workflow:actor:chat:reply:old';f.db.set(unknown,{state:'unknown',kind:'reply'});
 for(const proof of [{...f.native,operator_id:'other',state:'waiting',version:9},{...f.native,state:'waiting'},
                      {...f.native,id:'other',state:'waiting',version:9}])await assert.rejects(Workflow.releaseHumanHold(f.deps,'actor','chat',proof));
 assert.equal((await f.workflow.held('chat','actor')).state,'held');assert.equal(f.db.get(unknown).state,'unknown');
});

test('occupied manual tab yields passive wait without model, persistent handoff or pause transport',async()=>{
 const f=fixture();f.deps.snapshot=async()=>{throw Object.assign(Error('Ручная работа открыта'),{code:'manual_occupied'})};
 try{await f.runner.start('auto');assert.equal(f.runner.state.rows[0].step,'wait');assert.equal(f.runner.state.rows[0].needs_operator,false);
  assert.equal(f.previews,0);assert.deepEqual(f.calls,[]);assert.equal(f.db.size,0);
 }finally{f.runner.stop()}
});

test('rehearsal never parks or changes a real native assignment',async()=>{
 const f=fixture();try{await f.runner.start('review');assert.equal(f.previews,1);assert.deepEqual(f.calls,[]);assert.equal(f.db.size,0)}finally{f.runner.stop()}
});

test('a failed durable hold stops auto instead of looping or silently retrying the same dialogue',async()=>{
 const f=fixture();f.deps.save=async()=>{throw Error('Storage unavailable')};
 try{await f.runner.start('auto');assert.equal(f.runner.state.mode,'stopped');assert.equal(f.previews,1);assert.deepEqual(f.calls,[])}finally{f.runner.stop()}
});

test('native pause accepts the actual versioned API receipt without an invented ok field',async()=>{
 const calls=[],job={id:'chat',operator_id:'actor',principal_id:'admin',state:'waiting',version:3};
 const api=Native.create({operator:()=> 'actor',get:async()=>job,
  post:async(path,body)=>{calls.push([path,body]);return{...job,state:'paused',version:4}}});
 const receipt=await api.pauseForHuman('chat');assert.equal(receipt.ok,true);assert.equal(receipt.state,'paused');
 assert.equal(receipt.version,4);assert.deepEqual(calls[0][1],{operator_id:'actor',version:3});
});

test('changed native actor, CID or stale version cannot confirm a durable human pause',async()=>{
 for(const changed of [{operator_id:'other'},{id:'other'},{state:'waiting'},{version:3}]){
  const job={id:'chat',operator_id:'actor',principal_id:'admin',state:'waiting',version:3};
  const api=Native.create({operator:()=> 'actor',get:async()=>job,post:async()=>({...job,state:'paused',version:4,...changed})});
  await assert.rejects(api.pauseForHuman('chat'));
 }
});

test('an already paused native job is confirmed without another takeover request',async()=>{
 const api=Native.create({operator:()=> 'actor',get:async()=>({id:'chat',operator_id:'actor',state:'paused',version:7}),
  post:async()=>assert.fail('Do not repeat takeover')});
 assert.equal((await api.pauseForHuman('chat')).ok,true);
});

test('actual native handoff receipt can release only the matching confirmed local hold',async()=>{
 const f=fixture();await f.workflow.park('chat',{step:'handoff',reason:'Проверка'},'actor');
 const api=Native.create({post:async()=>({...f.native,state:'waiting',version:f.native.version+1})});
 const receipt=await api.handoff('chat','actor','actor');
 assert.equal(await Workflow.releaseHumanHold(f.deps,'actor','chat',receipt),true);
 assert.equal(await f.workflow.held('chat','actor'),null);
});

test('a failed native pause preserves the durable hold and cannot be retried by a timer',async()=>{
 const f=fixture();f.deps.pauseForHuman=async()=>{f.calls.push('failed-pause');throw Error('Unknown control result')};
 await assert.rejects(f.workflow.park('chat',{step:'handoff',reason:'Проверка'},'actor'));
 f.restart();const hold=await f.workflow.held('chat','actor');assert.equal(hold.native_sync,'unknown');
 await f.workflow.park('chat',{step:'handoff',reason:'Проверка'},'actor');assert.deepEqual(f.calls,['failed-pause']);
});
