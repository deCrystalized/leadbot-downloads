'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const workflow=require('../ext/workflow');
const permission={available:true,mode:'operator_confirmed',auto_enabled:false,acknowledgement:'operator_decision_not_client_consent'};
const reviewed=()=>({ok:true,reviewed_policy:true,auto_enabled:false,policy_version:'synthetic-policy',hard_block:true,
  reason:'Ранее названная стоимость не проверена',operator_review:'Ранее названная стоимость не проверена',
  approval:'Нужно согласование филиала',rule_ids:['synthetic-rule'],manual_creation:{...permission},
  results:[{key:'price_consent',item:'Нет подтверждения цены',done:false},{key:'volume',item:'Объём известен',done:true}]});
function fixture(check=reviewed()){
 const jobs=[],alerts=[],prompts=[];
 const lead={phone:'9001112233',addr:{street:'Ленина',building:'1'},city:'Тула',name:'Клиент',partner:'7',comment:'Ремонт',service_comment:''};
 const s={S:{id:'synthetic-manual',dir:'kp',lead,ctx:{messages:[]},lastId:'client-1',prep:{ok:true,cityId:'synthetic-city',cityText:'Тула'},check},
  LC_WORKFLOW:workflow,формаЭтого:()=>true,задачаИдёт:()=>jobs.length?{ход:{}}:null,кнопкаФормы:()=>{},readForm:()=>({lead:structuredClone(lead),sel:{cityId:'synthetic-city'}}),
  отпечатокФормы:f=>JSON.stringify(f),panel:{querySelectorAll:()=>[],querySelector:()=>null},визитПроблема:()=>({}),прошлыйАдрес:()=>false,белаяНаБТ:()=>false,историяКлиента:()=>null,
  alertBox:x=>alerts.push(x),confirm:x=>{prompts.push(x);return s.answer},answer:true,ручноеРазрешение:null,
  показатьРучноеПодтверждение:(review,f,proceed)=>{prompts.push(review.warnings.join('\n'));if(s.answer)proceed()},
  применитьЗакреп:()=>{},location:{origin:'https://synthetic.invalid'},LC_TG:{кодИсточника:()=>''},sentList:()=>[],кодАккаунта:()=>'',новыйId:()=> 'synthetic-job',копия:structuredClone,безКода:()=>'',
  минимумДоВизита:()=>60,визитАвто:()=>false,окноКлиента:()=>null,лидБот:()=>false,запустить:x=>jobs.push(x),dirName:()=> 'КП',отмечено:()=>false,
  h:(tag,attrs,...children)=>({tag,attrs,children}),svg:()=>''};
 const code=fs.readFileSync(require.resolve('../ext/content'),'utf8');
 function load(a,b,exportName){const start=code.indexOf(a),end=code.indexOf(b,start);assert.ok(start>=0&&end>start);vm.runInContext(code.slice(start,end)+';globalThis.'+exportName+'='+exportName+';',s)}
 vm.createContext(s);load('  function createNow()','  // снимок → задача:','createNow');
 load('  function главнаяКнопка()','  const кратко =','главнаяКнопка');
 load('  function неПрофильBox()','  /* ДУБЛЬ ВНУТРИ LEADCHAT:','неПрофильBox');
 return {s,jobs,alerts,prompts,lead};
}
test('red policy remains visible and the actual footer offers manual creation',()=>{
 const {s}=fixture();assert.equal(s.главнаяКнопка().label,'Создать с предупреждениями');
 const tree=JSON.stringify(s.неПрофильBox());assert.match(tree,/data-policy-block/);assert.match(tree,/Ранее названная стоимость/);assert.match(tree,/решение оператора/);
});
test('cancel creates nothing and leaves unanswered questions and red rules intact',()=>{
 const {s,jobs,prompts}=fixture();const original=JSON.stringify(s.S.check);s.answer=false;s.createNow();
 assert.equal(jobs.length,0);assert.equal(prompts.length,1);assert.match(prompts[0],/Нет подтверждения цены/);assert.match(prompts[0],/Нужно согласование/);
 assert.equal(JSON.stringify(s.S.check),original);
});
test('confirm creates exactly one snapshot with original warnings, no invented consent and no auto grant',()=>{
 const {s,jobs,prompts,alerts}=fixture();s.createNow();s.createNow();assert.equal(jobs.length,1);assert.equal(prompts.length,1);assert.equal(alerts.length,0);
 const job=jobs[0];assert.equal(job.manualReview.operator_confirmed,true);assert.equal(job.manualReview.last_message_id,'client-1');
 assert.equal(job.manualReview.policy_version,'synthetic-policy');assert.equal(job.manualReview.warnings.length,3);
 assert.equal(s.S.check.hard_block,true);assert.equal(s.S.check.results[0].done,false);assert.equal(s.S.check.auto_enabled,false);
 assert.equal(job.lead.comment,'Ремонт');assert.ok(!job.lead.service_comment.includes('согласен'));
 s.S.check.reason='Новое замечание';assert.equal(job.manualReview.warnings[0],'Ранее названная стоимость не проверена');
});
test('a new attempt, form change or dialogue never inherits a prior confirmation',()=>{
 const {s,jobs,prompts,lead}=fixture();s.createNow();jobs.length=0;s.S.id='synthetic-second';s.S.lastId='client-2';
 s.S.check=reviewed();s.S.check.reason='Новый риск';s.S.check.operator_review='Новый риск';lead.addr.building='2';s.answer=false;s.createNow();
 assert.equal(jobs.length,0);assert.equal(prompts.length,2);assert.match(prompts[1],/Новый риск/);assert.equal(s.S.manualReview,undefined);
});
test('map warnings can be reviewed manually but remain strict for the assistant',()=>{
 const {s,jobs,prompts}=fixture();s.S.terr={ok:false,mismatch:true,error:'Другой город по карте'};s.createNow();
 assert.equal(jobs.length,1);assert.match(prompts[0],/Другой город по карте/);assert.equal(workflow.territoryIssue(s.S.terr,s.S.lead),'Другой город по карте');
});
test('unsupported or stale manual capability cannot bypass a red rule',()=>{
 for(const permissionUpdate of [undefined,{...permission,auto_enabled:true},{...permission,mode:'auto'},{...permission,acknowledgement:'client_consented'}]){
  const check=reviewed();check.manual_creation=permissionUpdate;const {s,jobs,alerts,prompts}=fixture(check);s.createNow();
  assert.equal(jobs.length,0);assert.equal(prompts.length,0);assert.equal(alerts.length,1);
 }
});
test('missing required fields, wrong routed branch, stale policy, duplicate and visit constraints still stop',()=>{
 for(const modify of [x=>x.lead.phone='',x=>x.lead.addr={},x=>x.s.S.check.crm_route={city_id:'709'},
  x=>x.s.S.check.reviewed_policy=false,x=>x.s.визитПроблема=()=>({block:'Неверная дата',field:'visit_time'}),
  x=>x.s.историяКлиента=()=>({action:'вернуть',ref:{id:'123'}})]){
  const x=fixture();modify(x);x.s.createNow();assert.equal(x.jobs.length,0);assert.equal(x.prompts.length,0);assert.equal(x.alerts.length,1);
 }
});
test('a normal complete form creates without the extra warning dialog',()=>{
 const check=reviewed();check.hard_block=false;check.reason='';check.operator_review='';check.approval='';check.results=[];
 const {s,jobs,prompts}=fixture(check);s.createNow();assert.equal(jobs.length,1);assert.equal(prompts.length,0);assert.equal(jobs[0].manualReview,undefined);
});
test('attempt checkpoint contains the manual decision even before a CRM result',()=>{
 const {s,jobs}=fixture();s.createNow();const code=fs.readFileSync(require.resolve('../ext/content'),'utf8');
 const start=code.indexOf('  const записьЗадачи ='),end=code.indexOf('  // другая вкладка начала',start);s.ВКЛАДКА='synthetic-tab';
 vm.runInContext(code.slice(start,end)+';globalThis.record=записьЗадачи;',s);
 const row=s.record({...jobs[0],ход:{этап:'start'}});assert.equal(row.manualReview.operator_confirmed,true);assert.equal(row.manualReview.warnings.length,3);
});
test('changing form fields or reviewed policy while the dialog is open invalidates the displayed confirmation',()=>{
 for(const mutate of [x=>x.lead.addr.building='99',x=>x.s.S.check={...x.s.S.check,policy_version:'new-policy'},x=>x.s.S.lastId='new-message']){
  const x=fixture();let callback;x.s.показатьРучноеПодтверждение=(_r,_f,proceed)=>{callback=proceed};
  x.s.createNow();assert.equal(x.jobs.length,0);mutate(x);callback();assert.equal(x.jobs.length,0);assert.match(x.alerts[0],/изменились/);
 }
});
test('a forged callback argument cannot skip the inline review',()=>{
 const {s,jobs,prompts}=fixture();s.answer=false;s.createNow({signature:'fake',state:s.S,check:s.S.check});assert.equal(jobs.length,0);assert.equal(prompts.length,1);
});
