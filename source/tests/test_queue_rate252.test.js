'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {создать}=require('../extension-server/brain/index');
const {create}=require('../ext/assistant-runner');
test('the supported twelve-dialogue idle queue leaves room for control without hitting the real public limiter',async()=>{
 let now=Date.UTC(2026,9,30),timer,next=0,backend=0;
 const token='synthetic-capacity-token-not-real';
 const memory=new Map([['brain/tokens.json',{tokens:[{id:'synthetic',sha:crypto.createHash('sha256').update(token).digest('hex')}]}]]);
 const statuses=[];
 const brain=создать({env:{LEADBOT_SERVICE_TOKEN:'synthetic-service'},now:()=>now,sleep:async()=>{},log:()=>{},
  store:{get:async(k,d)=>structuredClone(memory.get(k)??d),put:async(k,v)=>memory.set(k,structuredClone(v))},
  запрос:async(url,options)=>{assert.equal(url,'http://127.0.0.1:8788/api/extension/assistant');backend++;return{ok:true,status:200,json:async()=>({ok:true})}}});
 async function read(action,id){
  const result=await brain({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'assistant',args:{action,ctx:{convId:id}}})});
  statuses.push({status:result.statusCode,at:now,action});const value=JSON.parse(result.body);
  if(!value.ok)throw Object.assign(Error(value.error),{code:value.code});return value;
 }
 const runner=create({visible:()=>true,active:()=>true,now:()=>now,
  schedule:(fn,delay)=>{timer={fn,delay,id:++next};return next},clear:id=>{if(timer?.id===id)timer=null},
  stopWorkflow:()=>{},setMode:async()=>({ok:true,auto_enabled:false}),
  scan:async()=>Array.from({length:12},(_,i)=>({id:'synthetic-'+i,eligible:true})),
  inspect:async id=>{await read('personal_plan',id);await read('research_status',id);return{step:'wait',needs_operator:false,research_state:'running'}}});
 try{
  await runner.start('review');
  for(let i=1;i<12;i++){
   now+=timer.delay;
   await read('personal_heartbeat','control');
   await runner.tick();
  }
  assert.equal(statuses.filter(x=>x.status===429).length,0);
  assert.equal(backend,12*12*2+11);assert.equal(runner.state.cycles,12);
  assert.ok(timer.delay<=20000);assert.ok(timer.delay>=12000);
  runner.wake({t:'message:new',id:'synthetic-1',from:'client'});assert.equal(timer.delay,800);
  runner.stop();assert.equal(timer,null);
 }finally{runner.stop()}
});
