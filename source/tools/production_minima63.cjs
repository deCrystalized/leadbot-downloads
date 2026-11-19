'use strict';
const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const manifest=JSON.parse(fs.readFileSync(require('node:path').resolve(__dirname,'../test-artifacts/deploy-manifest.json')));
const pid=cp.execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
const env=Object.fromEntries(fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').filter(Boolean).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
const token='test-only-quoted-service-check',objects=new Map([['brain/tokens.json',{tokens:[{id:env.LEADBOT_PERSONAL_OWNER_ID,sha:crypto.createHash('sha256').update(token).digest('hex'),label:'offline synthetic check'}]}]]);
const store={get:async(k,d)=>structuredClone(objects.has(k)?objects.get(k):d),put:async(k,v)=>objects.set(k,structuredClone(v))};
const compiled=require('/opt/lead-centre/brain/dist/index.js'),handler=compiled.создать({env,store,log:()=>{},sleep:async()=>{}});
(async()=>{
const cases=[
 ['hanging','mnc','Сколько стоит повесить карниз? Стены бетон.','От 800 рублей, точнее на месте','Да, устраивает',false],
 ['fixed','mnc','Цена повесить карниз. Бетон.','800 рублей работа будет','Да',true],
 ['pending','mnc','Повесить карниз','От 800 рублей',null,true],
 ['printer','kp','Принтер Canon не печатает','От 500 рублей такая услуга, точнее на месте','Хорошо. Вам завтра удобно? Потому что не знаю что с ним делать',false],
 ['cap','mnc','Повесить карниз','От 800 рублей','Бюджет максимум 800 рублей',true],
 ['fee','kp','Canon не печатает. Сколько стоит диагностика?','Диагностика от 500 рублей','Да',true]
];
for(const [name,dir,job,quote,reply,hard] of cases){
 const ctx={convId:'synthetic-production-minima58-'+name,city:'Череповец',dir,partner:'7',channel:'avito',accountTitle:dir==='mnc'?'Михаил МНЧ':'Новый КП',origin:'В75',itemTitle:dir==='mnc'?'Мастер на час':'Ремонт принтеров',messages:[{id:'job',direction:'in',body:job},{id:'quote',direction:'out',body:quote},...(reply?[{id:'answer',direction:'in',body:reply}]:[])]};
 const res=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'checklist',args:{ctx}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});assert.equal(res.statusCode,200);const out=JSON.parse(res.body);assert.equal(out.auto_enabled,false);assert.equal(out.policy_version,manifest.policy_version);assert.equal(out.hard_block,hard,name);assert.deepEqual(out.manual_creation,{mode:'operator_confirmed',available:true,auto_enabled:false,acknowledgement:'operator_decision_not_client_consent'});
 if(name==='fixed'){assert.equal(out.price_review.quote,quote);assert.match(out.price_review.recovery,/от 800/)}
 if(!hard){const r=out.results.find(r=>r.key==='price_consent');assert.equal(r.done,true);assert.equal(r.evidence.length,2)}
}
for(const answered of [false,true]){
 const ctx={convId:'synthetic-production-fee58-'+answered,city:'Череповец',dir:'kp',partner:'7',channel:'avito',accountTitle:'Новый КП',origin:'С78',itemTitle:'Ремонт принтеров',messages:[{id:'job',direction:'in',body:'Принтер Canon не печатает. Сколько стоит ремонт и выезд?'},{id:'quote',direction:'out',body:'От 500 рублей такая услуга'},{id:'yes',direction:'in',body:'Хорошо'},...(answered?[{id:'fee',direction:'out',body:'Выезд и диагностика бесплатны при выполнении работ. При отказе от работ стоимость составит 1000 рублей.'},{id:'yes2',direction:'in',body:'Да'}]:[])]};
 const res=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'checklist',args:{ctx}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});assert.equal(res.statusCode,200);const out=JSON.parse(res.body);assert.equal(out.auto_enabled,false);assert.equal(out.results.find(r=>r.key==='partner_visit_terms').done,answered);assert.equal(out.hard_block,!answered);
}
assert.equal(compiled.ВЕРСИЯ,manifest.brain_version);console.log(JSON.stringify({installed_minima_cases:cases.length+2,actual_browser_form_verified:false,customer_history_uploaded:false,customer_sends:0,crm_writes:0,auto_enabled:false}));
})().catch(e=>{console.error(e.stack);process.exitCode=1});
