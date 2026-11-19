'use strict';
// Installed compiled-entry checks; all transports and storage are synthetic.
// No environment secrets, customer dialogues, CRM writes or live grants.
const fs=require('node:fs'),crypto=require('node:crypto'),path=require('node:path');
const manifest=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../test-artifacts/deploy-manifest.json'),'utf8'));
const brain=require('/opt/lead-centre/brain/dist/index.js');
if(brain.ВЕРСИЯ!==manifest.brain_version)throw Error('Compiled version mismatch');
const token='synthetic-far-trip-verification';
const values=new Map([['brain/tokens.json',{tokens:[{id:'synthetic-far-trip',label:'synthetic',sha:crypto.createHash('sha256').update(token).digest('hex')}]}]]);
const store={get:async(k,d)=>structuredClone(values.has(k)?values.get(k):d),put:async(k,v)=>values.set(k,structuredClone(v))};
const run=brain.создать({env:{YANDEX_GEOCODER_KEY:'synthetic'},store,log:()=>{},sleep:async()=>{},
 запрос:async()=>({text:async()=>'',json:async()=>({})})});
const centre=[36.1923,51.727];
const point=distance=>[centre[0],centre[1]+distance/6371*180/Math.PI];
(async()=>{
 const results=[];
 for(const [dir,tech,distance,approval,far] of [
  ['kp','Компьютер',36.4,false,true],['kp','Компьютер',36.9,false,true],
  ['kp','Компьютер',36.99,false,true],['kp','Компьютер',37,true,true],
  ['kp','Телевизор',10,true,true],['bt','Стиральная машина',10,true,false],['mnc','Смеситель',10,true,false]]){
  const response=await run({httpMethod:'POST',headers:{'x-brain-auth':token},requestContext:{identity:{sourceIp:'127.0.0.1'}},
   body:JSON.stringify({op:'territory',args:{dir,tech,city:'Курск',pt:point(distance),ptLocality:'Дальняя Деревня'}})});
  const out=JSON.parse(response.body);
  if(response.statusCode!==200||out.ok!==true||out.approval!==approval||out.far!==far)throw Error('Installed far-trip case failed: '+[dir,tech,distance].join('/'));
  results.push({dir,distance,approval:out.approval,far:out.far});
 }
 console.log(JSON.stringify({installed_far_trip:'passed',v:brain.ВЕРСИЯ,policy_version:manifest.policy_version,cases:results,customer_sends:0,crm_writes:0}));
})().catch(e=>{console.log(JSON.stringify({error:e.message}));process.exitCode=1});
