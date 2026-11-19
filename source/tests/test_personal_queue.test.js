'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{create}=require('../ext/personal-queue');
function fixture(n=105,f=1205){const calls=[],mine=Array.from({length:n},(_,i)=>({id:'m'+i,status:'in_progress',assignee:{id:'george'},client:{name:'Мой'}})),free=Array.from({length:f},(_,i)=>({id:'f'+i,status:'new',assignee:null,can_claim:true,in_inbox:true}));const deps={identity:async()=> 'george',detail:async id=>[...mine,...free].find(r=>r.id===id)||{id,status:'in_progress',assignee:{id:'colleague'}},get:async path=>{calls.push(path);const u=new URL(path,'https://lead.test'),rows=u.pathname==='/inbox'?free:mine;const offset=Number(u.searchParams.get('offset')||0),size=Number(u.searchParams.get('limit'));return{items:rows.slice(offset,offset+size),page:{total:rows.length}}}};return{queue:create(deps),deps,calls}}
test('confirmed orders leave the bot queue while the actual dialogues stay incoming',async()=>{
 const f=fixture(2,3),get=f.deps.get,detail=f.deps.detail;const originals=[];
 const created=r=>{const v={...r,crm_request_id:r.id==='f1'?'':1234567};originals.push(v);return v};
 f.deps.get=async path=>{const page=await get(path);return{...page,items:page.items.map(created)}};
 f.deps.detail=async id=>created(await detail(id));
 const page=await f.queue.load({priorityIds:['f0','m0']});
 assert.deepEqual(page.rows.map(r=>r.id),['f1']);
 assert.ok(originals.filter(r=>r.id.startsWith('f')).every(r=>r.in_inbox===true&&r.status==='new'));
 assert.ok(f.calls.every(path=>path.startsWith('/inbox?')||path.startsWith('/conversations?')));
});
test('unknown failed or merely promised creation is not a confirmed CRM ID',async()=>{
 const f=fixture(0,7),get=f.deps.get,values=['',null,0,'0','pending','создам заявку',{id:1234567}];
 f.deps.get=async path=>{const p=await get(path);return{...p,items:p.items.map(r=>({...r,crm_request_id:values[Number(r.id.slice(1))]}))}};
 const seen=new Set();let offset=0;
 for(let i=0;i<10;i++){const p=await f.queue.load({offset});p.rows.forEach(r=>seen.add(r.id));offset=p.nextOffset;if(!p.more)break}
 assert.equal(seen.size,7);
});
test('completed heads do not consume slots intended for unprocessed rotating rows',async()=>{
 const f=fixture(0,30),get=f.deps.get;
 f.deps.get=async path=>{const p=await get(path);return{...p,items:p.items.map(r=>({...r,crm_request_id:Number(r.id.slice(1))<6?'7654321':''}))}};
 const p=await f.queue.load({offset:6});assert.equal(p.rows.length,12);assert.equal(p.rows[0].id,'f6');assert.equal(p.nextOffset,18);
});
test('personal screening never loads completed history or sends its messages',async()=>{
 const f=fixture(0,2),get=f.deps.get,loaded=[],actions=[];
 f.deps.get=async path=>{const p=await get(path);return{...p,items:p.items.map(r=>({...r,crm_request_id:r.id==='f0'?'1234567':''}))}};
 const personal=require('../ext/personal').create({getIdentity:async()=>({id:'george'}),loadQueue:()=>f.queue.load(),
  loadContext:async id=>{loaded.push(id);return{convId:id}},visible:()=>true,
  send:async({args:a})=>{actions.push(a.action);return a.action==='screen'?{ok:true,eligible:true}:{ok:true,active:a.action!=='personal_stop',max_dialogs:0}}});
 try{await personal.start();await personal.scan();assert.deepEqual(loaded,['f1']);assert.deepEqual(personal.state.rows.map(r=>r.id),['f1']);assert.ok(actions.every(v=>['personal_start','screen'].includes(v)))}finally{await personal.stop()}
});
test('paginates beyond 100 own and 600 free dialogs without an artificial total limit',async()=>{const f=fixture();const seen=new Set();let offset=0;for(let i=0;i<400;i++){const page=await f.queue.load({offset});page.rows.forEach(r=>seen.add(r.id));offset=page.nextOffset;if(!page.more)break}assert.equal(seen.size,1310);assert.ok(seen.has('m104'));assert.ok(seen.has('f1204'));assert.equal((await f.queue.load({offset})).rows[0].id,'f0');assert.ok(f.calls.every(path=>Number(new URL(path,'https://lead.test').searchParams.get('limit'))<=12))});
test('incoming event prioritizes a real own or free dialog while excluding foreign assignments',async()=>{const f=fixture();const page=await f.queue.load({offset:24,priorityIds:['f1200','m90','foreign','f1200']});assert.deepEqual(page.rows.slice(0,2).map(r=>r.id),['f1200','m90']);assert.ok(!page.rows.some(r=>r.id==='foreign'));assert.equal(page.nextOffset,28);assert.equal(page.rows.length,12)});
test('fresh workload snapshot reads one mine row without downloading inbox or contacts',async()=>{const f=fixture();const r=await f.queue.load({countOnly:true});assert.equal(r.mineCount,105);assert.equal(f.calls.length,1);assert.ok(!f.calls[0].includes('/inbox'))});
test('unknown pagination and invalid identity stop rather than truncate the queue',async()=>{const f=fixture();f.deps.get=async()=>({items:[]});await assert.rejects(f.queue.load(),/размер/);f.deps.identity=async()=> '';await assert.rejects(f.queue.load(),/аккаунт/)});

test('six free incoming dialogs are refreshed ahead of stale assignments on every cursor page',async()=>{const f=fixture(105,6);for(const offset of [0,24,100]){const p=await f.queue.load({offset});assert.deepEqual(p.rows.slice(0,6).map(r=>r.id),['f0','f1','f2','f3','f4','f5']);assert.ok(p.nextOffset>offset);assert.ok(p.rows.length<=12)}});
test('fresh free head changes are picked up without waiting for cursor wrap or WebSocket',async()=>{const f=fixture(105,0),get=f.deps.get;f.deps.get=async path=>path.startsWith('/inbox')?{items:[{id:'fresh',status:'new',can_claim:true,in_inbox:true}],page:{total:1}}:get(path);const p=await f.queue.load({offset:72});assert.equal(p.rows[0].id,'fresh');assert.ok(p.rows.some(r=>r.id==='m71'))});
test('a colleague draining the inbox between reads restarts pagination without stopping the loop',async()=>{const f=fixture(0,1),get=f.deps.get;let drained=false;f.deps.get=async path=>{if(path.includes('offset=')){drained=true;return{items:[],page:{total:0}}}if(drained&&path.startsWith('/inbox'))return{items:[],page:{total:0}};return get(path)};const first=await f.queue.load();assert.equal(first.queueChanged,true);assert.equal(first.nextOffset,0);assert.equal(first.rows[0].id,'f0');const next=await f.queue.load({offset:first.nextOffset});assert.equal(next.queueChanged,false);assert.equal(next.total,0);assert.deepEqual(next.rows,[]);assert.equal(next.more,false)});
