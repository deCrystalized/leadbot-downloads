'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function background(storage,fetch){
 const code=fs.readFileSync(require.resolve('../ext/background'),'utf8');
 const a=code.slice(code.indexOf('const НУЖЕН_ТОКЕН'),code.indexOf('// устройство —'));
 const b=code.slice(code.indexOf('async function мозгРаз('),code.indexOf('/* TELEGRAM —'));
 const s={chrome:{storage:{local:{get:async k=>{if(storage.fail)throw Error('storage unavailable');return{[k]:storage[k]}},set:async o=>Object.assign(storage,o),remove:async k=>delete storage[k]}}},
  CONFIG:{brainUrl:'https://fixture.invalid'},fetch,Date,Promise,AbortController,setTimeout,clearTimeout,
  СРОКИ:{иначе:1000},ЛЕЖИТ:{до:0},ВЕРСИЯ_API:'2.0.0',устройство:async()=>'offline',мозгЖив:()=>{},мозгЛежит:r=>r,запомнитьРежим:()=>{},текстОшибки:()=> 'Ошибка связи'};
 vm.createContext(s);vm.runInContext(a+b+';globalThis.api={access:доступ,one:мозгРаз};',s);return s.api;
}
const response=(status,body)=>({status,text:async()=>JSON.stringify(body)});
test('storage failure is distinct from an absent personal token',async()=>{
 const api=background({fail:true},async()=>{throw Error('must not fetch')});
 await assert.rejects(api.access(),e=>e.code==='storage');
});
test('a successful status rechecks a previously rejected token once for concurrent callers',async()=>{
 const token='test-only-token',storage={brainToken:token,brainTokenBad:token.length+':'+token.slice(0,3)+'…'+token.slice(-4)};let calls=0;
 const api=background(storage,async()=>{calls++;await new Promise(r=>setImmediate(r));return response(200,{ok:true,mode:'normal'})});
 assert.deepEqual(await Promise.all([api.access(),api.access(),api.access()]),[true,true,true]);assert.equal(calls,1);assert.equal(storage.brainTokenBad,undefined);
});
test('an upstream token error and a proxy 401 do not revoke the personal brain token',async()=>{
 for(const [status,body] of [[200,{ok:false,error:'token'}],[401,{error:'upstream authentication'}]]){
  const storage={brainToken:'test-only-token'},api=background(storage,async()=>response(status,body));
  const [r]=await api.one('tg',{});assert.notEqual(r.code,'token');assert.equal(storage.brainTokenBad,undefined);
 }
});
test('a genuine brain auth rejection remains blocked and says rejected, not missing',async()=>{
 const storage={brainToken:'test-only-token'},api=background(storage,async()=>response(401,{ok:false,code:'token'}));
 const [r]=await api.one('status',{});assert.equal(r.code,'token');assert.equal(r.token_state,'rejected');assert.ok(storage.brainTokenBad);
 assert.equal(await api.access(),false);
});
test('unrelated successful local operations and dismissals do not respawn an auth notification',()=>{
 const code=fs.readFileSync(require.resolve('../ext/content'),'utf8'),start=code.indexOf('  const МОЗГ_ЭКРАН'),end=code.indexOf('  const ЛИМИТ_ЗАПАС',start);
 const notes=[],s={Date,chrome:{storage:{local:{get:async()=>({})}}},h:()=>({}),тост:o=>{const el={isConnected:true,remove(){this.isConnected=false}};notes.push({o,el});return el}};
 vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.reply=мозгОтвет;',s);
 s.reply({ok:false,code:'token',token_state:'rejected'});s.reply({ok:true});notes[0].el.isConnected=false;s.reply({ok:false,code:'token',token_state:'rejected'});
 assert.equal(notes.length,1);assert.equal(notes[0].o.позже,false);
 s.reply({ok:true,auth_validated:true});s.reply({ok:false,code:'token'});assert.equal(notes.length,2);
});
