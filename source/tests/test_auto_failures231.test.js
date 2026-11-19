'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Runner=require('../ext/assistant-runner');
for(const code of ['research_stopped','research_disabled','research_configuration','native_source_unavailable',
 'operator_identity','personal_identity','personal_expired','auto_disabled']){
 test('technical '+code+' stops the cycle and resets review without parking a customer',async()=>{
  const calls=[];const ui=Runner.create({visible:()=>true,active:()=>true,
   setMode:async mode=>{calls.push('mode:'+mode);return{ok:true,auto_enabled:mode==='auto'}},
   stopWorkflow:()=>calls.push('fence'),scan:async()=>[{id:'first',eligible:true},{id:'second',eligible:true}],
   step:async()=>{throw Object.assign(Error('Synthetic technical failure'),{code})},
   park:()=>assert.fail('A technical stop must not become native customer takeover'),schedule:()=>assert.fail('No automatic retry timer'),clear:()=>{}});
  await ui.start('auto');assert.equal(ui.state.mode,'stopped');assert.equal(ui.state.error,'Synthetic technical failure');
  assert.ok(calls.includes('mode:review'));const count=calls.length;await ui.tick();assert.equal(calls.length,count);
 });
}
test('server busy waits passively while genuine client handoff still parks',async()=>{
 for(const code of ['busy','client_case']){
  const parked=[];const ui=Runner.create({visible:()=>true,active:()=>true,
   setMode:async()=>({ok:true,auto_enabled:true}),stopWorkflow:()=>{},
   scan:async()=>[{id:'first',eligible:true}],step:async()=>{throw Object.assign(Error('case'),{code})},
   park:async(id,r)=>{parked.push(id);return r},schedule:()=>1,clear:()=>{}});
  try{await ui.start('auto');assert.equal(ui.state.rows[0].step,code==='busy'?'wait':'handoff');
   assert.equal(parked.length,code==='busy'?0:1)}finally{ui.stop()}
 }
});
