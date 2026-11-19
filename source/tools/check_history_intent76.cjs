'use strict';
// Actual compiled extension gateway and form adapter, synthetic loopback only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const crypto=require('node:crypto'),readline=require('node:readline'),{spawn}=require('node:child_process');
const root=process.cwd(),installed=process.argv[2]==='--installed';
const bundle=installed?'/opt/lead-centre/brain/dist/index.js':path.resolve(process.argv[2]);
const manifest=JSON.parse(fs.readFileSync(installed?path.resolve(__dirname,'../test-artifacts/deploy-manifest.json'):path.resolve(path.dirname(bundle),'../../test-artifacts/deploy-manifest.json')));
const owner='offline-personal-owner',service='test-only-service-token-not-a-credential';
const child=spawn('python3',['-u',path.join(root,'tests/http_fixture.py'),...(installed?['--installed-brain']:[])],{stdio:['ignore','pipe','pipe'],
 env:{...process.env,PYTHONPATH:installed?'/opt/leadbot/brain':path.join(root,'leadbot/brain'),LEADBOT_PERSONAL_OWNER_ID:owner,LEADBOT_PERSONAL_AUTO_AVAILABLE:'0'}});
let stderr='';child.stderr.on('data',b=>stderr+=b);
(async()=>{try{
 const lines=readline.createInterface({input:child.stdout});
 const port=await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('Fixture timeout')),10000);lines.once('line',s=>{clearTimeout(t);resolve(JSON.parse(s).port)});child.once('exit',c=>reject(Error('Fixture exit '+c)))});
 const base='http://127.0.0.1:'+port,compiled=require(bundle);assert.equal(compiled.ВЕРСИЯ,manifest.brain_version);
 const token='synthetic-history-intent76-token',month=new Date(Date.now()+3*3600000).toISOString().slice(0,7);
 const memory=new Map([['brain/tokens.json',{tokens:[{id:owner,sha:crypto.createHash('sha256').update(token).digest('hex'),label:'synthetic'}]}],['brain/state.json',{mode:'economy',modeMonth:month,limit:999999}]]);
 let calls=0;
 const handler=compiled.создать({store:{get:async(k,d)=>structuredClone(memory.has(k)?memory.get(k):d),put:async(k,v)=>memory.set(k,structuredClone(v))},
 env:{LEADBOT_PERSONAL_OWNER_ID:owner,LEADBOT_SERVICE_TOKEN:service,LEADBOT_ASSISTANT_URL:base+'/api/extension/assistant'},log:()=>{},sleep:async()=>{},запрос:async(u,o)=>{
  assert.ok(String(u).startsWith(base+'/'),'External calls forbidden');calls++;
  const r=await fetch(u,{method:o.method,headers:o.headers,body:o.body});return{ok:r.ok,status:r.status,json:()=>r.json()};}});
 async function request(name,dir,pairs,op='assistant'){
  const ctx={convId:'synthetic-compiled76-'+name,city:'Москва',dir,partner:'7',channel:'avito',accountTitle:'Иван '+(dir==='bt'?'БТ':'КП'),itemTitle:'Ремонт техники',adIdentity:'Иван',origin:'С1',messages:pairs.map(([direction,body],i)=>({id:String(i),direction,body}))};
  const response=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op,args:{action:'preview',ctx}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
  const out=JSON.parse(response.body);assert.equal(response.statusCode,200,out.error);assert.equal(out.ok,true);assert.equal(out.auto_enabled,false);assert.equal(out.policy_version,manifest.policy_version);return out;
 }
 assert.equal((await request('combined','bt',[['in','Печка Дарина верх газ, духовка электричество не включается']])).action,'refuse');
 const warranty=await request('warranty','kp',[['in','Телевизор Samsung звук есть картинки нет'],['out','Нужно смотреть'],['in','Гарантия имеется после ремонта?']]);
 assert.equal(warranty.action,'question');assert.match(warranty.reply,/оказанные услуги/);assert.doesNotMatch(warranty.reply,/бесплат/);
 const progress=await request('progress','kp',[['in','Есть понимание по срокам ремонта принтера?']]);
 assert.equal(progress.action,'handoff');assert.equal(progress.equipment_readiness_evidence.repair_completion_confirmed,false);
 const out=await request('arrival','kp',[['in','Компьютер не включается'],['in','Позвоните когда будете у подъезда']],'checklist');
 const form=require(path.join(root,'ext/workflow')).projectContactFacts({lead:{comment:'Не включается'},checks:[]},out);
 assert.equal(form.lead.call_before_visit,true);assert.match(form.lead.comment,/Позвонить при подъезде по просьбе клиента/);
 assert.doesNotMatch(form.lead.comment,/Позвонить перед выездом по просьбе клиента/);
 assert.equal(calls,4);
 console.log(JSON.stringify({policy:manifest.policy_version,brain:compiled.ВЕРСИЯ,compiled_previews:3,compiled_normal_form_checks:1,actual_form_adapter_checks:1,loopback_calls:calls,model_calls:0,external_calls:0,customer_sends:0,crm_reads:0,crm_writes:0,real_sessions_started:0,auto_enabled:false}));
}catch(e){console.error(e.stack);if(stderr)console.error(stderr.slice(-400));process.exitCode=1;}finally{child.kill();}})();
