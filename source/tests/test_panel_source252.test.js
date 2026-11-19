'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{panelHarness}=require('./helpers/panel_harness236.cjs');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
const draft={ok:true,reply:'Уточните, пожалуйста, материал стены.',draft_id:'synthetic-draft',revision:'r1'};
test('delegated manual validation keeps the attested actor instead of dropping to legacy transport',async t=>{
 const h=await panelHarness({currentId:()=>'first',latestId:async()=>'m1',send:async a=>{
  if(a.action==='preview')return draft;
  if(a.action==='validate')return a.identity_proof==='synthetic-proof'&&a.operator_id==='11111111-1111-4111-8111-111111111111'?draft:{ok:false,error:'Attestation missing'};
 }});t.after(()=>h.stop());await h.ui.preview();
 assert.equal((await h.ui.validate()).reply,draft.reply);
 assert.equal(h.wires.find(a=>a.action==='validate').identity_proof,'synthetic-proof');
 assert.equal(h.wires.find(a=>a.action==='preview').operator_id,'11111111-1111-4111-8111-111111111111');
 assert.deepEqual(h.effects,[]);
});
test('delegated freshness observation uses the authenticated source path',async t=>{
 let last='m1';
 const h=await panelHarness({currentId:()=>'first',latestId:async()=>last,send:async a=>{
  if(a.action==='preview')return draft;
  if(a.action==='observe')return {ok:a.identity_proof==='synthetic-proof'};
 }});t.after(()=>h.stop());await h.ui.preview();last='m2';await h.refresh();
 const sent=h.wires.find(a=>a.action==='observe');assert.ok(sent);assert.equal(sent.identity_proof,'synthetic-proof');
 assert.equal(sent.operator_id,'11111111-1111-4111-8111-111111111111');
 assert.deepEqual(h.effects,[]);
});
test('an old dialogue freshness result cannot contaminate a newly opened dialogue',async t=>{
 let selected='first',hold=false,release;
 const h=await panelHarness({currentId:()=>selected,latestId:async()=>hold?new Promise(r=>{release=r}):'m1',
  send:async a=>a.action==='preview'?draft:a.action==='observe'?{ok:true}:undefined});
 t.after(()=>h.stop());await h.ui.preview();hold=true;const previous=h.refresh();await turn();
 assert.ok(release);selected='second';await h.ui.open();release('m2');await previous;
 assert.equal(h.ui.state.id,'second');assert.equal(h.ui.state.stale,false);
 assert.equal(h.wires.filter(a=>a.action==='observe').length,0);assert.deepEqual(h.effects,[]);
});
