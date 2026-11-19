'use strict';
const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const manifest=JSON.parse(fs.readFileSync(require('node:path').resolve(__dirname,'../test-artifacts/deploy-manifest.json')));
const pid=cp.execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
const env=Object.fromEntries(fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').filter(Boolean).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
const token='test-only-quoted-service-check',objects=new Map([['brain/tokens.json',{tokens:[{id:env.LEADBOT_PERSONAL_OWNER_ID,sha:crypto.createHash('sha256').update(token).digest('hex'),label:'offline synthetic check'}]}]]);
const store={get:async(k,d)=>structuredClone(objects.has(k)?objects.get(k):d),put:async(k,v)=>objects.set(k,structuredClone(v))};
const compiled=require('/opt/lead-centre/brain/dist/index.js'),handler=compiled.создать({env,store,log:()=>{},sleep:async()=>{}});
const rows=[['in','Сколько стоит замена подсветки телевизора DEXP?'],['out','Точную стоимость назову после осмотра техники.'],['in','А хоть примерно сколько стоит?'],['out','Замена подшипников от 500 рублей, запчасти отдельно'],['in','Да']];
const ctx={convId:'synthetic-production-wrong-service54',city:'Воткинск',dir:'kp',partner:'7',channel:'avito',accountTitle:'Пётр КП',itemTitle:'Ремонт телевизоров',origin:'В89',messages:rows.map(([direction,body],i)=>({id:String(i),direction,body,sender_type:direction==='in'?'client':'operator'}))};
(async()=>{
 for(const op of ['checklist','assistant']){
  const res=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op,args:op==='checklist'?{ctx}:{action:'preview',ctx}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
  const out=JSON.parse(res.body);assert.equal(res.statusCode,200);assert.equal(out.ok,true);assert.equal(out.auto_enabled,false);assert.equal(out.policy_version,manifest.policy_version);assert.match(out.reason,/подшипник/);assert.match(out.reason,/телевизор/);
  if(op==='checklist'){assert.equal(out.hard_block,true);assert.equal(out.geography.crm_city,'Ижевск');assert.equal(out.geography.settlement,'Воткинск');assert.equal(out.geography.far_trip,true);assert.equal(out.price_service_conflict.message_id,'3');}
  else {assert.equal(out.action,'handoff');assert.equal(out.reply,'');}
 }

 const written='Сломалась боковая доска кровати и ножка. Нужен ремонт.';
 const transcript='Сломалась ножка кровати и спинка. Это расшифровка голосового.';
 const bed={convId:'synthetic-production-written-bed55',city:'Ярославль',dir:'mnc',partner:'7',channel:'avito',accountTitle:'Анатолий МНЧ',itemTitle:'Ремонт мебели',origin:'В80',messages:[{id:'written',direction:'in',body:written},{id:'voice-copy',direction:'in',body:transcript,voice_transcript:transcript,attachments:[{kind:'voice'}]},{id:'scope',direction:'in',body:'Хорошо хотя бы с ремонтом кровати помогите пожалуйста'}]};
 const bedResponse=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'checklist',args:{ctx:bed}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
 const bedOut=JSON.parse(bedResponse.body);assert.equal(bedResponse.statusCode,200);assert.equal(bedOut.auto_enabled,false);assert.equal(bedOut.policy_version,manifest.policy_version);
 const notes=bedOut.facts.task_notes.filter(n=>n.kind==='bed_part_damage');assert.equal(notes.length,1);assert.equal(notes[0].message_id,'written');assert.equal(notes[0].quote,written);assert.equal(notes[0].written,true);assert.equal(bedOut.facts.active_service_scope.message_id,'scope');assert.ok(bedOut.facts.comment_lines.some(line=>line.includes(written)));assert.ok(!bedOut.facts.comment_lines.some(line=>line.includes(transcript)));
 console.log(JSON.stringify({installed_written_bed_parts:'passed',copied_asr_not_written:true,current_repair_scope_retained:true,customer_sends:0,crm_writes:0,auto_enabled:false}));

 const request='Домофона нет, поэтому потребуется набрать по номеру';
 for(const [name,bodies,timing,requested] of [
  ['entry',[request],'upon_arrival',true],
  ['advance',['Домофона нет, поэтому позвоните перед выездом'],'before_visit',true],
  ['withdrawn',[request,'Не набирайте, я буду у входа'],'not_stated',false]
 ]){
  const access={convId:'synthetic-production-access56-'+name,city:'Санкт-Петербург',dir:'mnc',partner:'7',channel:'avito',accountTitle:'Григорий МНЧ',itemTitle:'Монтаж гардин',origin:'С79.2',messages:bodies.map((body,i)=>({id:'access-'+i,direction:'in',body,sender_type:'client'}))};
  const response=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'checklist',args:{ctx:access}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
  const checked=JSON.parse(response.body);assert.equal(response.statusCode,200);assert.equal(checked.ok,true);assert.equal(checked.auto_enabled,false);assert.equal(checked.policy_version,manifest.policy_version);
  assert.equal(checked.facts.call_before_visit,requested);assert.equal(checked.facts.call_timing,timing);assert.equal(checked.facts.intercom_working,false);assert.equal(checked.facts.intercom_present,false);
  if(name==='entry'){assert.equal(checked.facts.evidence.call_before_visit.quote,request);assert.ok(checked.facts.comment_lines.includes('Позвонить при подъезде по просьбе клиента.'));assert.ok(!checked.facts.comment_lines.includes('Позвонить перед выездом по просьбе клиента.'));}
 }
 console.log(JSON.stringify({installed_implicit_access_call:'passed',explicit_advance_kept:true,withdrawal_clears:true,old_customer_intercom_yes_clearing_verified:false,customer_history_uploaded:false,customer_sends:0,crm_writes:0,auto_enabled:false}));

 const doorRows=[['in','Нужно заменить в межкомнатной двери ручку, какая цена?'],['in','Без врезки. Просто замена'],['out','У вас она в наличии уже есть?'],['in','Да'],['in','Цена какая'],['out','От 800 рублей, точнее на месте']];
 const door={convId:'synthetic-production-door57',city:'Саранск',dir:'mnc',partner:'7',channel:'avito',accountTitle:'Михаил МНЧ',itemTitle:'Мастер на час',origin:'В75',messages:doorRows.map(([direction,body],i)=>({id:String(i),direction,body,sender_type:direction==='in'?'client':'operator'}))};
 async function checklist57(ctx){const res=await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'checklist',args:{ctx}}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});const out=JSON.parse(res.body);assert.equal(res.statusCode,200);assert.equal(out.policy_version,manifest.policy_version);assert.equal(out.auto_enabled,false);return out}
 const doorOut=await checklist57(door);assert.equal(doorOut.approval,'');assert.equal(doorOut.hard_block,true);assert.match(doorOut.reason,/явное согласие/);for(const key of ['materials','volume','door_type'])assert.equal(doorOut.results.find(r=>r.key===key).done,true);
 const troitsk={...ctx,convId:'synthetic-production-troitsk57',city:'Челябинск',cityRaw:'Троицк',crmCity:'Челябинск',itemTitle:'Ремонт принтеров',accountTitle:'Дамир КП',messages:[{id:'task',direction:'in',body:'Принтер Epson не печатает'},{id:'address',direction:'in',body:'Троицк 10 квартал дом 28 3 подъезд кв 60'}]};
 const troitskOut=await checklist57(troitsk);assert.equal(troitskOut.facts.client_location.status,'confirmed');assert.equal(troitskOut.facts.client_location.advertised_city,'Троицк');assert.ok(!troitskOut.reason.includes('Клиент назвал другой город'));assert.equal(troitskOut.geography.status,'unknown');assert.ok(!troitskOut.results.some(r=>r.key==='printer_connection'));
 for(const [body,present,working] of [['Домофона нет',false,false],['Домофон не работает',true,false],['Домофон есть',true,null],['Ленина 1',null,null]]){const out=await checklist57({...door,convId:'synthetic-production-presence57-'+String(present)+String(working),messages:[{id:'client',direction:'in',body}]});assert.equal(out.facts.intercom_present,present);assert.equal(out.facts.intercom_working,working)}
 console.log(JSON.stringify({installed_door_and_troitsk:'passed',physical_presence_vs_operation:'passed',unknown_not_absence:true,unconfirmed_branch_not_invented:true,model_calls:0,customer_sends:0,crm_writes:0,auto_enabled:false}));
 assert.equal(compiled.ВЕРСИЯ,manifest.brain_version);console.log(JSON.stringify({compiled_brain:manifest.brain_version,policy:manifest.policy_version,wrong_service_amount_match_blocked:true,normal_form_and_assistant_verified:true,satellite_parent_policy_retained:true,model_calls:0,customer_history_uploaded:false,customer_sends:0,crm_writes:0,auto_enabled:false}));
})().catch(e=>{console.error(e.message);process.exitCode=1});
