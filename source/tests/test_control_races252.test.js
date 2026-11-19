'use strict';
// Pipe/server-control doubles only: no network, provider, real identity or writes.
const test=require('node:test'),assert=require('node:assert/strict');
const Personal=require('../ext/personal');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
function server(){
 let epoch=0,conn=0,seq=0,active=false,mode='review',nonce='initial-nonce-long-enough';
 const calls=[];let hold;
 const view=()=>({ok:true,active,execution_mode:mode,auto_enabled:active&&mode==='auto',
  auto_available:true,lease_seconds:45,mode_epoch:epoch,connection_epoch:conn,control_seq:seq,
  control_protocol:'ordered_v1',activation_nonce:nonce,policy_version:'synthetic-policy'});
 function apply(a){
  if(a.action==='personal_start'){active=true;mode='review';epoch++;conn=epoch;seq=0;nonce='nonce-'+epoch+'-long-enough-for-activation';return view()}
  if(!active)return{...view(),ok:false,error:'expired'};
  if(['personal_stop','personal_mode'].includes(a.action)){
   if(a.expected_mode_epoch!==undefined&&a.expected_mode_epoch!==epoch)return{...view(),stop_not_applied:true};
   if(a.connection_epoch!==undefined&&(a.connection_epoch!==conn||!Number.isSafeInteger(a.control_seq)||a.control_seq<=seq))return{...view(),control_not_applied:true};
   if(a.control_seq!==undefined)seq=a.control_seq;
  }
  if(a.action==='personal_stop'){active=false;mode='review';epoch++}
  if(a.action==='personal_mode'){mode=a.execution_mode;epoch++;nonce='nonce-'+epoch+'-long-enough-for-activation'}
  return view();
 }
 const send=async({args:a})=>{calls.push(structuredClone(a));if(hold?.action===a.action){const h=hold;hold=null;return new Promise(resolve=>{h.ready(()=>resolve(h.capture?{...h.value}:apply(a)))})}return apply(a)};
 function delay(action,{capture=false}={}){let release;hold={action,capture,value:capture?view():null,ready:f=>{release=f}};return()=>{assert.ok(release,'delayed operation dispatched');release()}}
 const client=()=>Personal.create({getIdentity:async()=>({id:'operator'}),visible:()=>true,send});
 return{client,delay,calls,view};
}
test('late old stop cannot kill a new same-browser connection',async()=>{
 const s=server(),old=s.client(),fresh=s.client();await old.start();const release=s.delay('personal_stop');const stopping=old.stop();await turn();await fresh.start();
 release();await stopping;
 try{assert.equal(s.view().active,true);assert.equal(fresh.state.active,true);assert.equal(s.view().execution_mode,'review')}
 finally{await fresh.stop()}
});
test('old heartbeat cannot restore old Auto flag or activation nonce',async()=>{
 const s=server(),ui=s.client();await ui.start();const release=s.delay('personal_heartbeat',{capture:true});const beat=ui.heartbeat();await turn();await ui.setMode('auto');const current=ui.state.nonce;release();await beat;
 try{assert.equal(ui.state.auto,true);assert.equal(ui.state.nonce,current);assert.equal(s.view().auto_enabled,true)}finally{await ui.stop()}
});
test('late old review cannot turn off a later activation after reconnect',async()=>{
 const s=server(),old=s.client(),fresh=s.client();await old.start();await old.setMode('auto');const release=s.delay('personal_mode');const review=old.setMode('review').catch(()=>{});await turn();await old.stop();await fresh.start();await fresh.setMode('auto');release();await review;
 try{assert.equal(s.view().auto_enabled,true);assert.equal(fresh.state.auto,true)}finally{await fresh.stop()}
});
test('an older stopped-mode response cannot defeat the latest intent in one connection',async()=>{
 const s=server(),ui=s.client();await ui.start();await ui.setMode('auto');const release=s.delay('personal_mode');const older=ui.setMode('review').catch(()=>{});await turn();await ui.setMode('review');await ui.setMode('auto');release();await older;
 try{assert.equal(s.view().auto_enabled,true);assert.equal(ui.state.auto,true)}finally{await ui.stop()}
});

test('Stop during activation wins even when Auto arrives at the server after Stop',async()=>{
 const s=server(),ui=s.client();await ui.start();const release=s.delay('personal_mode');
 const activating=ui.setMode('auto').catch(()=>{});await turn();await ui.stop();release();await activating;
 assert.equal(s.view().active,false);assert.equal(s.view().auto_enabled,false);assert.equal(ui.state.auto,false);
});
test('a stopped in-flight Start is cleaned before the same client starts its next connection',async()=>{
 const s=server(),ui=s.client(),release=s.delay('personal_start');
 const first=ui.start();await turn();await ui.stop();const next=ui.start();await turn();
 assert.equal(s.calls.filter(c=>c.action==='personal_start').length,1);
 release();await first;await next;
 try{
  assert.equal(s.view().active,true);assert.equal(ui.state.active,true);assert.equal(ui.state.auto,false);
  const cleanup=s.calls.find(c=>c.stop_reason==='stale_start_cleanup');
  assert.ok(Number.isSafeInteger(cleanup.connection_epoch));assert.equal(cleanup.control_seq,1);
 }finally{await ui.stop()}
});
test('a heartbeat from before a manual approval cannot restore the consumed activation nonce',async()=>{
 const s=server(),ui=s.client();await ui.start();const release=s.delay('personal_heartbeat',{capture:true});
 const beating=ui.heartbeat();await turn();ui.state.nonce='rotated-by-manual-approval';release();await beating;
 try{assert.equal(ui.state.nonce,'rotated-by-manual-approval')}finally{await ui.stop()}
});
