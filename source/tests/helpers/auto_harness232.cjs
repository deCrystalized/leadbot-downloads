'use strict';
// All communication is child-process pipes. No web server, API key, Chrome or
// production service is used; only the external provider/native writes are fake.
const test=require('node:test'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),readline=require('node:readline');
const {createAssistant}=require('../../extension-server/brain/assistant');
const Workflow=require('../../ext/workflow'),Runner=require('../../ext/assistant-runner');
const Native=require('../../ext/assistant-native'),Intake=require('../../ext/intake');
const Personal=require('../../ext/personal');
const actor='11111111-1111-4111-8111-111111111111',owner='isolated-auto231';

async function harness(t,names=['first','second']){
 const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>
  !/^(?:LEADBOT_|LC_)|TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY/i.test(key)));
 const child=spawn('/opt/homebrew/bin/python3',[require.resolve('../auto_simulator231.py')],{stdio:['pipe','pipe','pipe'],env});
 const pending=[],errors=[];let serial=Promise.resolve(),stderr='',personal,runner;
 child.stderr.on('data',v=>stderr+=v);
 readline.createInterface({input:child.stdout}).on('line',line=>{
  const task=pending.shift();if(!task)return errors.push(line);
  const value=JSON.parse(line);value.ok?task.resolve(value.value):task.reject(Error(value.error+'\n'+value.trace));
 });
 child.on('exit',code=>{while(pending.length)pending.shift().reject(Error('Fixture exited '+code+' '+stderr))});
 const rpc=value=>{const call=serial.then(()=>new Promise((resolve,reject)=>{pending.push({resolve,reject});child.stdin.write(JSON.stringify(value)+'\n')}));serial=call.catch(()=>{});return call};
 t.after(async()=>{runner?.stop();await personal?.stop();await serial;child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));assert.equal(stderr,'');assert.deepEqual(errors,[])});
 for(const cid of names)await rpc({op:'add',cid});
 const wire=[],hooks={};
 const bridge=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'synthetic-service-only',LEADBOT_RESEARCH_PROFILE:'sol_only'},
  ai:{спросить:()=>assert.fail('Forbidden fallback provider')},
  запрос:async(url,options)=>{
   assert.equal(url,'http://127.0.0.1:8788/api/extension/assistant');
   const body=JSON.parse(options.body);wire.push({action:body.action,cid:body.ctx?.convId});
   await hooks.beforeCall?.(body);
   const result=await rpc({op:'call',body});return{ok:result.status>=200&&result.status<300,status:result.status,json:async()=>result.body};
  }});
 personal=Personal.create({getIdentity:async()=>({id:'22222222-2222-4222-8222-222222222222',role:'admin'}),
  getAuthors:async()=>({principal:{id:'22222222-2222-4222-8222-222222222222'},authors:[{id:actor,full_name:'Synthetic actor'}]}),
  getProof:()=>rpc({op:'identity'}),send:req=>bridge(req.args,owner,'auto'),visible:()=>true,
  loadContext:cid=>rpc({op:'context',cid}),intakeGuard:Intake.inspect,
  loadQueue:async()=>({mineCount:0,rows:await Promise.all(names.map(async id=>{const c=await rpc({op:'context',cid:id});return{id,assigneeId:c.assigneeId}}))})});
 await personal.prepare();await personal.selectAuthor(actor);
 const call=async(action,ctx,extra={})=>bridge({action,ctx,operator_id:actor,...await personal.identityArgs(),...extra},owner,'auto');
 await personal.start();
 const session=await call('personal_status');
 assert.equal(session.ok,true,JSON.stringify(session));
 assert.equal(personal.state.active,true,personal.state.error);
 const mode=value=>personal.setMode(value);
 const storage=new Map(),locks=new Map(),jobs=new Map(),effects=[];
 const native=Native.create({operator:()=>actor,get:async path=>{
  const cid=decodeURIComponent(path.split('/dialogs/')[1]);if(!jobs.has(cid))throw Object.assign(Error('Not enrolled'),{status:404});return structuredClone(jobs.get(cid));
 },post:async(path,body)=>{
  const [cid,kind]=path.split('/dialogs/')[1].split('/'),ctx=await rpc({op:'context',cid});
  assert.equal(body.operator_id,actor);effects.push({cid,kind});
  if(kind==='claim'){
   assert.equal(ctx.assigneeId,'');await rpc({op:'update',cid,changes:{assigneeId:actor}});
   jobs.set(cid,{id:cid,operator_id:actor,state:'waiting',version:1});return structuredClone(jobs.get(cid));
  }
  const job=jobs.get(cid);assert.equal(body.version,job.version);
  if(kind==='messages'){
   assert.equal(body.expected_last_message_id,ctx.messages.at(-1).id);
   const message={id:cid+'-out-'+job.version,direction:'out',sender_type:'operator',body:body.text,
    delivery_status:'delivered',client_message_id:body.client_message_id};
   await rpc({op:'update',cid,changes:{messages:[...ctx.messages,message]}});job.version++;return message;
  }
  if(kind==='takeover'){job.state='paused';job.version++;return{...job,ok:true}}
  if(kind==='complete'){
   assert.equal(body.telegram_confirmed,true);assert.ok(effects.some(e=>e.cid===cid&&e.kind==='telegram_confirmed'));
   await rpc({op:'update',cid,changes:{crmRequestId:body.crm_request_id,conversationStatus:'closed'}});
   job.state='completed';job.version++;return{...job};
  }
  assert.fail('Unexpected native write '+kind);
 }});
 const deps={operator:()=>actor,visible:()=>true,
  snapshot:async cid=>({ctx:await rpc({op:'context',cid}),operatorId:actor,active:true,mineCount:0}),
  plan:s=>call('personal_plan',s.ctx,{mine_count:0}),
  preview:s=>call('preview',s.ctx,{wording_mode:runner?.state.mode==='auto'?'neural_auto':'neural_review'}),
  research:(action,s,args)=>call(action,s.ctx,args),validate:(s,draft)=>call('validate',s.ctx,{draft_id:draft.draft_id}),
  authorize:(s,operation)=>call('personal_authorize',s.ctx,{operation,mine_count:0}),
  audit:(s,event)=>call('personal_event',s.ctx,{audit_event:event,mine_count:0}),
  intakeGuard:Intake.inspect,replyIssue:Intake.replyIssue,
  lock:async(key,fn)=>{const run=(locks.get(key)||Promise.resolve()).then(fn);locks.set(key,run.catch(()=>{}));return run},
  read:async key=>storage.get(key),save:async(key,value)=>storage.set(key,structuredClone(value)),
  pending:async(op,id)=>[...storage].filter(([key,v])=>key.startsWith('workflow:'+op+':'+id+':')&&v.state!=='done').map(([key,v])=>({...v,key})),
  claim:s=>native.claim(s.ctx.convId),pauseForHuman:id=>native.pauseForHuman(id),
  sendReply:async(s,text,id)=>({confirmed:true,result:await native.reply(s.ctx.convId,text,id,s.ctx.messages.at(-1).id)}),
  prepareCRM:s=>rpc({op:'proposal',cid:s.ctx.convId}),
  checkCRM:(s,proposal)=>call('personal_crm_check',s.ctx,{proposal,mine_count:0}),
  createCRM:async(proposal,s,p)=>{
   effects.push({cid:s.ctx.convId,kind:'create'});
   // Simulated CRM returns an ID, then a separate full card read/dedup.
   effects.push({cid:s.ctx.convId,kind:'read_card_and_dedup'});
   const fields=[...new Set(['город','вид работ','вид услуг','тип','партнёр','дата','время','комментарий партнёра',
    'комментарий','служебный комментарий','имя / аккаунт объявления','телефон','имя клиента',...p.crm_required_fields])];
   return{ok:true,id:'9000001',verified:{fields,diffs:[]},warnings:[],workflow:{followup:{required:true}}};
  },
  notifyCreated:async(s,r)=>{effects.push({cid:s.ctx.convId,kind:'telegram_confirmed'});return{confirmed:true,result:{id:r.id,telegram_confirmed:true}}},
  linkCRM:async(s,r)=>({confirmed:true,result:await native.complete(s.ctx.convId,r.id,r.service_notification)}),
  reconcile:async()=>({confirmed:false}),finishOnLinked:true,notifyBeforeFinish:true};
 let workflow=Workflow.create(deps);let timer=0;
 runner=Runner.create({active:()=>true,visible:()=>true,setMode:mode,stopWorkflow:()=>workflow.stop(),
  scan:async(priority,ready)=>{await personal.scan(priority,ready);return personal.state.rows},
  step:id=>workflow.step(id),inspect:id=>workflow.inspect(id),park:(id,r)=>workflow.park(id,r),schedule:()=>++timer,clear:()=>{}});
 return{rpc,call,runner,wire,effects,storage,deps,session,mode,hooks,jobs,personal,
  evidence:()=>rpc({op:'evidence'}),
  async admit(){const p=await rpc({op:'controller',value:{op:'pending'}});assert.ok(p.pending_total>0,JSON.stringify(p));
   await rpc({op:'controller',value:{op:'arm',bindings:p.pending.map(r=>r.binding_hash),max_calls:4*p.pending_total,seconds:600}});
   for(const row of p.pending)await rpc({op:'controller',value:{op:'admit',binding_hash:row.binding_hash,max_calls:4,seconds:300}});
  },
  async accept(){const e=await this.evidence();for(const j of e.jobs.filter(j=>j.state==='awaiting_root')){assert.equal(j.state,'awaiting_root',JSON.stringify(j));await rpc({op:'controller',value:{op:'decide',owner,job:j.job,result_sha256:j.result_sha256,accepted:true,reviewer:'synthetic-test-driver'}})}}};
}

module.exports={harness};
