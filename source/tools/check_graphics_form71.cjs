'use strict';
// Actual compiled extract/checklist entry, with only loopback HTTP and memory storage.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {spawn,execFileSync}=require('node:child_process'),readline=require('node:readline');
const installed=process.argv[2]==='--installed',root=process.cwd();let child,stderr='';
async function setup(){
 if(installed){
  const pid=execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
  const all=Object.fromEntries(fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').filter(Boolean).map(s=>[s.slice(0,s.indexOf('=')),s.slice(s.indexOf('=')+1)]));
  assert.ok(all.LEADBOT_SERVICE_TOKEN&&all.LEADBOT_PERSONAL_OWNER_ID);
  return {bundle:'/opt/lead-centre/brain/dist/index.js',base:'http://127.0.0.1:8788',owner:all.LEADBOT_PERSONAL_OWNER_ID,service:all.LEADBOT_SERVICE_TOKEN,manifest:JSON.parse(fs.readFileSync(path.resolve(__dirname,'../test-artifacts/deploy-manifest.json')))};
 }
 const bundle=path.resolve(process.argv[2]);assert.ok(fs.existsSync(bundle));
 child=spawn('python3',['-u',path.join(root,'tests/http_fixture.py')],{stdio:['ignore','pipe','pipe']});child.stderr.on('data',b=>stderr+=b);
 const lines=readline.createInterface({input:child.stdout});
 const port=await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('fixture timeout')),10000);lines.once('line',s=>{clearTimeout(t);resolve(JSON.parse(s).port)});child.once('exit',c=>reject(Error('fixture exit '+c)))});
 return {bundle,base:'http://127.0.0.1:'+port,owner:'offline-personal-owner',service:'test-only-service-token-not-a-credential',manifest:JSON.parse(fs.readFileSync(path.resolve(path.dirname(bundle),'../../test-artifacts/deploy-manifest.json')))};
}
(async()=>{try{
 const cfg=await setup(),compiled=require(cfg.bundle);assert.equal(compiled.ВЕРСИЯ,cfg.manifest.brain_version);
 const token='synthetic-graphics71-token',month=new Date(Date.now()+3*3600000).toISOString().slice(0,7);
 const memory=new Map([['brain/tokens.json',{tokens:[{id:cfg.owner,sha:crypto.createHash('sha256').update(token).digest('hex'),label:'synthetic'}]}],['brain/state.json',{mode:'economy',modeMonth:month,limit:999999}]]);
 const store={get:async(k,d)=>structuredClone(memory.has(k)?memory.get(k):d),put:async(k,v)=>memory.set(k,structuredClone(v))};let calls=0,nonLoopback=0;
 const handler=compiled.создать({store,env:{LEADBOT_PERSONAL_OWNER_ID:cfg.owner,LEADBOT_SERVICE_TOKEN:cfg.service,LEADBOT_ASSISTANT_URL:cfg.base+'/api/extension/assistant'},log:()=>{},sleep:async()=>{},запрос:async(u,o)=>{
  if(!String(u).startsWith(cfg.base+'/')){nonLoopback++;throw Error('external calls forbidden');}calls++;
  const r=await fetch(u,{method:o.method,headers:o.headers,body:o.body});return{ok:r.ok,status:r.status,json:()=>r.json()};
 }});
 const symptom='Подарили рабочую видеокарту, нет картинки, экран чёрный';
 const rows=[['in',symptom],['out','Видеокарта вставлена в ПК?'],['in','Да конечно']];
 const ctx={convId:'synthetic-compiled-graphics71',city:'Оренбург',dir:'kp',partner:'7',channel:'avito',accountTitle:'Иван КП',itemTitle:'Компьютерная помощь',purpose:'inbox',messages:rows.map(([direction,body],i)=>({id:String(i),direction,body}))};
 async function run(op,c){
  const r=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op,args:{ctx:c}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
  const out=JSON.parse(r.body);assert.equal(r.statusCode,200,out.error);assert.equal(out.ok,true);assert.equal(out.auto_enabled,false);assert.equal(out.policy_version,cfg.manifest.policy_version);return out;
 }
 const form=await run('checklist',ctx);assert.equal(form.facts.graphics_scope.kind,'host_diagnostic');assert.ok(!form.rule_ids.includes('DOC-L0152'));
 const extracted=await run('extract',ctx);assert.equal(extracted.economy,true);assert.equal(extracted.rules,true);assert.equal(extracted.lead.device,'компьютер');assert.ok(extracted.lead.topics.includes('компьютер'));assert.equal(extracted.contact_facts.graphics_scope.component_fault_confirmed,false);
 const unknown={...ctx,convId:ctx.convId+'-unknown',messages:[{id:'a',direction:'in',body:symptom}]};
 const pending=await run('checklist',unknown);assert.ok(pending.results.some(r=>r.key==='graphics_host'&&!r.done));assert.ok(!pending.reason.includes('5000'));
 const uncertain=await run('extract',unknown);assert.equal(uncertain.contact_facts.graphics_scope.kind,'device_uncertain');assert.ok(!uncertain.lead.topics.includes('компьютер'));
 const questioned=await run('extract',{...unknown,convId:ctx.convId+'-question',messages:[...unknown.messages,{id:'b',direction:'in',body:'Видеокарта установлена в компьютере?'}]});
 assert.equal(questioned.contact_facts.graphics_scope.kind,'device_uncertain');assert.ok(!questioned.lead.topics.includes('компьютер'));
 assert.equal(nonLoopback,0);assert.equal(calls,5);
 console.log(JSON.stringify({policy:cfg.manifest.policy_version,brain:compiled.ВЕРСИЯ,compiled_normal_forms:2,compiled_extracts:3,source_bound_pc_work_item:true,unconfirmed_host_not_promoted:true,client_question_not_promoted:true,loopback_calls:calls,model_provider_calls:0,external_calls:0,customer_history_uploaded:false,customer_sends:0,crm_writes:0,auto_enabled:false}));
 }catch(e){console.error(e.stack||e);if(stderr)console.error(stderr);process.exitCode=1;}finally{if(child)child.kill();}})();
