'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const adapter=require('../ext/assistant-native');
const fs=require('node:fs'),vm=require('node:vm');
const P='22222222-2222-4222-8222-222222222222',O='11111111-1111-4111-8111-111111111111';
const Q='33333333-3333-4333-8333-333333333333',RUN='44444444-4444-4444-8444-444444444444';
function status(changes={}){return {principal_id:P,state:'stopped',mode:'rehearsal',generation:0,run_id:null,operator_id:null,
 auto_enabled:false,native_supported:true,configured:true,worker_ready:true,start_available:true,
 observer_disconnect_stops_run:false,...changes}}
function fixture(){
 const f={value:status(),calls:[],events:[],now:100000,principal:P,operator:O,timers:new Map(),nextTimer:0};
 f.get=async path=>{f.calls.push(['GET',path]);return structuredClone(f.value)};
 f.post=async(path,body)=>{
  f.calls.push(['POST',path,body]);
  assert.equal(body.expected_principal_id,P);assert.equal(body.expected_generation,f.value.generation);
  f.value=status({state:path.endsWith('/start')?'running':'stopped',mode:'auto',run_id:RUN,
    operator_id:body.operator_id||f.value.operator_id,generation:f.value.generation+1,
    auto_enabled:path.endsWith('/start')});return structuredClone(f.value);
 };
 f.ui=adapter.createRun({get:path=>f.get(path),post:(path,body)=>f.post(path,body),
  identity:async()=>({id:f.principal,role:'admin'}),principal:()=>f.principal,operator:()=>f.operator,
  now:()=>f.now,onChange:s=>f.events.push(structuredClone(s)),schedule:fn=>{const n=++f.nextTimer;f.timers.set(n,fn);return n},
  clear:id=>f.timers.delete(id)});
 return f;
}
test('native observer read/open/close never starts or stops the server Run',async()=>{
 const f=fixture();await f.ui.inspect();f.ui.watch();await new Promise(r=>setImmediate(r));f.ui.unwatch();
 assert.equal(f.ui.state.view.state,'stopped');assert.ok(f.calls.length);assert.ok(f.calls.every(c=>c[0]==='GET'));
 assert.equal(f.timers.size,0);
});
test('explicit start confirmation sends only actual owner expectation author and generation',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();assert.equal(f.calls.filter(c=>c[0]==='POST').length,0);
 await f.ui.start(ticket);assert.equal(f.ui.state.view.auto_enabled,true);
 assert.deepEqual(f.calls.find(c=>c[0]==='POST').slice(1),['/bot-dialogs/assistant/native-run/start',
  {expected_principal_id:P,operator_id:O,expected_generation:0}]);
 f.ui.unwatch();assert.equal(f.ui.state.view.state,'running');
 assert.equal(f.calls.filter(c=>c[0]==='POST').length,1);
});
test('lost read retains last confirmed running state and marks it stale',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',run_id:RUN,operator_id:O,generation:4,auto_enabled:true});
 await f.ui.inspect();f.get=async()=>{throw Error('synthetic read loss')};
 await assert.rejects(f.ui.inspect());assert.equal(f.ui.state.view.auto_enabled,true);assert.equal(f.ui.state.stale,true);
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('selected author change invalidates an old confirmation without POST',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();f.operator=Q;
 await assert.rejects(f.ui.start(ticket));assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('generation change in another tab invalidates the exact start confirmation',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();f.value=status({generation:2,run_id:RUN,operator_id:O});
 await assert.rejects(f.ui.start(ticket));assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('expired or invented confirmation never becomes a launch',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();await assert.rejects(f.ui.start({...ticket}));
 const next=await f.ui.prepareStart();f.now+=60001;await assert.rejects(f.ui.start(next));
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('unknown start acknowledgement is observed and never automatically resubmitted',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();let attempts=0;
 f.post=async()=>{attempts++;throw Error('synthetic lost acknowledgement')};
 await assert.rejects(f.ui.start(ticket));assert.ok(f.ui.state.unknown);await f.ui.inspect();
 await assert.rejects(f.ui.start(ticket));assert.equal(attempts,1);
 f.value=status({generation:1,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 await f.ui.inspect();assert.equal(f.ui.state.unknown,null);assert.equal(f.ui.state.view.state,'running');
});
test('explicit stop uses current Run generation, not selected replacement author',async()=>{
 const f=fixture();f.value=status({generation:3,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 await f.ui.inspect();f.operator=Q;await f.ui.stop();
 const call=f.calls.find(c=>c[0]==='POST');assert.deepEqual(call.slice(1),['/bot-dialogs/assistant/native-run/stop',
  {expected_principal_id:P,expected_generation:3}]);assert.equal(f.ui.state.view.state,'stopped');
});
test('simultaneous stop clicks send one command for the displayed Run',async()=>{
 const f=fixture();f.value=status({generation:3,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 await f.ui.inspect();const releases=[];let attempts=0;f.post=async()=>{attempts++;await new Promise(r=>releases.push(r));
  return status({generation:4,state:'stopped',mode:'auto',run_id:RUN,operator_id:O})};
 const both=Promise.allSettled([f.ui.stop(),f.ui.stop()]);await new Promise(r=>setImmediate(r));
 for(const release of releases)release();const results=await both;
 assert.equal(attempts,1);assert.equal(results[0].status,'fulfilled');assert.equal(results[1].status,'rejected');
});
test('an old displayed Stop cannot silently switch to a later launch in another tab',async()=>{
 const f=fixture();f.value=status({generation:3,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 await f.ui.inspect();f.value=status({generation:5,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 const posts=[];f.post=async(path,body)=>{posts.push(body);const error=Error('Synthetic generation changed');error.status=409;throw error};
 await assert.rejects(f.ui.stop());assert.equal(posts.length,1);assert.equal(posts[0].expected_generation,3);
 assert.equal(f.value.generation,5);assert.equal(f.value.state,'running');
 await f.ui.inspect();assert.equal(posts.length,1);assert.equal(f.ui.state.view.generation,5);
});
test('changed authenticated principal response cannot become the old account state',async()=>{
 const f=fixture();f.value=status({principal_id:Q});await assert.rejects(f.ui.inspect());assert.equal(f.ui.state.view,null);
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('no browser-auto fallback on unavailable or malformed native status',async()=>{
 for(const value of [null,{active:true,auto_enabled:true},status({observer_disconnect_stops_run:true})]){
  const f=fixture();f.value=value;await assert.rejects(f.ui.prepareStart());assert.ok(f.calls.every(c=>c[0]==='GET'));
 }
});
test('server Run already active is observed without a replacement start',async()=>{
 const f=fixture();f.value=status({generation:7,state:'running',mode:'auto',run_id:RUN,operator_id:O,auto_enabled:true});
 await assert.rejects(f.ui.prepareStart());assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('closing observation rejects its late read without any server stop',async()=>{
 const f=fixture();let release;f.get=()=>new Promise(r=>release=r);f.ui.watch();
 await new Promise(r=>setImmediate(r));f.ui.unwatch();release(status({state:'running',mode:'auto',run_id:RUN,
  operator_id:O,generation:8,auto_enabled:true}));await new Promise(r=>setImmediate(r));
 assert.equal(f.ui.state.view,null);assert.equal(f.timers.size,0);
});
test('duplicate watches share one status read and one bounded poll timer',async()=>{
 const f=fixture();f.ui.watch();f.ui.watch();await new Promise(r=>setImmediate(r));
 assert.equal(f.calls.length,1);assert.equal(f.timers.size,1);f.ui.unwatch();assert.equal(f.timers.size,0);
});
test('closing during a submitted launch preserves uncertainty without a stuck busy state',async()=>{
 const f=fixture(),ticket=await f.ui.prepareStart();let release;
 f.post=async()=>new Promise(r=>release=r);const launch=f.ui.start(ticket);
 await new Promise(r=>setImmediate(r));f.ui.unwatch();
 release(status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:1,auto_enabled:true}));
 await launch;assert.equal(f.ui.state.busy,false);assert.ok(f.ui.state.unknown);
 f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:1,auto_enabled:true});
 await f.ui.inspect();assert.equal(f.ui.state.unknown,null);assert.equal(f.ui.state.view.state,'running');
});
test('an account change clears the old local view and cannot stop its Run',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:3,auto_enabled:true});
 await f.ui.inspect();f.principal=Q;await assert.rejects(f.ui.inspect());
 assert.equal(f.ui.state.view,null);assert.equal(f.ui.state.unknown,null);assert.ok(f.calls.every(c=>c[0]==='GET'));
 assert.equal(f.events.at(-1).view,null);assert.equal(f.events.at(-1).stale,true);
 f.value=status({principal_id:Q});await f.ui.inspect();assert.equal(f.ui.state.view.principal_id,Q);
});
test('lost stop acknowledgement is observed without a second POST',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:3,auto_enabled:true});
 await f.ui.inspect();let attempts=0;f.post=async()=>{attempts++;throw Error('synthetic lost stop reply')};
 await assert.rejects(f.ui.stop());await f.ui.inspect();await assert.rejects(f.ui.stop());assert.equal(attempts,1);
 f.value=status({state:'stopped',mode:'auto',operator_id:O,run_id:RUN,generation:4});
 await f.ui.inspect();assert.equal(f.ui.state.unknown,null);assert.equal(f.ui.state.view.state,'stopped');
});

const source=fs.readFileSync(require.resolve('../ext/assistant-ui'),'utf8');
function nodes(tree){return [tree,...(tree?.kids||[]).filter(x=>x&&typeof x==='object').flatMap(nodes)]}
function ui(f){
 const calls=[],h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
 const p={principal:P,operator:O,name:'Автор',active:false,busy:false,auto:false,error:'',
  authors:[{id:P,full_name:'Администратор'},{id:O,full_name:'Автор'}]};
 const runner={state:{mode:'stopped'},stop:()=>{calls.push('stop-browser-loop');runner.state.mode='stopped'},
  start:async mode=>{calls.push('browser-start:'+mode);if(mode==='auto')assert.fail('No native Auto through browser runner')}};
 const personal={state:p,nativeRun:f.ui,stop:async()=>calls.push('disconnect-view'),start:async()=>calls.push('connect-view'),
  selectAuthor:async id=>{calls.push('select:'+id);p.operator=id},setMode:async()=>assert.fail('No legacy auto mode')};
 const c={h,Date,nativeRequested:true,nativeRun:f.ui,personal,runner,nativeSync:null,timer:10,
  deps:{onPersonalStart:async()=>calls.push('disable-local-auto-claim')},
  workflow:{stop:()=>calls.push('stop-local-workflow')},observer:{reset:()=>calls.push('reset-view'),refresh:async()=>calls.push('refresh-view')},
  state:{activation:null,error:'',epoch:0},draw:()=>{},clearInterval:()=>calls.push('clear-view-timer'),
  button:(text,onclick,disabled=false,main=false,key='')=>h('button',{onclick,disabled,key},text)};
 vm.createContext(c);
 for(const [start,end]of [
  ['    async function requestAuto(', '    async function openReviewedDialog('],
  ['    function nativeControls(', '    function observerControls('],
  ['    async function changeAuthor(', '    function personalView('],
  ['    function stop(endPersonal=', "    window.addEventListener('pagehide'"],
  ['    async function syncNativeObservation(', '    const style ='],
 ]){
  const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a,start);
  vm.runInContext(source.slice(a,b),c);
 }
 return {c,p,calls,controls:()=>c.nativeControls(p)};
}
test('actual panel start confirmation targets server control and never browser auto',async()=>{
 const f=fixture(),u=ui(f);await u.c.requestAuto();assert.ok(u.c.state.activation.native);
 assert.ok(f.calls.every(c=>c[0]==='GET'));await u.c.confirmAuto();
 assert.equal(f.ui.state.view.state,'running');assert.equal(f.calls.filter(c=>c[0]==='POST').length,1);
 assert.ok(u.calls.includes('disable-local-auto-claim'));
 assert.ok(!u.calls.includes('browser-start:auto'));
});
test('failed local auto-claim shutdown cannot silently launch the competing native Run',async()=>{
 const f=fixture(),u=ui(f);u.c.deps.onPersonalStart=async()=>{throw Error('Synthetic storage failure')};
 await u.c.requestAuto();await u.c.confirmAuto();assert.ok(u.c.state.error);
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('actual panel shows working server even when browser view is disconnected',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,auto_enabled:true});
 await f.ui.inspect();const u=ui(f),tree=u.controls(),text=JSON.stringify(tree);
 assert.ok(text.includes('Бот работает на сервере'));assert.ok(text.includes('Репетиция: отключена'));
 const button=nodes(tree).find(n=>n.attrs?.key==='observer-auto');assert.equal(button.kids[0],'Остановить авто');assert.equal(button.attrs.disabled,false);
 await button.attrs.onclick();assert.equal(f.ui.state.view.state,'stopped');
});
test('running Run with unavailable worker is stoppable but never green working',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,
  auto_enabled:true,worker_ready:false,start_available:false});
 await f.ui.inspect();const u=ui(f),tree=u.controls(),text=JSON.stringify(tree);
 assert.ok(!text.includes('Бот работает на сервере'));assert.ok(text.includes('работа обработчика не подтверждена'));
 assert.equal(nodes(tree).find(n=>n.attrs?.key==='observer-auto').attrs.disabled,false);
 assert.ok(!nodes(tree).some(n=>n.attrs?.class==='observer-session running'));
});
test('duplicate employee names keep ID disambiguation in the native author picker',async()=>{
 const f=fixture();await f.ui.inspect();const u=ui(f);u.p.authors=[{id:O,full_name:'Тёзка'},{id:Q,full_name:'Тёзка'}];
 const options=nodes(u.controls()).filter(n=>n.tag==='option');
 assert.equal(options.length,2);assert.notEqual(options[0].kids[0],options[1].kids[0]);
 assert.ok(options[0].kids[0].includes(O.slice(0,8)));assert.ok(options[1].kids[0].includes(Q.slice(0,8)));
 assert.equal(options[0].attrs.value,O);assert.equal(options[1].attrs.value,Q);
});
test('an active Run whose author is unavailable is not shown as a new author choice',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:Q,run_id:RUN,generation:2,auto_enabled:true});
 await f.ui.inspect();const u=ui(f);assert.ok(JSON.stringify(u.controls()).includes('Автор недоступен'));
 assert.equal(nodes(u.controls()).find(n=>n.attrs?.key==='observer-auto').attrs.disabled,false);
});
test('actual panel marks stale running status without claiming auto is off',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,auto_enabled:true});
 await f.ui.inspect();f.get=async()=>{throw Error('synthetic missing status')};await assert.rejects(f.ui.inspect());
 const u=ui(f),tree=u.controls();assert.ok(JSON.stringify(tree).includes('бот работал · связь потеряна'));
 assert.equal(nodes(tree).find(n=>n.attrs?.key==='observer-auto').kids[0],'Остановить авто');
});
test('a stored server Rehearsal Run is not displayed as working Auto',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'rehearsal',operator_id:O,run_id:RUN,generation:2});
 await f.ui.inspect();const u=ui(f),tree=u.controls(),text=JSON.stringify(tree);
 assert.ok(!text.includes('Бот работает на сервере'));assert.ok(text.includes('отправки выключены'));
 assert.equal(nodes(tree).find(n=>n.attrs?.key==='observer-auto').kids[0],'Остановить запуск');
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('actual panel close clears only observation and local resources',async()=>{
 const f=fixture(),u=ui(f);u.c.stop();await new Promise(r=>setImmediate(r));
 assert.ok(u.calls.includes('disconnect-view'));assert.ok(u.calls.includes('clear-view-timer'));
 assert.equal(f.calls.length,0);assert.equal(f.timers.size,0);
});
test('actual author change cannot migrate an active native Run',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,auto_enabled:true});
 await f.ui.inspect();const u=ui(f);await u.c.changeAuthor({currentTarget:{value:P}});
 assert.equal(u.p.operator,O);assert.ok(u.c.state.error);assert.ok(!u.calls.some(c=>c.startsWith('select:')));
});
test('actual Rehearsal cannot start while a native Run is active',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,auto_enabled:true});
 const u=ui(f);await u.c.startRunner('review');assert.ok(!u.calls.includes('browser-start:review'));assert.ok(u.c.state.error);
 assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('native module missing never falls back to browser Auto',async()=>{
 const f=fixture(),u=ui(f);u.c.nativeRun=null;await u.c.requestAuto();
 assert.ok(u.c.state.error);assert.ok(!u.calls.includes('browser-start:auto'));assert.equal(f.calls.length,0);
 assert.ok(JSON.stringify(u.controls()).includes('серверное управление не загружено'));
});
test('native status synchronizes only observation author, not the server Run',async()=>{
 const f=fixture();f.value=status({state:'running',mode:'auto',operator_id:O,run_id:RUN,generation:2,auto_enabled:true});
 await f.ui.inspect();const u=ui(f);u.p.operator=P;u.c.runner.state.mode='review';
 await u.c.syncNativeObservation();assert.equal(u.p.operator,O);const count=u.calls.length;
 await u.c.syncNativeObservation();assert.equal(u.calls.length,count);assert.ok(f.calls.every(c=>c[0]==='GET'));
});
