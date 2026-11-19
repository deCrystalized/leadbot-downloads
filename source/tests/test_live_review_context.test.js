'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync(require.resolve('../ext/assistant-ui'),'utf8');
function snapshotFixture(){
 const calls=[],state={id:'chat',epoch:1,ctx:null};let current='chat';
 const ctx={convId:'chat',messages:[{id:'m1',direction:'in',body:'Компьютер не включается'}]};
 const scope={state,personal:{state:{active:true,operator:'george'}},currentId:()=>current,
  deps:{assertUnoccupied:async()=>{},getIdentity:async()=>({id:'george'}),loadQueue:async opts=>{assert.equal(opts.countOnly,true);return{mineCount:0}}},
  send:async req=>{calls.push(req.args.action);return{ok:true,active:true}},loadContext:async()=>ctx};
 const seeded=scope.personal.state;
 scope.personal=require('../ext/personal').create({getIdentity:()=>scope.deps.getIdentity(),send:scope.send});
 Object.assign(scope.personal.state,seeded,{principal:'george'});
 const start=code.indexOf('      snapshot:async(id)=>{'),end=code.indexOf('\n      plan:',start);
 assert.ok(start>=0&&end>start);vm.createContext(scope);vm.runInContext('globalThis.fn=({'+code.slice(start,end)+'}).snapshot;',scope);
 return{scope,state,ctx,calls,setCurrent:id=>current=id};
}
test('actual UI snapshot exposes the exact selected history using only read operations',async()=>{
 const f=snapshotFixture(),result=await f.scope.fn('chat');
 assert.equal(f.state.ctx,f.ctx);assert.equal(result.ctx,f.ctx);assert.equal(result.operatorId,'george');
 assert.deepEqual(f.calls,['personal_status']);
});
test('late history from a previous selection cannot replace the currently displayed conversation',async()=>{
 const f=snapshotFixture(),selected={convId:'other',messages:[]};
 f.scope.loadContext=async()=>{f.state.epoch++;f.state.id='other';f.state.ctx=selected;f.setCurrent('other');return f.ctx};
 await f.scope.fn('chat');assert.equal(f.state.ctx,selected);
});
test('account change stops before reading or displaying a client history',async()=>{
 const f=snapshotFixture();f.scope.deps.getIdentity=async()=>({id:'colleague'});
 f.scope.loadContext=async()=>assert.fail('History must not load for another account');
 await assert.rejects(f.scope.fn('chat'),/Аккаунт LeadChat изменился/);assert.equal(f.state.ctx,null);assert.deepEqual(f.calls,[]);
});
test('actual inline history keeps service notes and unread attachments distinct and excludes another chat',()=>{
 const s={state:{id:'chat'},h:(tag,attrs,...children)=>({tag,attrs,children:children.flat()}),Date};
 const start=code.indexOf('    function conversationReview('),end=code.indexOf('    function workflowView()',start);
 assert.ok(start>=0&&end>start);vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.view=conversationReview;',s);
 assert.equal(s.view({convId:'other',messages:[]}), '');
 const tree=s.view({convId:'chat',itemTitle:'Компьютерный мастер',messages:[{direction:'in',body:'Не включается',attachments:[{kind:'image'}]},
   {direction:'note',body:'Назначен сотрудник'},{direction:'out',body:'Подскажите модель?',status:'sending'}]});
 const rendered=JSON.stringify(tree);
 assert.equal(tree.attrs.open,'');assert.match(rendered,/Клиент/);assert.match(rendered,/Служебное/);
 assert.match(rendered,/проверить перед ответом/);assert.match(rendered,/Не подтверждена доставка/);
 assert.doesNotMatch(rendered,/onclick/);
});
test('opening a queue entry automatically inspects one selected chat without executing a step',async()=>{
 const calls=[],state={id:''};let current='chat';
 const s={state,workflow:{},currentId:()=>current,deps:{onOpenDialog:async id=>{calls.push('select:'+id)}},
  open:async()=>{state.id=current;calls.push('view')},inspectWorkflow:async()=>calls.push('inspect')};
 const start=code.indexOf('    async function openReviewedDialog('),end=code.indexOf('    function queueRow(',start);
 assert.ok(start>=0&&end>start);vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.openOne=openReviewedDialog;',s);
 await s.openOne('chat');assert.deepEqual(calls,['select:chat','view','inspect']);
 calls.length=0;current='changed';await s.openOne('chat');assert.deepEqual(calls,['select:chat','view']);
});
