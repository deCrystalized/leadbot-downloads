'use strict';
// Read-only map probes through the installed compiled entry. No live dialogue,
// CRM transport, persisted budget state, assistant session, or write grant.
const fs=require('fs'),cp=require('child_process'),crypto=require('crypto');
const pid=cp.execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
const actualEnv=Object.fromEntries(fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').filter(Boolean).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
const compiled=require('/opt/lead-centre/brain/dist/index.js');
const manifest=JSON.parse(fs.readFileSync(require('path').resolve(__dirname,'../test-artifacts/deploy-manifest.json'),'utf8'));
if(compiled.ВЕРСИЯ!==manifest.brain_version)throw Error('Wrong compiled version');
const token='synthetic-locality-probe-token';
function store(){const data=new Map([['brain/tokens.json',{tokens:[{id:'synthetic-locality',label:'synthetic',sha:crypto.createHash('sha256').update(token).digest('hex')}]}]]);return{get:async(k,d)=>structuredClone(data.has(k)?data.get(k):d),put:async(k,v)=>data.set(k,structuredClone(v))};}
function event(args){return{httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'territory',args}),requestContext:{identity:{sourceIp:'127.0.0.1'}}};}
function feature(city,district){return{GeoObject:{Point:{pos:city==='Омск'?'73.37 54.99':'84.99 56.41'},metaDataProperty:{GeocoderMetaData:{precision:'exact',kind:'house',text:city+', '+district+', Королёва 8',Address:{Components:[{kind:'locality',name:city},{kind:'district',name:district},{kind:'street',name:'улица Королёва'},{kind:'house',name:'8'}]}}}}};}
const args={dir:'mnc',city:'Омск',settlement:'Южные ворота',street:'Королева',building:'8',partner:'7'};
(async()=>{
 // /proc exposes the startup environment. The running VPS also loads its
 // existing config from storage; reproduce that read-only precedence here.
 if(process.argv.includes('--maps')&&actualEnv.S3_URL){
  try{
   const r=await fetch(String(actualEnv.S3_URL).replace(/\/+$/,'')+'/'+(actualEnv.BUCKET||'lc-team-b1g1hrbbp0j5')+'/brain/config.json',{signal:AbortSignal.timeout(5000)});
   if(r.ok)for(const [k,v] of Object.entries(await r.json()))if(typeof v==='string'&&!(k in actualEnv))actualEnv[k]=v;
  }catch(_e){}
 }
 const queries=[];
 const mock=compiled.создать({env:{...actualEnv,TEAM_URL:'',BRAIN_TOKEN:'',YANDEX_GEOCODER_KEY:'synthetic'},store:store(),log:()=>{},sleep:async()=>{},запрос:async (url,init)=>{
  if(url.startsWith('http://127.0.0.1:8788/'))return fetch(url,{...init,signal:AbortSignal.timeout(12000)});
  if(url.includes('geocode-maps')){const q=new URL(url).searchParams.get('geocode');queries.push(q);return{json:async()=>({response:{GeoObjectCollection:{featureMember:q.startsWith('Южные ворота,')?[feature('Зональная Станция','микрорайон Южные Ворота')]:[feature('Омск','')]}}})};}
  return{text:async()=>'',json:async()=>({})};
 }});
 const response=await mock(event(args)),body=JSON.parse(response.body);
 if(response.statusCode!==200||body.ok!==false||body.mismatch!==true||!body.candidates?.some(c=>c.locality==='Зональная Станция'&&c.house)
  ||queries.find(q=>q.includes('Королева'))!=='Южные ворота, Королева, 8')throw Error('Installed locality-first protection failed');
 const formEvent={...event({}),body:JSON.stringify({op:'checklist',args:{dir:'mnc',ctx:{convId:'synthetic-installed-location-checklist',
  city:'Омск',dir:'mnc',partner:'7',channel:'avito',accountTitle:'Мастер МНЧ',itemTitle:'Сборка мебели',
  messages:[{id:'a',direction:'in',body:'Шкаф собран, нужно поставить двери. Королева 8 южные ворота этаж 3 кв 191'}]}}})};
 const formResponse=await mock(formEvent),form=JSON.parse(formResponse.body);
 if(formResponse.statusCode!==200||!form.hard_block||!form.territory_review?.mismatch||form.facts?.address?.settlement!=='южные ворота')throw Error('Installed server form location gate failed');
 console.log(JSON.stringify({compiled_locality_first:'passed',compiled_server_checklist:'passed',v:compiled.ВЕРСИЯ,policy_version:manifest.policy_version,other_region_blocks:true,customer_sends:0,crm_writes:0}));
 if(process.argv.includes('--maps')){
  if(!actualEnv.YANDEX_GEOCODER_KEY){console.log(JSON.stringify({actual_map_probe:'unavailable',reason:'geocoder_not_configured'}));return;}
  const live=compiled.создать({env:{...actualEnv,TEAM_URL:'',BRAIN_TOKEN:''},store:store(),log:()=>{},sleep:async()=>{}});
  const result=await live(event(args)),out=JSON.parse(result.body);
  const candidatePlaces=(out.candidates||[]).map(c=>({locality:c.locality,house:c.house}));
  console.log(JSON.stringify({actual_map_probe:out.mismatch&&candidatePlaces.some(c=>c.house)?'other_region_detected':'not_confirmed',http:result.statusCode,ok:out.ok,mismatch:out.mismatch,qualified_location_unverified:out.qualified_location_unverified,candidate_places:candidatePlaces,customer_sends:0,crm_writes:0}));
  const actualFormResponse=await live(formEvent),actualForm=JSON.parse(actualFormResponse.body);
  if(actualFormResponse.statusCode!==200||!actualForm.hard_block||!actualForm.territory_review?.mismatch)throw Error('Actual server form allowed the other region');
  console.log(JSON.stringify({actual_normal_form:'wrong_region_blocked',hard_block:actualForm.hard_block,auto_enabled:actualForm.auto_enabled,customer_sends:0,crm_writes:0}));
  // Owner confirmed the actual region separately; do not infer this city
  // from a neighbourhood name. Coverage and approval remain map decisions.
  const correctedResponse=await live(event({...args,city:'Томск'})),corrected=JSON.parse(correctedResponse.body);
  if(correctedResponse.statusCode!==200||!corrected.ok||!corrected.address_verified||corrected.mismatch)throw Error('Confirmed-region full address not resolved');
  console.log(JSON.stringify({actual_confirmed_region:'Томск',address_verified:corrected.address_verified,locality:corrected.locality,
   branch:corrected.branch,approval:corrected.approval,in_map:corrected.inMap,hours:corrected.hours,customer_sends:0,crm_writes:0}));
 }
})().catch(()=>{console.log(JSON.stringify({error:'Installed locality verification failed; no secret or request URL logged'}));process.exitCode=1});
