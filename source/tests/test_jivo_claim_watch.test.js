'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),N=require('../ext/request-notes');
const code=fs.readFileSync(require.resolve('../ext/content'),'utf8');
function fixture(options={}){
 const {channel='jivo',direction='in',count=1,attachment=false,sender_type='customer'}=options;
 const hasClaim=Object.hasOwn(options,'hasClaim')?options.hasClaim:true;
 const calls=[],cards=[],deferred=new Map(),now=Date.now(),message={id:'in-1',direction,sender_type,body:attachment?'':'Спасибо',created_at:new Date(now).toISOString(),attachments:attachment?[{kind:'image',url:'synthetic://image'}]:[]};
 const cr={id:'1234567',dir:'mnc',at:now-10000,...(hasClaim===undefined?{}:{hasClaim})};
 const s={Date,LC_REQUEST_NOTES:N,W:{},ДОПИСКИ:deferred,ACT:{},LC_EXTRACT:{сКонтактом:m=>m.body,голосовое:()=>false},
  последнееИз:p=>p.items.at(-1),лента:async()=>({items:[message]}),деталь:async()=>({channel,account:{channel}}),
  convIdNow:()=> 'dialog',panel:{classList:{contains:()=>false}},
  показатьДописку:(...a)=>cards.push(a),markSeen:async()=>{},объявлениеДиалога:()=>({}),городОбъявления:()=>'',поясОбъявления:()=>'',
  send:async m=>{calls.push(m);return m.kind==='lcz-crm'?{ok:true,count}:{ok:true,important:false}},String};
 vm.createContext(s);vm.runInContext(code.slice(code.indexOf('  async function watchAdditions('),code.indexOf('  async function markSeen(')),s);
 return {s,calls,cards,cr};
}
test('a Jivo thank-you on an existing claim prepares a rule action before any neural importance classifier',async()=>{
 const f=fixture();await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,1);
 const r=f.cards[0][2];assert.equal(r.намерение,'jivo_claim_reply');assert.equal(r.rule_action,true);assert.equal(r.messageId,'in-1');assert.equal(f.calls.length,0);
 await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,1);
});
test('an attachment-only incoming message also requires the existing claim notice',async()=>{
 const f=fixture({attachment:true});await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,1);assert.equal(f.calls.length,0);
});
test('unknown claim is read from CRM; a positive result prepares and never creates or sends',async()=>{
 const f=fixture({hasClaim:undefined});await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,1);
 assert.deepEqual(f.calls.map(x=>[x.kind,x.op]),[['lcz-crm','claims']]);
});
test('a negative claim result does not fabricate an existing claim',async()=>{
 const f=fixture({hasClaim:undefined,count:0});await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,0);assert.ok(!f.calls.some(x=>x.kind==='lcz-tg'));
});
test('outgoing and MAX never create the Jivo-specific claim action',async()=>{
 for(const args of [{direction:'out'},{channel:'max_user'},{channel:'avito'}]){
  const f=fixture(args);await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,0);assert.ok(!f.calls.some(x=>x.kind==='lcz-tg'));
 }
});
test('an incoming system message is not treated as a customer reply',async()=>{
 const f=fixture({sender_type:'system'});await f.s.watchAdditions('dialog',f.cr);assert.equal(f.cards.length,0);assert.ok(!f.calls.some(x=>x.kind==='lcz-tg'));
});
