'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=process.env.LEADBOT_UI_GRAPH_ROOT||path.join(__dirname,'../ext');
const source=fs.readFileSync(path.join(root,'content.js'),'utf8');
const Extract=require(path.join(root,'extract.js'));

function helpers(){
 const scope={LC_EXTRACT:Extract,ПОЯС_ДИАЛОГА:new Map(),
  поясОбъявления:()=>'',объявлениеДиалога:c=>c.item||{},
  заявкаLC:c=>c.crm_request_id?{id:c.crm_request_id}:null,
  исход:(base,st,why,extra)=>({...base,st,why,...extra}),
  ctxOf:()=>{throw Error('reached_remaining_readiness_checks')}};
 vm.createContext(scope);
 for(const [start,end]of [
  ['  const сообщенияРазбора =','  // объявление и канал-источник'],
  ['  const ОТКАЗ_ОПЕРАТОРА =','  /* ЛИД-БОТ:'],
  ['  async function разобратьГотовность(','  /* Клиент с уже созданной']]){
  const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a,start);
  vm.runInContext(source.slice(a,b),scope);
 }
 return scope;
}
const refusal=changes=>({id:'staff-refusal',direction:'out',sender_type:'operator',
 body:'К сожалению, не смогу вам помочь.',...changes});

for(const status of ['delivered','read','sent',''])test('genuine staff refusal remains a cautious stop: '+(status||'legacy unspecified delivery'),()=>{
 assert.ok(helpers().отказалОператор([refusal({delivery_status:status})]));
});
for(const status of ['pending','queued','sending','failed','error','cancelled','canceled'])test('undelivered staff refusal cannot stop readiness: '+status,()=>{
 assert.equal(helpers().отказалОператор([refusal({delivery_status:status})]),'');
});
for(const changes of [
 {sender_type:'system'},{sender_type:'bot'},{sender_type:'avito'},
 {sender_type:'client'},{role:'system'},{speaker_role:'bot'}
])test('nonstaff source cannot become staff refusal: '+JSON.stringify(changes),()=>{
 assert.equal(helpers().отказалОператор([refusal({delivery_status:'delivered',...changes})]),'');
});
for(const direction of ['note','in','system'])test('nonoutbound refusal has no outbound authority: '+direction,()=>{
 assert.equal(helpers().отказалОператор([refusal({direction,delivery_status:'delivered'})]),'');
});
test('a quotation does not become the staff current refusal',()=>{
 assert.equal(helpers().отказалОператор([refusal({delivery_status:'delivered',
  body:'Сосед написал: «К сожалению, не смогу вам помочь».'})]),'');
});
for(const body of [
 'Если не смогу приехать, предупрежу.',
 'Не смогу сегодня, давайте завтра в 12.',
 'К сожалению, в 10 не смогу, могу в 12.'
])test('existing conditional/time counteroffer stays distinct: '+body,()=>{
 assert.equal(helpers().отказалОператор([refusal({delivery_status:'delivered',body})]),'');
});
test('a subsequent genuine staff alternative retains its priority',()=>{
 assert.equal(helpers().отказалОператор([refusal({delivery_status:'delivered'}),
  refusal({id:'alternative',delivery_status:'delivered',body:'Завтра в 12 можем.'})]),'');
});
test('a quoted alternative cannot erase a genuine staff refusal',()=>{
 assert.ok(helpers().отказалОператор([refusal({delivery_status:'delivered'}),
  refusal({id:'quotation',delivery_status:'delivered',body:'Сосед написал: «Завтра в 12 можем».'})]));
});
test('a genuine current refusal after a quotation remains visible',()=>{
 assert.ok(helpers().отказалОператор([refusal({delivery_status:'delivered',
  body:'Сосед написал: «Завтра в 12 можем». Но я не смогу вам помочь.'})]));
});
test('existing CRM order remains ahead of audio and staff refusal',async()=>{
 const r=await helpers().разобратьГотовность({conv:{crm_request_id:'9000001'},msgs:[refusal({delivery_status:'delivered'})]},
  {id:'synthetic-existing261'},{});
 assert.equal(r.st,'exists');assert.equal(r.crmLC,'9000001');
});
test('genuine running audio is still awaited before readiness',async()=>{
 const r=await helpers().разобратьГотовность({conv:{},msgs:[{id:'audio',direction:'in',sender_type:'client',body:'',
  voice_transcript_status:'running',created_at:new Date().toISOString(),attachments:[{kind:'audio',avito_type:'voice'}]}]},
  {id:'synthetic-audio261'},{});
 assert.equal(r.st,'wait');assert.equal(r.retry,true);
});
test('actual readiness continues past a pending refusal without any external action',async()=>{
 await assert.rejects(helpers().разобратьГотовность({conv:{},msgs:[refusal({delivery_status:'pending'})]},
  {id:'synthetic-pending261'},{}),/reached_remaining_readiness_checks/);
});
test('actual readiness preserves a genuine delivered staff refusal',async()=>{
 const r=await helpers().разобратьГотовность({conv:{},msgs:[refusal({delivery_status:'delivered'})]},
  {id:'synthetic-delivered261'},{});
 assert.equal(r.st,'refused');assert.match(r.why,/оператор уже отказал/);
});
