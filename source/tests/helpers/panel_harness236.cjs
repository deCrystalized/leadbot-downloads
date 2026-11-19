'use strict';
// Actual UI/Personal/Runner/Workflow/Observer orchestration. The minimal DOM
// replaces rendering only; all backend/model/customer I/O below is synthetic.
const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
class Element{
 constructor(tag,attrs={},kids=[]){this.tag=tag;this.attrs=attrs;this.dataset={};this.children=[];this.scrollTop=0;this.style={};this.open=false;
  this.classList={values:new Set((attrs.class||'').split(/\s+/).filter(Boolean)),contains:x=>this.classList.values.has(x),add:x=>this.classList.values.add(x),remove:x=>this.classList.values.delete(x)};
  for(const[k,v]of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v;
  this.disabled=!!attrs.disabled;this.replaceChildren(...kids);
 }
 append(...kids){for(const k of kids.flat(Infinity)){if(k==null||k===false)continue;if(k instanceof Element)k.parent=this;this.children.push(k)}}
 appendChild(k){this.append(k);return k}
 replaceChildren(...kids){this.children=[];this.append(...kids)}
 get textContent(){return this.children.map(k=>k instanceof Element?k.textContent:String(k)).join(' ')}
 set textContent(v){this.children=[v]}
 getRootNode(){return this.parent?this.parent.getRootNode():this}
 contains(el){return el===this||this.children.some(k=>k instanceof Element&&k.contains(el))}
 matches(sel){if(sel.startsWith('.'))return this.classList.contains(sel.slice(1));const a=/^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(sel);return a?Object.hasOwn(this.attrs,a[1])&&(a[2]===undefined||this.attrs[a[1]]===a[2]):this.tag===sel}
 querySelectorAll(sel){return this.children.filter(k=>k instanceof Element).flatMap(k=>[...(k.matches(sel)?[k]:[]),...k.querySelectorAll(sel)])}
 querySelector(sel){return this.querySelectorAll(sel)[0]||null}
 getAttribute(k){return this.attrs[k]}
 setAttribute(k,v){this.attrs[k]=v}
 focus(){}
}
async function panelHarness(options={}){
 const actor='11111111-1111-4111-8111-111111111111',principal='22222222-2222-4222-8222-222222222222';
 const context={convId:'first',assigneeId:'',conversationStatus:'in_progress',crmRequestId:'',revision:'r1',messages:[{id:'m1',direction:'in',sender_type:'client',body:'Сколько стоит собрать тумбу?'}]};
 const records=new Map(),calls=[],wires=[],effects=[],nativeJobs=new Map(),timers=new Map();let mode='review',active=false,timer=0;
 const root=new Element('root'),panel=new Element('section');root.append(panel);
 const h=(tag,attrs,...kids)=>new Element(tag,attrs||{},kids);
 const status=()=>({ok:true,active,auto_enabled:mode==='auto',auto_available:true,policy_version:'synthetic-policy',activation_nonce:'synthetic-nonce',mode_epoch:1,max_dialogs:12});
 const screen=()=>({ok:true,eligible:true,scope:context.assigneeId?'mine':'free',action:'price',reason:'Профильная работа без выявленных согласований'});
 const send=async msg=>{const a=msg.args;calls.push({action:a.action,wording:a.wording_mode});
  wires.push(structuredClone(a));
  if(options.send){const custom=await options.send(a);if(custom!==undefined)return custom}
  if(a.action==='personal_start'){active=true;return status()}
  if(a.action==='personal_stop'){active=false;return status()}
  if(a.action==='personal_mode'){mode=a.execution_mode;return status()}
  if(['personal_heartbeat','personal_status'].includes(a.action))return status();
  if(a.action==='screen')return screen();
  if(a.action==='personal_plan')return{...screen(),operator_id:actor,auto_session_enabled:mode==='auto',mode_epoch:1,revision:context.revision,operation_id:context.revision+':operation',step:context.assigneeId?'reply':'claim'};
  if(a.action==='personal_event')return{ok:true};
  if(a.action==='personal_authorize')return{ok:true,auto_enabled:true,execution_allowed:true,mode_epoch:1,operator_id:actor,revision:context.revision,kind:a.operation.kind,permit:'synthetic',expires_at:Date.now()+10000};
  if(['preview','research_status'].includes(a.action))return{ok:true,pending_research:true,pending_admission:true,research_state:'awaiting_admission',research_job_id:'',request_id:'synthetic-request',revision:context.revision,needs_operator:false,reply:''};
  if(a.action==='research_cancel')return{ok:true};
  throw Error('Unexpected synthetic UI transport '+a.action);
 };
 const scope={module:{exports:{}},console,crypto,Date,document:{createElement:tag=>new Element(tag),hidden:false},window:{addEventListener:()=>{}},
  setInterval:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer},clearInterval:id=>timers.delete(id),setTimeout,clearTimeout,
  LC_PERSONAL:require('../../ext/personal'),LC_WORKFLOW:require('../../ext/workflow'),LC_ASSISTANT_RUNNER:require('../../ext/assistant-runner'),LC_OBSERVER:require('../../ext/observer')};
 vm.createContext(scope);vm.runInContext(fs.readFileSync(require.resolve('../../ext/assistant-ui'),'utf8'),scope);
 const ui=scope.module.exports.create({h,panel,header:()=>h('header',{},'Synthetic panel'),send,currentId:options.currentId||(()=>''),latestId:options.latestId||(async()=>''),
  getIdentity:async()=>({id:principal,role:'admin',full_name:'Администратор'}),
  getAuthors:async()=>({principal:{id:principal},authors:[{id:actor,full_name:'Автор'}]}),
  getProof:async()=>({identity_proof:'synthetic-proof',browser_session:'synthetic-browser',expires_at:Date.now()/1000+45}),
  loadContext:options.loadContext||(async()=>structuredClone(context)),loadQueue:async()=>({mineCount:context.assigneeId?1:0,rows:[{id:'first',name:'Синтетический клиент',assigneeId:context.assigneeId}]}),
  workflow:{lock:async(k,fn)=>fn(),read:async k=>records.get(k),save:async(k,v)=>records.set(k,structuredClone(v)),pending:async(op,cid)=>[...records].filter(([k,v])=>k.startsWith('workflow:'+op+':'+cid+':')&&v.state!=='done').map(([key,v])=>({...v,key})),
   claim:async()=>{effects.push('claim');context.assigneeId=actor;context.revision='r2';nativeJobs.set('first',{id:'first',operator_id:actor,state:'waiting',version:1});return{ok:true}},reconcile:async()=>({confirmed:false})},
  observer:{list:async()=>({items:[...nativeJobs.values()],more:false,total:nativeJobs.size}),takeover:()=>{throw Error('No synthetic takeover expected')}}
 });
 const button=text=>{const b=panel.querySelectorAll('button').find(b=>b.textContent===text);if(!b||b.disabled)throw Error('Unavailable button '+text);return b.attrs.onclick()};
 await ui.open();await ui.personal.selectAuthor(actor);await ui.personal.start();
 return{ui,panel,button,context,calls,wires,effects,records,screen,async refresh(){await [...timers.values()].find(t=>t.delay===5000).fn()},async start(){await button('Запустить авто');await button('Подтверждаю: включить рабочий авто');await [...timers.values()].find(t=>t.delay===5000).fn()},stop:()=>ui.stop()};
}
module.exports={panelHarness};
