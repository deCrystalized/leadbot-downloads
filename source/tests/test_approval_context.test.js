'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),cp=require('node:child_process');
const code=process.env.APPROVAL_BASELINE==='1'?cp.execFileSync('git',['show','HEAD:ext/content.js'],{encoding:'utf8'}):fs.readFileSync(require.resolve('../ext/content'),'utf8');
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
function fixture(){
 const data={},calls=[],notes=[],renders=[];
 const rec={chats:[{chat:'branch-a',title:'A',msg:10}],queue:[{chat:'branch-b',title:'B'}],text:'Согласовать работу',at:1};
 const original={id:'dialog-a',lead:{name:'Клиент',city:'Тула'},prep:{cityText:'Тула'},tgSent:rec,
  tg:{chats:{'branch-a':{title:'A'},'branch-b':{title:'B'}},picked:['branch-a','branch-b'],text:'Согласовать работу'}};
 const s={S:original,Date,Promise,Set,JSON,String,Array,LC_WORKFLOW:{territoryIssue:()=>null},keepEdits:()=>{},keepTg:()=>{},
  panel:{querySelector:()=>({value:'Согласовать работу'}),querySelectorAll:()=>[],classList:{contains:()=>true}},
  store:{get:async(k,d)=>structuredClone(data[k]||d),set:async(k,v)=>{data[k]=structuredClone(v)}},
  шаг:()=>{},просьбыВЧате:async()=>[],сТаймаутом:p=>p,вJpeg:async()=>'',
  render2keep:()=>renders.push(s.S.id),pollReplies:()=>{},формаЭтого:()=>true,
  заметкаСогласования:async(...args)=>{notes.push(args);return true},
  send:async x=>{calls.push(structuredClone(x));return {ok:true,message_id:11,replies:[]}},
  вЧатГорода:async(...args)=>{calls.push(structuredClone(args));return {ok:true,message_id:11}}};
 vm.createContext(s);
 function load(start,end){const a=code.indexOf(start),b=code.indexOf(end,a);assert.ok(a>=0&&b>a);vm.runInContext(code.slice(a,b),s)}
 // Реальные обработчики и реальный storage updater; внешние транспорты только синтетические.
 load('  const tgSentGet =','  function workText()');
 load('  async function sendApproval0()','  function approvalBox()');
 vm.runInContext('globalThis.save=tgSentSet;globalThis.busy=typeof TG_BUSY!=="undefined"?TG_BUSY:new Set();',s);
 return {s,data,calls,notes,renders,original,rec,button:()=>({disabled:false,textContent:'',dataset:{}})};
}
test('next branch acknowledgement stays with original dialogue after switching mid-send',async()=>{
 const f=fixture(),d=defer();f.s.вЧатГорода=async x=>{f.calls.push(x);return d.promise};
 const task=f.s.следующемуФилиалу(f.button());f.s.S={id:'dialog-b',tgSent:null};d.resolve({ok:true,message_id:22});await task;
 assert.equal(f.data.tgSent['dialog-a'].chats[1].msg,22);assert.equal(f.data.tgSent['dialog-b'],undefined);
 assert.equal(f.s.S.tgSent,null);assert.equal(f.notes[0][0],'dialog-a');assert.deepEqual(f.renders,[]);
});
test('rerender and second activation cannot send the same next branch twice',async()=>{
 const f=fixture(),d=defer();let n=0;f.s.вЧатГорода=async()=>{n++;return d.promise};
 const first=f.s.следующемуФилиалу(f.button()),second=f.s.следующемуФилиалу(f.button());
 d.resolve({ok:true,message_id:22});await Promise.all([first,second]);assert.equal(n,1);assert.equal(f.rec.queue.length,0);
});
test('first successful approval persists even when its dialogue is no longer visible',async()=>{
 const f=fixture(),d=defer(),started=defer();f.s.send=async()=>{started.resolve();return d.promise};
 const task=f.s.sendApproval0();await started.promise;f.s.S={id:'dialog-b',tgSent:null};d.resolve({ok:true,message_id:33});await task;
 assert.equal(f.data.tgSent['dialog-a'].chats[0].msg,33);assert.equal(f.data.tgSent['dialog-b'],undefined);assert.equal(f.s.S.tgSent,null);
});
test('multi outcome uses its original dialogue for every branch, including after a switch',async()=>{
 const f=fixture(),d=defer(),started=defer();f.rec.chats.push({chat:'branch-b',title:'B',msg:20});
 f.s.send=async x=>{f.calls.push(x);if(x.args.action==='replies')return {ok:true,replies:[]};if(x.args.chat==='branch-a'){started.resolve();return d.promise}return {ok:true,message_id:40}};
 const task=f.s.итогСогласования(f.button(),'Клиент отказался');await started.promise;f.s.S={id:'dialog-b',tgSent:null};d.resolve({ok:true,message_id:30});await task;
 assert.ok(f.calls.filter(x=>x.args.action==='send').every(x=>x.args.conv==='dialog-a'));
 assert.equal(f.data.tgSent['dialog-a'].done,'Клиент отказался');assert.equal(f.data.tgSent['dialog-b'],undefined);assert.equal(f.s.S.tgSent,null);
});
test('partial outcome is persisted as partial; retry skips branches already acknowledged',async()=>{
 const f=fixture();f.rec.chats.push({chat:'branch-b',title:'B',msg:20});let b=0;
 f.s.send=async x=>{f.calls.push(x);return x.args.action==='replies'?{ok:true,replies:[]}:x.args.chat==='branch-b'&&b++===0?{ok:false,error:'definite rejection'}:{ok:true,message_id:42}};
 await f.s.итогСогласования(f.button(),'Клиент отказался');assert.equal(f.data.tgSent['dialog-a'].done,undefined);assert.match(f.data.tgSent['dialog-a'].outcomeError,/не во все/);
 await f.s.итогСогласования(f.button(),'Клиент отказался');assert.equal(f.data.tgSent['dialog-a'].done,'Клиент отказался');
 assert.equal(f.calls.filter(x=>x.args.action==='send'&&x.args.chat==='branch-a').length,1);
});
test('concurrent storage saves preserve both dialogues',async()=>{
 const f=fixture();await Promise.all([f.s.save('dialog-a',{text:'A'}),f.s.save('dialog-b',{text:'B'})]);
 assert.equal(f.data.tgSent['dialog-a'].text,'A');assert.equal(f.data.tgSent['dialog-b'].text,'B');
});
test('reply carries exact branch and approval message; edits with equal count refresh the card',async()=>{
 const f=fixture();f.original.tgReplies=[{id:5,text:'Старый ответ'}];
 f.s.send=async()=>({ok:true,replies:[{id:5,at:1,text:'Исправленные условия'}]});
 await f.s.pollReplies();assert.equal(f.original.tgReplies[0].chat,'branch-a');assert.equal(f.original.tgReplies[0].approvalMsg,10);assert.equal(f.renders.length,1);
});
test('late reply cannot repaint a replacement approval in the same dialogue',async()=>{
 const f=fixture(),d=defer();f.s.send=async()=>d.promise;
 const task=f.s.pollReplies();f.original.tgSent={chats:[{chat:'branch-c',msg:99}]};d.resolve({ok:true,replies:[{id:5,text:'Ответ старому согласованию'}]});await task;
 assert.equal(f.original.tgReplies,undefined);assert.equal(f.renders.length,0);
});
test('pre-send dialogue switch while preparing prevents the send entirely',async()=>{
 const f=fixture(),d=defer();f.s.просьбыВЧате=async()=>d.promise;
 const task=f.s.sendApproval0();f.s.S={id:'dialog-b'};d.resolve([]);await task;assert.equal(f.calls.length,0);
});
test('unknown next-branch acknowledgement is persisted and cannot be retried blindly',async()=>{
 const f=fixture();let calls=0;f.s.вЧатГорода=async()=>{calls++;return {ok:false,unknown:true}};
 await f.s.следующемуФилиалу(f.button());await f.s.следующемуФилиалу(f.button());
 assert.equal(calls,1);assert.equal(f.data.tgSent['dialog-a'].nextUnknown,'branch-b');assert.equal(f.rec.queue.length,1);
});
test('unknown outcome is not a success and a retry does not send it again',async()=>{
 const f=fixture();f.s.send=async x=>{f.calls.push(x);return x.args.action==='replies'?{ok:true,replies:[]}:{ok:false,unknown:true}};
 await f.s.итогСогласования(f.button(),'Отказ');await f.s.итогСогласования(f.button(),'Отказ');
 assert.equal(f.calls.filter(x=>x.args.action==='send').length,1);assert.equal(f.rec.done,undefined);assert.equal(f.data.tgSent['dialog-a'].outcomeUnknown['branch-a:10'],true);
});
test('force override belongs to the branch whose pending request was shown',async()=>{
 const f=fixture(),b=f.button();b.dataset.force='branch-a';let opts;
 f.s.вЧатГорода=async(_x,o)=>{opts=o;return {ok:true,message_id:45}};await f.s.следующемуФилиалу(b);assert.equal(opts.force,false);
});
test('a thrown next-branch transport error becomes an unknown acknowledgement, without a blind retry',async()=>{
 const f=fixture();let n=0;f.s.вЧатГорода=async()=>{n++;throw Error('connection lost')};
 await f.s.следующемуФилиалу(f.button());await f.s.следующемуФилиалу(f.button());assert.equal(n,1);assert.equal(f.data.tgSent['dialog-a'].nextUnknown,'branch-b');
});
