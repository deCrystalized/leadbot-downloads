'use strict';
// Installed compiled map -> authenticated read-only geography API -> visit slot.
// Map transport/store are isolated; no customer or CRM write capability.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),manifest=JSON.parse(fs.readFileSync(root+'/test-artifacts/deploy-manifest.json','utf8'));
const brain=require('/opt/lead-centre/brain/dist/index.js');
if(brain.ВЕРСИЯ!==manifest.brain_version)throw Error('Wrong compiled version');
const pid=cp.execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
const service=fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').find(x=>x.startsWith('LEADBOT_SERVICE_TOKEN='));
if(!service)throw Error('Missing internal geography connection');
const token='synthetic-map-verification',values=new Map([['brain/tokens.json',{tokens:[{id:'synthetic-map',label:'synthetic',sha:crypto.createHash('sha256').update(token).digest('hex')}]}]]);
const run=brain.создать({env:{LEADBOT_SERVICE_TOKEN:service.slice(service.indexOf('=')+1)},
 store:{get:async(k,d)=>structuredClone(values.has(k)?values.get(k):d),put:async(k,v)=>values.set(k,structuredClone(v))},log:()=>{},sleep:async()=>{},
 запрос:async(url,init)=>{
  if(url==='http://127.0.0.1:8788/api/extension/assistant'){
   if(JSON.parse(init.body).action!=='geography')throw Error('Non-geography request rejected');
   return fetch(url,{...init,signal:AbortSignal.timeout(3000)});
  }
  if(url.includes('map-widget'))return{text:async()=>fs.readFileSync(root+'/test-artifacts/custom-maps-20261018/kp.html','utf8')};
  throw Error('Unexpected transport rejected');
 }});
(async()=>{
 const cases=JSON.parse(fs.readFileSync(root+'/test-artifacts/custom-maps-20261018/mytishchi-expected.json','utf8')),results=[];
 for(const c of cases){
  const response=await run({httpMethod:'POST',headers:{'x-brain-auth':token},requestContext:{identity:{sourceIp:'127.0.0.1'}},
   body:JSON.stringify({op:'territory',args:{city:'Мытищи',dir:'kp',tech:'Компьютер',pt:c.point,ptLocality:'Мытищи'}})});
  const out=JSON.parse(response.body),passed=response.statusCode===200&&out.ok===true&&out.hours===c.expected_hours&&out.approval===false&&out.far===false;
  results.push({zone:c.zone,expected_hours:c.expected_hours,hours:out.hours,approval:out.approval,far:out.far,passed});
 }
 console.log(JSON.stringify({installed_map_slot_checks:results,passed:results.every(r=>r.passed),policy_version:manifest.policy_version,customer_sends:0,crm_writes:0}));
 if(!process.argv.includes('--observe')&&results.some(r=>!r.passed))process.exitCode=1;
})().catch(()=>{console.log(JSON.stringify({error:'Map verification failed; no secret or transport URL logged'}));process.exitCode=1});
