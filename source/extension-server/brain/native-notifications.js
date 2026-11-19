'use strict';
/* Private service receipt for one already-created native CRM work. No model,
   customer message, CRM write, Run start or public browser operation. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const uuid=x=>typeof x==='string'&&/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(x);
const hex=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const stable=x=>JSON.stringify(x&&typeof x==='object'&&!Array.isArray(x)
  ?Object.fromEntries(Object.keys(x).sort().map(k=>[k,JSON.parse(stable(x[k]))]))
  :Array.isArray(x)?x.map(v=>JSON.parse(stable(v))):x);
const fail=code=>Object.assign(Error('Исходная служебная отписка не подтверждена'),{code});

function strictJSON(raw,maxBytes=200000){
  if(typeof raw!=='string'||Buffer.byteLength(raw)>maxBytes)throw fail('native_json');
  let i=0;const ws=()=>{while(/\s/.test(raw[i]||'')&&i<raw.length)i++};
  function string(){
    const start=i;if(raw[i++]!=='"')throw fail('native_json');
    while(i<raw.length){const c=raw[i++];if(c==='"')return JSON.parse(raw.slice(start,i));
      if(c==='\\')i++;}
    throw fail('native_json');
  }
  function value(depth){
    if(depth>24)throw fail('native_json');ws();const c=raw[i];
    if(c==='"'){string();return}
    if(c==='{'||c==='['){
      const object=c==='{',end=object?'}':']',keys=new Set();i++;ws();
      if(raw[i]===end){i++;return}
      while(i<raw.length){
        ws();if(object){const key=string();if(keys.has(key))throw fail('native_json');keys.add(key);
          ws();if(raw[i++]!==':')throw fail('native_json');}
        value(depth+1);ws();if(raw[i]===end){i++;return}
        if(raw[i++]!==',')throw fail('native_json');
      }
      throw fail('native_json');
    }
    const token=/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(i));
    if(!token)throw fail('native_json');i+=token[0].length;
  }
  value(0);ws();if(i!==raw.length)throw fail('native_json');
  const result=JSON.parse(raw);
  function finite(x){if(typeof x==='number'&&!Number.isFinite(x))throw fail('native_json');
    if(x&&typeof x==='object')for(const v of Object.values(x))finite(v);}
  finite(result);return result;
}

const FIELDS=['v','intent_id','work_id','principal_id','operator_id','run_id','generation','cid',
  'source_sha256','snapshot_hash','form_reference','card_sha256','crm_request_id',
  'direction','source_code','dispatch_before'];
function checked(value){
  if(!value||typeof value!=='object'||Array.isArray(value)
      ||Object.keys(value).sort().join()!==[...FIELDS].sort().join()||value.v!==1
      ||['intent_id','principal_id','operator_id','run_id','cid'].some(k=>!uuid(value[k]))
      ||['work_id','source_sha256','snapshot_hash','form_reference','card_sha256'].some(k=>!hex(value[k]))
      ||!Number.isSafeInteger(value.generation)||value.generation<1
      ||typeof value.crm_request_id!=='string'||!/^[1-9]\d{0,11}$/.test(value.crm_request_id)
      ||!['mnc','kp','bt'].includes(value.direction)
      ||typeof value.source_code!=='string'||!/^[АСВМБ]\d{1,3}(?:\.\d)?$/.test(value.source_code)
      ||typeof value.dispatch_before!=='number'||!Number.isFinite(value.dispatch_before))
    throw fail('native_notification_binding');
  return JSON.parse(stable(value));
}

class Journal{
  constructor(directory){
    if(typeof directory!=='string'||!path.isAbsolute(directory))throw fail('native_journal');
    let cursor=directory;
    while(true){if(fs.existsSync(cursor)&&fs.lstatSync(cursor).isSymbolicLink())throw fail('native_journal');
      const parent=path.dirname(cursor);if(parent===cursor)break;cursor=parent;}
    let existing=directory;while(!fs.existsSync(existing))existing=path.dirname(existing);
    fs.mkdirSync(directory,{recursive:true,mode:0o700});
    for(let child=directory;child!==existing;child=path.dirname(child)){
      const parent=fs.openSync(path.dirname(child),'r');try{fs.fsyncSync(parent)}finally{fs.closeSync(parent)}
    }
    const info=fs.statSync(directory);
    if(info.uid!==process.getuid()||!info.isDirectory())throw fail('native_journal');
    fs.chmodSync(directory,0o700);this.directory=directory;
  }
  folder(work){
    if(!hex(work))throw fail('native_journal');const target=path.join(this.directory,work);
    if(fs.existsSync(target)&&fs.lstatSync(target).isSymbolicLink())throw fail('native_journal');
    const existed=fs.existsSync(target);fs.mkdirSync(target,{mode:0o700,recursive:true});
    if(!existed){const parent=fs.openSync(this.directory,'r');try{fs.fsyncSync(parent)}finally{fs.closeSync(parent)}}
    const s=fs.statSync(target);if(!s.isDirectory()||s.uid!==process.getuid()||(s.mode&0o077))throw fail('native_journal');
    return target;
  }
  read(work,name){
    const file=path.join(this.folder(work),name);
    try{const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.uid!==process.getuid()
        ||(s.mode&0o077)||s.size>400000)throw fail('native_journal');
      return strictJSON(fs.readFileSync(file,'utf8'),400000);
    }catch(e){if(e.code==='ENOENT')return null;throw e}
  }
  write(work,name,value,{exclusive=false}={}){
    const folder=this.folder(work),file=path.join(folder,name),raw=stable(value);
    const tmp=exclusive?file:path.join(folder,'.'+name+'.'+crypto.randomUUID());
    let fd;
    try{fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,raw);fs.fsyncSync(fd);}
    finally{if(fd!==undefined)fs.closeSync(fd)}
    if(!exclusive)fs.renameSync(tmp,file);
    const dir=fs.openSync(folder,'r');try{fs.fsyncSync(dir)}finally{fs.closeSync(dir)}
  }
}

function create({enabled=false,team,directory,now=()=>Date.now()}={}){
  if(typeof enabled!=='boolean'||typeof now!=='function')throw fail('native_configuration');
  if(!enabled){const disabled=async()=>({ok:false,state:'disabled',telegram_confirmed:false});return {prepare:disabled,send:disabled}}
  if(typeof team!=='function')throw fail('native_configuration');
  const journal=new Journal(directory),active=new Map();
  const textFor=p=>p.crm_request_id+' - '+p.source_code+' '+{mnc:'МНЧ',kp:'КП',bt:'БТ'}[p.direction];
  function receipt(p,target,raw){
    if(!raw||raw.status!==200||raw.content_type!=='application/json'
        ||typeof raw.body!=='string'||!hex(raw.sha256))throw fail('native_receipt');
    const bytes=Buffer.from(raw.body,'base64');
    if(bytes.length>200000||bytes.toString('base64')!==raw.body||hash(bytes)!==raw.sha256)
      throw fail('native_receipt');
    const r=strictJSON(bytes.toString('utf8'));
    if(!r||r.ok!==true||!Number.isSafeInteger(r.message_id)||r.message_id<1
        ||r.native_intent!==p.intent_id||r.chat_id!==target.chat_id||r.reply_to!==target.topic_id
        ||r.text_sha256!==hash(Buffer.from(textFor(p))))throw fail('native_receipt');
    return {ok:true,telegram_confirmed:true,work_id:p.work_id,intent_id:p.intent_id,
      crm_request_id:p.crm_request_id,source_sha256:p.source_sha256,snapshot_hash:p.snapshot_hash,
      form_reference:p.form_reference,card_sha256:p.card_sha256,
      chat_id:r.chat_id,topic_id:r.reply_to,message_id:r.message_id,text_sha256:r.text_sha256,
      original_http:raw};
  }
  const requestHash=p=>hash(Buffer.from(stable(p)));
  function original(p){
    const saved=journal.read(p.work_id,'request.json');
    if(saved&&(saved.sha256!==requestHash(p)||stable(saved.request)!==stable(p)))
      throw fail('native_intent_changed');
    return saved;
  }
  async function call(p,op,query,body){
    if(p.dispatch_before*1000<=now())throw fail('native_deadline');
    return team(op,query,body,{timeout:Math.min(30000,p.dispatch_before*1000-now()),parse:strictJSON,
      observeRaw:async(meta,bytes)=>{
        if(!Buffer.isBuffer(bytes)||bytes.length>200000)throw fail('native_receipt');
        journal.write(p.work_id,op==='tg_send'?'send-raw.json':op+'-raw.json',{
          status:meta.status,content_type:meta.content_type,sha256:hash(bytes),body:bytes.toString('base64'),
        },{exclusive:true});
      }});
  }
  async function prepareWork(p){
    const id=p.work_id,saved=original(p);
    if(saved){
      const target=journal.read(id,'target.json');
      return target?{ok:true,prepared:true,work_id:id,intent_id:p.intent_id,telegram_confirmed:false}
        :{ok:false,state:'notification_unknown',telegram_confirmed:false,work_id:id};
    }
    if(p.dispatch_before*1000<=now()||p.dispatch_before*1000>now()+90000)throw fail('native_deadline');
    journal.write(id,'request.json',{request:p,sha256:requestHash(p)},{exclusive:true});
    try{
      const chats=await call(p,'tg_chats',null),matches=Object.entries(chats||{}).filter(([id,c])=>
        /^-?[1-9]\d{0,18}$/.test(id)&&c?.forum===true&&/^авито[\s-]*чаты$/i.test(String(c.title||'').trim()));
      if(matches.length!==1)throw fail('native_route');
      const chat=matches[0][0],topics=await call(p,'tg_topics',{chat});
      const chosen=(topics?.topics||[]).filter(t=>Number.isSafeInteger(t?.id)&&t.id>0
        &&String(t.title||'').trim().replace(/\s+/g,' ').toLowerCase()==='созданные с авито');
      if(chosen.length!==1)throw fail('native_route');
      journal.write(id,'target.json',{chat_id:chat,topic_id:chosen[0].id,
        text_sha256:hash(Buffer.from(textFor(p)))},{exclusive:true});
      return {ok:true,prepared:true,work_id:id,intent_id:p.intent_id,telegram_confirmed:false};
    }catch(_){
      journal.write(id,'stopped.json',{state:'notification_stopped',at:now()});
      return {ok:false,state:'notification_stopped',telegram_confirmed:false,work_id:id};
    }
  }
  async function sendWork(p,sendBefore){
    const id=p.work_id;if(!original(p))throw fail('native_not_prepared');
    const target=journal.read(id,'target.json'),raw=journal.read(id,'send-raw.json');
    if(raw&&target)return receipt(p,target,raw); // Original evidence after Stop/expiry, no network.
    if(journal.read(id,'sending.json'))return {ok:false,state:'notification_unknown',telegram_confirmed:false,work_id:id};
    if(!target||typeof sendBefore!=='number'||!Number.isFinite(sendBefore)
        ||sendBefore*1000<=now()||sendBefore*1000>now()+5000
        ||p.dispatch_before*1000<=now())throw fail('native_jit_permission');
    journal.write(id,'sending.json',{request_sha256:requestHash(p),target,at:now(),send_before:sendBefore},{exclusive:true});
    try{
      // No slow group/topic read may occur after the fresh Root source gate.
      if(sendBefore*1000<=now())throw fail('native_jit_permission');
      await call(p,'tg_send',null,{chat:target.chat_id,reply_to:target.topic_id,text:textFor(p),conv:p.cid,
        native_receipt:true,native_intent:p.intent_id});
      const result=receipt(p,target,journal.read(id,'send-raw.json'));
      journal.write(id,'result.json',result,{exclusive:true});return result;
    }catch(_){
      journal.write(id,'stopped.json',{state:'notification_unknown',at:now()});
      return {ok:false,state:'notification_unknown',telegram_confirmed:false,work_id:id};
    }
  }
  function run(action,value,sendBefore){
    let p;try{p=checked(value)}catch(e){return Promise.reject(e)}
    const key=p.work_id+':'+action,signature=stable(p),running=active.get(key);
    if(running){if(running.signature!==signature)return Promise.reject(fail('native_intent_changed'));return running.promise}
    const promise=(action==='prepare'?prepareWork(p):sendWork(p,sendBefore)).finally(()=>active.delete(key));
    active.set(key,{signature,promise});return promise;
  }
  return {prepare:value=>run('prepare',value),send:(value,sendBefore)=>run('send',value,sendBefore)};
}
module.exports={create,strictJSON,checked,Journal};
