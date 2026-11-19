'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/observer');
const native=require('../ext/assistant-native');
const personal=require('../ext/personal');
const h=(tag,attrs,...kids)=>({tag,attrs,kids:kids.flat()});
function fixture(){
  const reads=[],writes=[],rows=Array.from({length:10},(_,i)=>({id:'c'+i,operator_id:'author',version:1,state:'waiting',last_message_at:'now'}));
  const deps={h,list:async({offset})=>({items:offset?[]:rows,more:offset===0}),
    loadContext:async id=>{reads.push(id);return {convId:id,clientName:'Клиент '+id,messages:Array.from({length:8},(_,n)=>({id:id+'m'+n,body:'Сообщение '+n,direction:n%2?'out':'in',delivery_status:'delivered'}))}},
    takeover:async row=>{writes.push(row);row.state='paused';row.version++}};
  return {ui:create(deps),deps,reads,writes,rows};
}
function nodes(tree){return [tree,...(tree?.kids||[]).filter(x=>x&&typeof x==='object').flatMap(nodes)]}
test('slow full history cannot hide the already fetched page or faster histories',async()=>{
 const f=fixture();let release;f.deps.loadContext=async id=>id==='c0'?new Promise(r=>release=r):{messages:[{body:id}]};
 const pending=f.ui.refresh();await new Promise(r=>setImmediate(r));
 assert.equal(f.ui.state.rows.length,10);assert.equal(f.ui.state.busy,true);assert.equal(f.ui.state.rows[1].ctx.messages[0].body,'c1');
 release({messages:[]});await pending;assert.equal(f.ui.state.busy,false);
});
test('a stuck history times out visibly without losing other cards or blocking future refresh',async()=>{
 const f=fixture();f.deps.historyTimeout=5;f.deps.loadContext=async id=>id==='c0'?new Promise(()=>{}):{messages:[]};
 await f.ui.refresh();assert.equal(f.ui.state.busy,false);assert.equal(f.ui.state.rows.length,10);assert.match(f.ui.state.rows[0].readError,/слишком долго/);
});
test('candidate queues show ten read-only previews and only focus reads a full history',async()=>{
 const f=fixture(),seen=[];f.deps.listCandidates=async(source,page)=>{seen.push([source,page.offset]);return{items:[{id:'free',state:'candidate',candidate_name:'Анна',previewMessages:[{body:'Preview'}]}],more:false,total:1}};
 await f.ui.source('incoming');assert.equal(f.reads.length,0);assert.deepEqual(f.writes,[]);assert.equal(f.ui.state.total,1);
 assert.ok(JSON.stringify(f.ui.view()).includes('Не передан боту'));assert.ok(JSON.stringify(f.ui.view()).includes('Превью · полная история'));
 await f.ui.takeover('free');assert.deepEqual(f.writes,[]);f.ui.focus('free');await new Promise(r=>setImmediate(r));assert.deepEqual(f.reads,['free']);assert.deepEqual(f.writes,[]);
});
test('changing author or source fences late history reads and clears attention cache',async()=>{
 const f=fixture();let release;f.deps.loadContext=()=>new Promise(r=>release=r);f.rows.splice(1);
 const pending=f.ui.refresh();await new Promise(r=>setImmediate(r));f.ui.update([{id:'c0',step:'handoff'}]);f.ui.reset();release({clientName:'Old author',messages:[]});await pending;
 assert.deepEqual(f.ui.state.rows,[]);assert.equal(f.ui.state.busy,false);assert.equal(f.ui.state.error,'');
});
test('an old failed draft followed by delivered conversation is not a current call for an operator',async()=>{
 const f=fixture();f.deps.loadContext=async()=>({messages:[{direction:'out',delivery_status:'failed'},{direction:'out',delivery_status:'delivered'},{direction:'in',sender_type:'system',body:'Status'}]});
 await f.ui.refresh();f.ui.filter('attention');assert.equal(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).length,0);
});
test('candidate API reads real selected-author queue without enrollment or author impersonation',async()=>{
 const paths=[],api=native.create({operator:()=> 'real-author',get:async path=>{paths.push(path);return{items:[{id:'free',client:{name:'А'},last_message:{body:'Hello'}}],page:{total:12}}},post:()=>assert.fail('Read only')});
 const incoming=await api.candidates('incoming',{limit:10,offset:0});assert.equal(incoming.items[0].state,'candidate');assert.equal(incoming.more,true);
 await api.candidates('mine',{limit:10,offset:10});assert.match(paths[0],/queue\?operator_id=real-author/);assert.match(paths[1],/tab=all&assignee_id=real-author&channel=avito/);
});
test('status filters use only enrolled page data and never fetch or claim a chat',async()=>{
  const f=fixture();f.rows[1].state='paused';f.rows[2].state='completed';await f.ui.refresh();
  f.ui.update([{id:'c0',step:'handoff',reason:'Требуется согласование',needs_operator:true}]);
  const before=[...f.reads];f.ui.filter('attention');
  assert.deepEqual(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).map(x=>x.attrs['data-observer-id']),['c0']);
  f.ui.filter('paused');assert.deepEqual(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).map(x=>x.attrs['data-observer-id']),['c1']);
  assert.deepEqual(f.reads,before);assert.deepEqual(f.writes,[]);
});
test('page search finds client and message text, retains query and supports an explicit reset',async()=>{
  const f=fixture();await f.ui.refresh();f.ui.search('КЛИЕНТ c4');
  assert.deepEqual(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).map(x=>x.attrs['data-observer-id']),['c4']);
  f.ui.search('Нет такого текста');const tree=f.ui.view();assert.ok(JSON.stringify(tree).includes('Нет подходящих диалогов'));
  nodes(tree).find(x=>x.tag==='button'&&x.kids.includes('Сбросить фильтры')).attrs.onclick();assert.equal(f.ui.state.query,'');assert.equal(f.ui.state.filter,'all');assert.equal(f.reads.length,10);assert.deepEqual(f.writes,[]);
});
test('partial history failure is visible and cannot appear as an all-clear status',async()=>{
  const f=fixture();f.deps.loadContext=async id=>{if(id==='c3')throw Error('Нет связи');return {messages:[]}};await f.ui.refresh();f.ui.filter('attention');
  assert.deepEqual(nodes(f.ui.view()).filter(x=>x.attrs?.['data-observer-id']).map(x=>x.attrs['data-observer-id']),['c3']);
  assert.ok(JSON.stringify(f.ui.view()).includes('История не обновилась. Нет связи'));assert.deepEqual(f.writes,[]);
});
test('double takeover clicks execute once while the native operation is in flight',async()=>{
  const f=fixture();let release;const pending=new Promise(resolve=>release=resolve);f.deps.takeover=async row=>{f.writes.push(row.id);await pending};
  await f.ui.refresh();const first=f.ui.takeover('c0');await f.ui.takeover('c0');assert.deepEqual(f.writes,['c0']);
  assert.ok(JSON.stringify(f.ui.view()).includes('Передаю…'));release();await first;
});
test('observer opens ten actual enrolled dialogues without write or activation',async()=>{
  const f=fixture();await f.ui.refresh();assert.equal(f.ui.state.rows.length,10);assert.equal(f.reads.length,10);assert.deepEqual(f.writes,[]);
  assert.equal(f.ui.view().tag,'section');assert.ok(JSON.stringify(f.ui.view()).includes('Сообщение 7'));
});
test('focus and grid keyboard only change observation, never start workflow',async()=>{
  const f=fixture();await f.ui.refresh();let prevented=0;
  f.ui.key({key:'0',target:{tagName:'DIV'},preventDefault:()=>prevented++});assert.equal(f.ui.state.focus,'c9');
  assert.ok(JSON.stringify(f.ui.view()).includes('Сообщение 0'));
  f.ui.key({key:'Escape',target:{tagName:'DIV'},preventDefault:()=>prevented++});assert.equal(f.ui.state.focus,'');assert.equal(prevented,2);
  f.ui.key({key:'1',target:{tagName:'TEXTAREA'},preventDefault:()=>assert.fail()});assert.equal(f.ui.state.focus,'');assert.deepEqual(f.writes,[]);
});
test('unchanged refresh uses metadata and completed dialogue stops history reads',async()=>{
  const f=fixture();await f.ui.refresh();await f.ui.refresh();assert.equal(f.reads.length,10);
  f.rows[0].state='completed';f.rows[0].crm_request_id='1234567';f.rows[0].last_message_at='later';
  f.rows[1].last_message_at='later';await f.ui.refresh();assert.equal(f.reads.length,11);assert.equal(f.reads.at(-1),'c1');
  f.ui.focus('c0');assert.ok(JSON.stringify(f.ui.view()).includes('Заявка №1234567'));assert.deepEqual(f.writes,[]);
});
test('manual takeover passes exact actor and optimistic version and cannot take completed card',async()=>{
  const f=fixture();await f.ui.refresh();await f.ui.takeover('c1');assert.equal(f.writes.length,1);assert.equal(f.writes[0].operator_id,'author');assert.equal(f.writes[0].version,2);
  f.rows[0].state='completed';await f.ui.refresh();await f.ui.takeover('c0');assert.equal(f.writes.length,1);
});
test('stopping observer discards pending reads, errors do not invent empty healthy state',async()=>{
  const f=fixture();f.deps.list=async()=>({items:'broken'});await f.ui.refresh();assert.match(f.ui.state.error,/список/);assert.deepEqual(f.writes,[]);
  f.ui.stop();await f.ui.refresh();assert.equal(f.reads.length,0);
});
function apiFixture(){
  const calls=[];let actor='author',job={id:'c1',operator_id:'author',state:'waiting',version:3};
  const api=native.create({operator:()=>actor,get:async path=>{calls.push(['GET',path]);if(!path.includes('?limit=')&&!path.endsWith('/c1'))throw Object.assign(Error('not enrolled'),{status:404});return path.includes('?limit=')?{items:[job],more:false}:job},
    post:async(path,body)=>{calls.push(['POST',path,body]);return path.endsWith('/identity')?{identity_proof:'opaque',expires_at:100,author:{id:body.operator_id}}:{...job,ok:true}},
    send:async()=>({ok:true,nonce:'native-challenge',browser_session:'actual-tab'})});
  return {api,calls,setActor:v=>actor=v,setJob:v=>job={...job,...v}};
}
test('native replies use dedicated delegation path and exact actual author/version',async()=>{
  const f=apiFixture();await f.api.reply('c1','Ответ','cmid');const call=f.calls.at(-1);
  assert.match(call[1],/\/assistant\/dialogs\/c1\/messages$/);assert.equal(call[2].operator_id,'author');assert.equal(call[2].version,3);assert.equal(call[2].client_message_id,'cmid');
});
test('native API404 or paused changed author cannot fall back to ordinary sending',async()=>{
  for(const change of [{state:'paused'},{state:'completed'},{operator_id:'other'}]){
    const f=apiFixture();f.setJob(change);await assert.rejects(f.api.reply('c1','Ответ','id'));assert.ok(f.calls.every(c=>c[0]==='GET'));
  }
  const api=native.create({operator:()=> 'author',get:async()=>{throw Error('404')},post:async()=>assert.fail('must not fall back')});await assert.rejects(api.reply('c1','Ответ','id'),/404/);
});
test('manual handoff enrolls one specific CID and does not activate auto',async()=>{
  const f=apiFixture();await f.api.handoff('c1','author','previous');assert.deepEqual(f.calls,[['POST','/bot-dialogs/assistant/dialogs/c1/handoff',{operator_id:'author',expected_assignee_id:'previous'}]]);
});
test('admin proof uses challenge tab binding; never asks for another employees token',async()=>{
  const f=apiFixture();const proof=await f.api.proof('author');assert.equal(proof.browser_session,'actual-tab');
  assert.deepEqual(f.calls.at(-1)[2],{operator_id:'author',nonce:'native-challenge',browser_session:'actual-tab'});
});
test('native enrollment list does not include all manually assigned human chats',async()=>{
  const f=apiFixture();const page=await f.api.queue({rows:[{id:'free'},{id:'c1',assigneeId:'author'},{id:'human',assigneeId:'author'}]});
  assert.deepEqual(page.rows.map(r=>r.id),['free','c1']);
});
test('choosing an author stops the old session and requires explicit fresh activation',async()=>{
  const calls=[];let proofs=0;
  const ui=personal.create({getIdentity:async()=>({id:'admin',role:'admin',full_name:'Admin'}),
    getAuthors:async()=>({principal:{id:'admin'},authors:[{id:'admin',full_name:'Admin'},{id:'author',full_name:'Author'}]}),
    getProof:async actor=>{proofs++;return {identity_proof:'opaque-'+actor,expires_at:Date.now()/1000+45,browser_session:'actual-tab'}},
    send:async({args})=>{calls.push(args);return {ok:true,active:args.action!=='personal_stop',max_dialogs:0,auto_enabled:false}},visible:()=>true});
  try{await ui.start();await ui.identityArgs();assert.equal(proofs,1);await ui.selectAuthor('author');assert.equal(ui.state.active,false);assert.equal(ui.state.auto,false);assert.equal(ui.state.operator,'author');assert.equal(calls.at(-1).action,'personal_stop');await ui.start();assert.equal(ui.state.principal,'admin');assert.equal(ui.state.operator,'author');assert.equal(proofs,2);assert.equal(calls.at(-1).identity_proof,'opaque-author');assert.ok(!calls.some(c=>c.action==='personal_mode'))}finally{await ui.stop()}
});

test('native completion requires the acknowledged service post for this exact CRM ID',async()=>{
 const f=apiFixture();for(const receipt of [null,{id:'1234567',telegram_confirmed:false},{id:'7654321',telegram_confirmed:true}])await assert.rejects(f.api.complete('c1','1234567',receipt),/не подтверждена/);
 assert.deepEqual(f.calls,[]);await f.api.complete('c1','1234567',{id:'1234567',telegram_confirmed:true});
 assert.deepEqual(f.calls.at(-1)[2],{operator_id:'author',version:3,crm_request_id:'1234567',telegram_confirmed:true});
});
