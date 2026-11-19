'use strict';
const fs=require('node:fs'),{createRequire}=require('node:module');
const readline=require('node:readline'),path=require('node:path'),assert=require('node:assert/strict');
const rl=readline.createInterface({input:process.stdin});
let first,serial=0;const initial=new Promise(resolve=>{first=resolve}),pending=new Map();
rl.on('line',raw=>{
  const value=JSON.parse(raw);
  if(value.kind==='seed'){first(value.data);return}
  const resolve=pending.get(value.id);if(!resolve)throw Error('Unknown owned IPC response');
  pending.delete(value.id);resolve(value);
});
function rpc(method,route,body){
  const id=++serial;
  return new Promise((resolve,reject)=>{
    pending.set(id,value=>value.error?reject(Error(value.error)):resolve(value.data));
    process.stdout.write(JSON.stringify({kind:'request',id,method,route,body})+'\n');
  });
}

(async()=>{
  const seed=await initial;
  seed.proposal=await prepareOriginal(seed);
  const client=path.join(__dirname,'extension');
  const file=path.join(client,'tests/test_native_office257.test.js');
  const all=fs.readFileSync(file,'utf8'),end=all.indexOf("\ntest('actual client/host/offscreen/CRM");
  assert.ok(end>0);let code=all.slice(0,end);
  function replace(before,after){assert.equal(code.split(before).length,2,before);code=code.replace(before,after)}
  replace('const P=randomUUID(),O=randomUUID(),RUN=randomUUID(),CID=randomUUID(),LEASE=randomUUID();',
    'const P=seed.principal_id,O=seed.operator_id,RUN=seed.run_id,CID=seed.cid,LEASE=seed.lease_id;');
  replace("const H='a'.repeat(64),SOURCE='b'.repeat(64),FORM='c'.repeat(64),SNAP='d'.repeat(64),MSGS='e'.repeat(64);",
    'const H=seed.work_id,SOURCE=seed.source_sha256,FORM=seed.form.form_reference,SNAP=null,MSGS=seed.message_revision;');
  replace('now:1000000,events:[]','now:seed.now_ms,events:[]');
  replace("f.host=Host.create(chrome,[ORIGIN],{now:()=>f.now,uuid:randomUUID});",
    'let chosen=false;f.host=Host.create(chrome,[ORIGIN],{now:()=>f.now,uuid:()=>chosen?randomUUID():(chosen=true,seed.executor_id)});');
  const requiredStart=code.indexOf("  const required=['город'");
  const requiredEnd=code.indexOf(';',requiredStart);
  assert.ok(requiredStart>0&&requiredEnd>requiredStart);
  code=code.slice(0,requiredStart)+'  const required=seed.required_fields'+code.slice(requiredEnd);
  replace('  const form={ok:true,auto_enabled:false,',
    "  const form={...seed.form,ok:true,completion_mode:'crm_only',auto_enabled:false,");
  replace("form_reference:FORM,research_job_id:'synthetic-ready-form',policy_version:'synthetic-policy',",
    'form_reference:FORM,research_job_id:seed.form.research_job_id,policy_version:seed.form.policy_version,');
  replace("followup:{required:true,telegram_ready:true,code:'7'}",
    "followup:{mode:'crm_only',required:false,telegram_ready:false}");
  const apiStart=code.indexOf('  const api={'),apiEnd=code.indexOf('  const offscreenCode=',apiStart);
  assert.ok(apiStart>0&&apiEnd>apiStart);
  code=code.slice(0,apiStart)+`  const api={
    get:async route=>{f.calls.push(['GET',route]);return rpc('GET',route)},
    post:async(route,body)=>{f.calls.push(['POST',route]);return rpc('POST',route,body)},
  };\n`+code.slice(apiEnd);
  const proposalStart=code.indexOf('  f.proposal=structuredClone(');
  const proposalEnd=code.indexOf('  function envelope()',proposalStart);
  assert.ok(proposalStart>0&&proposalEnd>proposalStart);
  code=code.slice(0,proposalStart)+'  f.proposal=structuredClone(seed.proposal);\n'+code.slice(proposalEnd);
  replace("const code=fs.readFileSync(require.resolve('./test_crm_results234.test.js'),'utf8');",
    "let code=fs.readFileSync(require.resolve('./test_crm_results234.test.js'),'utf8');"+
    "code=code.replace(\"assert.equal(url,CRM.BASES.mnc+\",\"assert.equal(url,CRM.BASES[options.dir||'mnc']+\");"+
    "code=code.replace(\"const fields=[field('Customer[phone]')\",\"const fields=[...['street','building','office','entrance','floor','locality'].map(k=>field('Customer[address_'+k+']')),field('Customer[phone]')\");");
  replace("f.core=coreFixture(options.note?{note:'Проверенный комментарий',omitPartnerField:true}:{});",
    "f.core=coreFixture({dir:seed.proposal.dir});");
  const exported={exports:{}};
  new Function('require','module','seed','rpc',code+'\nmodule.exports=setup;')(
    createRequire(file),exported,seed,rpc);
  const f=exported.exports();
  const crm=actualCardFixture(f,seed,client);
  await f.runJob();
  if(seed.scenario==='lost_ack'||seed.scenario==='duplicate_match'){
    await rpc('CONTROL','stop');f.restart();await f.runJob();
  }
  if(seed.scenario==='review_not_saved'){
    f.restart();await f.runJob();
  }
  const records=[...f.store.values()].filter(x=>x?.scope?.work_id===seed.work_id);
  const result={telegramReads:seed.telegramReads,prepared_proposal:seed.proposal,state:f.client.state(),physical_crm_posts:f.physical,
    records:records.map(x=>({state:x.state,created_id:x.created?.id||null,reason_code:x.reason_code,
      completion_mode:x.completion_mode,dialog_closed:x.dialog_closed,
      telegram_confirmed:x.telegram_confirmed})),operations:f.calls,
    events:f.events,CRM_POST_count:f.core.calls.filter(x=>x.kind==='POST').length,
    submitted:crm.submitted(),verified:crm.reports,createOutcomes:crm.createOutcomes};
  process.stdout.write(JSON.stringify({kind:'done',result})+'\n');
  rl.close();process.stdin.pause();
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;rl.close();process.stdin.pause()});

async function prepareOriginal(input){
  const root=path.join(__dirname,'extension');
  const Workflow=require(path.join(root,'ext/workflow'));
  const vm=require('node:vm');
  const code=fs.readFileSync(path.join(root,'ext/content.js'),'utf8');
  let telegramReads=0;
  const scope={LC_WORKFLOW:Workflow,LC_EXTRACT:{точкаАдреса:()=>({})},LC_TG:{кодИсточника:()=> 'С1'},
    personalDialog:async()=>({conv:{client:{name:input.seed.lead.name}}}),
    разобратьГотовность:async()=>({st:'ready',A:{lead:{...structuredClone(input.seed.lead),service_comment:''},conv:{},ctx:{}}}),
    withSource:lead=>lead,копия:structuredClone,наДваДня:()=>false,техника:()=>'',партнёрКодом:()=> '624',
    send:async()=>structuredClone(input.seed.prep),территория:async()=>structuredClone(input.seed.territory),
    группыTG:async()=>{telegramReads++;throw Error('No Telegram lookup in CRM-only integration')},
    чатАвито:()=>null,разделСозданных:async()=>false,location:{origin:'https://lead.test'}};
  vm.createContext(scope);
  const start=code.indexOf('  async function workflowPrepare('),end=code.indexOf('  const workflowAdapters=',start);
  assert.ok(start>=0&&end>start);
  vm.runInContext(code.slice(start,end)+';globalThis.prepare=workflowPrepare;',scope);
  const value=await scope.prepare({ctx:{convId:input.cid,channel:'avito'},operatorId:input.operator_id},
    {revision:input.form.revision},input.form);
  const source=fs.readFileSync(path.join(root,'ext/native-office.js'),'utf8');
  const declaration=source.match(/  const proposalKeys=\[[\s\S]*?\];/)?.[0];assert.ok(declaration);
  const fields={};vm.createContext(fields);vm.runInContext(declaration+';this.keys=proposalKeys;',fields);
  input.telegramReads=telegramReads;
  return JSON.parse(JSON.stringify(Object.fromEntries(fields.keys.map(k=>[k,value[k]]))));
}

function actualCardFixture(f, seed, extension){
  const vm=require('node:vm');
  const CITY='CustomerRequest[city_id]',PARTNER='CustomerRequest[partner_id]',REVIEW='CustomerRequest[is_req_fback]';
  assert.equal(String(seed.proposal.lead.partner),'624');
  assert.equal(seed.proposal.lead.review,true);
  const findDuplicates = f.core.scope.searchAllBases;
  f.core.scope.searchAllBases = async phone => {
    assert.equal(String(phone).replace(/\D/g, '').slice(-10),
      String(seed.proposal.lead.phone).replace(/\D/g, '').slice(-10));
    f.events.push('DUPLICATE_LOOKUP');
    if(seed.scenario==='duplicate_match')
      return {found:[{dir:seed.proposal.dir,id:'7654321',status:'Ожидает'}],unchecked:[]};
    return findDuplicates(phone);
  };
  const createOutcomes=[];
  const create=f.core.scope.executeCreate;
  f.core.scope.executeCreate=async fields=>{
    const outcome=await create(fields);
    createOutcomes.push({
      skipped:outcome.skipped===true,dispatched:outcome.crm_create_dispatched===true,
      existing_case_identified:typeof outcome.error==='string'&&outcome.error.includes('№7654321'),
    });
    return outcome;
  };
  const raw=f.core.scope.fetchDoc, reports=[];
  f.core.scope.fetchDoc=async url=>{
    const doc=await raw(url),form=doc.querySelector('#customerRequestForm');
    if(!form) return doc;
    const fields=form.elements;
    if(!fields[PARTNER].options.some(option=>option.value==='id-624'))
      fields[PARTNER].options.push({value:'id-624',textContent:'624'});
    if(!fields[REVIEW]){
      const hidden={name:REVIEW,type:'hidden',value:'0'};
      const checkbox={name:REVIEW,type:'checkbox',tagName:'INPUT',value:'1',checked:false};
      fields.push(hidden,checkbox);
      fields[REVIEW]=[hidden,checkbox];
    }
    if(seed.scenario==='wrong_branch_form'&&!Object.hasOwn(fields[CITY],'syntheticWrongOption')){
      Object.defineProperty(fields[CITY],'value',{get:()=> '999',set:()=>{}});
      fields[CITY].syntheticWrongOption=true;
    }
    if(seed.scenario==='review_not_saved'&&new URL(url).pathname==='\/admin\/domain\/customer-request\/update')
      fields[REVIEW][1].checked=false;
    return doc;
  };
  const source=fs.readFileSync(path.join(extension,'ext/crm.js'),'utf8');
  const start=source.indexOf('  async function verifyCreated(');
  const end=source.indexOf('\n  /* СОЗДАНИЕ',start);
  assert.ok(start>=0&&end>start);
  vm.runInContext(source.slice(start,end)+';this.actualVerifyCreated=verifyCreated;',f.core.scope);
  f.core.scope.verifyCreated=async(...args)=>{
    f.events.push('CARD_READ');
    const value=await f.core.scope.actualVerifyCreated(...args);
    reports.push({id:String(args[1]),fields:[...value.fields],diffs:[...value.diffs]});
    return value;
  };
  const submitted=()=>f.core.calls.filter(call=>call.kind==='POST').map(call=>({
    branch:call.body.get(CITY),partner:call.body.get(PARTNER),review:call.body.getAll(REVIEW).at(-1),
  }));
  return {submitted,reports,createOutcomes};
}
