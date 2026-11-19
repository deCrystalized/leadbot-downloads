'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const CRM=require('../ext/crm');

function field(name,value='',type='text'){
 return{name,value,type,tagName:'INPUT',disabled:false};
}
function fixture(options={}){
 const code=fs.readFileSync(require.resolve('../ext/crm'),'utf8'),calls=[];
 const fields=[field('Customer[phone]'),field('Customer[first_name]'),field('CustomerRequest[comments]'),
  field('CustomerRequest[comments_service]'),field('CustomerRequest[partner_comment]'),
  field('CustomerRequest[opened_at]'),field('cr_opened_at_time'),field('CustomerRequest[is_zakrep]','0','hidden')];
 for(const [name,id,text]of [['city_id','1','Чита'],['appliance_type_id','2','Мебель'],
   ['appliance_sub_type_id','3','Сборка'],['type','10','Впервые'],['partner_id','7','7']]){
  fields.push({name:'CustomerRequest['+name+']',value:id,tagName:'SELECT',
   options:[{value:id,textContent:text}],replaceChildren(){this.options=[]},append(o){this.options.push(o)},
   querySelectorAll(){return this.options}});
 }
 if(options.omitPartnerField)fields.splice(fields.findIndex(f=>f.name==='CustomerRequest[partner_comment]'),1);
 for(const f of fields)fields[f.name]=f;
 const form={elements:fields};
 const doc={querySelector:()=>form};
 const params={dir:'mnc',lead:{phone:'9000000000',name:'Synthetic',partner:'7',comment:'Synthetic work',addr:{},...(options.note?{partner_note:options.note}:{})},
  sel:{cityId:'1',applId:'2',subId:'3',appl:[{id:'2',text:'Мебель'}],sub:[{id:'3',text:'Сборка'}],type:'Впервые'}};
 let now=1000,profileReads=0;
 const links=ids=>ids.map(id=>({getAttribute:()=>'/admin/domain/customer-request/update?id='+id}));
 const timers=new Map();let timerID=0;
 const scope={BASES:CRM.BASES,CREATE:'/admin/domain/customer-request/create',URL,URLSearchParams,Date:{now:()=>now},
  setTimeout:(fn,ms)=>{const id=++timerID;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id),
  Option:class{constructor(text,value){this.textContent=text;this.value=value}},
  заранее:p=>async()=>p,findCustomerId:async()=>options.existing||options.recover&&calls.some(c=>c.kind==='POST')?{id:'11',count:1}:{id:'',count:0},
  customerStatuses:async()=>[],формаКлиента:()=>options.unreadableHistory?null:{},клиентЗаявкиИз:()=>options.savedCustomer||'11',
  searchAllBases:async()=>({found:[],unchecked:[]}),fetchDoc:async url=>{
   if(url.includes('/customer/update')){
    const ids=options.existing&&profileReads++===0?(options.beforeIDs||[]):(options.afterIDs||[]);
    return{__finalUrl:options.profileURL||url,querySelector:()=>null,querySelectorAll:()=>links(ids)};
   }
   if(url.includes('/customer-request/update')&&options.savedMismatch)fields[options.savedMismatch].value='different';
   return {...doc,__finalUrl:options.savedURL||url};
  },
  setVal:CRM._внутр.setVal,serializeForm:CRM._внутр.serializeForm,
  полеВидаУслуг:()=>fields['CustomerRequest[appliance_sub_type_id]'],
  intercomChoice:()=>({value:null}),intercomWanted:()=>null,ДОМОФОН:'synthetic_intercom',
  pickOption:CRM.pickOption,pickNumber:CRM.pickNumber,NOTES:{service:x=>x},
  ИМЯ:{mnc:'МНЧ'},СЕССИЯ:()=> 'Сессия истекла',имяПоАдресу:()=> 'МНЧ',
  ЖИВЫЕ:/Ожидает/,МОДЕРАЦИЯ:/Модерация/,
  verifyCreated:async()=>{calls.push({kind:'readback'});return{checked:1,diffs:[],fields:['город']}},
  saveComments:async(_base,_id,_note,beforeSubmit)=>{
   calls.push({kind:'followup_read'});
   if(options.hangFollowupRead)await new Promise(resolve=>{scope.finishFollowupRead=resolve});
   if(!(await beforeSubmit()).ok)return false;
   calls.push({kind:'followup_POST'});
   return options.hangFollowup?new Promise(()=>{}):true;
  },
  DOMParser:class{parseFromString(text){return{querySelector:selector=>
   selector.includes('password')&&text==='synthetic-login'?{}:selector==='#customerRequestForm'&&options.validationForm?{}:null}}},
  formErrors:()=>options.errors||[],
  fetch:async(url,init)=>{
   assert.equal(init.method,'POST');assert.equal(url,CRM.BASES.mnc+'/admin/domain/customer-request/create'+(options.existing?'?customer_id=11':''));
   calls.push({kind:'POST',body:new URLSearchParams(init.body)});
    if(options.hang)return new Promise(resolve=>{scope.finishTransport=resolve});
   return{status:options.status??200,url:options.url??url,
    headers:{get:()=>options.header===undefined?'/admin/domain/customer-request/update?id=1234567':options.header},
    text:async()=>{if(options.hangBody)return new Promise(resolve=>{scope.finishBody=resolve});return options.body||''}};
  }};
 vm.createContext(scope);
 const start=code.indexOf('  const СОЗДАЮТСЯ ='),end=code.indexOf('  /* ЗАКРЕП ГОРОДА',start);
 assert.ok(start>=0&&end>start,'Use the exact current create implementation');
 vm.runInContext(code.slice(start,end)+';this.executeCreate=create;',scope);
 return {calls,scope,params,timers,run:()=>scope.executeCreate(structuredClone(params)),advance:ms=>{now+=ms},
  expire:()=>{for(const {fn}of [...timers.values()])fn()}};
}

test('CRM serializer sends only successful controls and explicit caller submitter',()=>{
 const els=[field('_csrf','synthetic'),field('flag','0','hidden'),
  {...field('flag','1','checkbox'),checked:true},field('reset','1','reset'),
  field('save','1','submit'),{...field('delete','1'),tagName:'BUTTON'},
  field('image','1','image'),field('action','1','button'),field('upload','fake-path','file'),
  {...field('inside_disabled_fieldset','secret'),matches:()=>true}];
 const body=CRM._внутр.serializeForm({elements:els});
 assert.deepEqual([...body],[['_csrf','synthetic'],['flag','0'],['flag','1']]);
 body.set('save_close','1');assert.equal(body.get('save_close'),'1');
});
test('ordinary same-origin create retains exact ID, one POST and readback',async()=>{
 const f=fixture(),result=await f.run();assert.equal(result.ok,true,JSON.stringify(result));assert.equal(result.id,1234567);
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);assert.equal(f.calls.filter(c=>c.kind==='readback').length,1);
 assert.equal(f.calls[0].body.get('save_close'),'1');
});
for(const status of [400,401,403,429,500,502,503,504])test('HTTP'+status+' cannot become successful from X-Redirect',async()=>{
 const f=fixture({status}),result=await f.run();assert.equal(result.ok,false);
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);assert.equal(f.calls.filter(c=>c.kind==='readback').length,0);
 assert.equal(result.unknown,true);
});
test('login URL numeric id is never a created CRM ID',async()=>{
 const f=fixture({header:'',url:CRM.BASES.mnc+'/login?id=7654321',body:'synthetic-login'}),r=await f.run();
 assert.equal(r.ok,false);assert.equal(r.id,undefined);assert.match(r.error,/Сессия/);
});
test('login body is rejected before a numeric card URL is accepted',async()=>{
 const f=fixture({header:'',url:CRM.BASES.mnc+'/admin/domain/customer-request/update?id=7654321',body:'synthetic-login'}),r=await f.run();
 assert.equal(r.ok,false);assert.equal(r.id,undefined);assert.match(r.error,/Сессия/);
});
for(const header of ['https://external.invalid/admin/domain/customer-request/update?id=1234567',
 '/admin/domain/customer/update?id=1234567','javascript:alert(1)'])test('untrusted redirect '+header+' is unknown, with no followup',async()=>{
 const f=fixture({header}),r=await f.run();assert.equal(r.ok,false);assert.equal(r.unknown,true);
 assert.equal(f.calls.filter(c=>c.kind==='readback').length,0);
});
test('index redirect without a confirmed request ID is unknown instead of a successful zero-ID creation',async()=>{
 const f=fixture({header:'/admin/domain/customer-request/index'}),r=await f.run();
 assert.equal(r.ok,false);assert.equal(r.unknown,true);assert.equal(r.id,undefined);
});
test('elapsed time never permits another POST while the original create is unresolved',async()=>{
 const f=fixture({hang:true});f.run();await new Promise(setImmediate);
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
 f.advance(10*60*1000+1);const second=await f.run();
 assert.equal(second.ok,false);assert.equal(second.refused,true);assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
});
for(const options of [
 {header:'/admin/domain/customer-request/update?id=1234567',body:'synthetic-login'},
 {header:'/admin/domain/customer-request/update?id=1234567',url:'https://foreign.invalid/admin/domain/customer-request/index'},
 {header:'',url:'https://foreign.invalid/admin/domain/customer-request/index'},
 {header:'',url:CRM.BASES.mnc+'/admin/domain/customer-request/index'},
 {url:CRM.BASES.mnc+'/admin/domain/customer-request/update?id=7654321'},
])test('inconsistent or unauthenticated creation response has no followup: '+JSON.stringify(options),async()=>{
 const f=fixture(options),r=await f.run();assert.equal(r.ok,false);assert.equal(r.unknown,true);
 assert.equal(f.calls.filter(c=>c.kind==='readback').length,0);
 const again=await f.run();assert.equal(again.ok,false);assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
});
test('ordinary final card URL without X-Redirect uses the same readback path',async()=>{
 const f=fixture({header:'',url:CRM.BASES.mnc+'/admin/domain/customer-request/update?id=1234567'}),r=await f.run();
 assert.equal(r.ok,true);assert.equal(r.id,1234567);assert.equal(f.calls.filter(c=>c.kind==='readback').length,1);
});
for(const hangBody of [false,true])test('creation observation expires without abort or repeated POST; late response cannot follow up: body='+hangBody,async()=>{
 const f=fixture({hang:!hangBody,hangBody}),pending=f.run();await new Promise(setImmediate);
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
 assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,120000);
 f.expire();const r=await pending;assert.equal(r.unknown,true);assert.equal(r.crm_create_dispatched,true);
 if(hangBody)f.scope.finishBody('');
 else f.scope.finishTransport({status:200,url:CRM.BASES.mnc+'/admin/domain/customer-request/create',headers:{get:()=>'/admin/domain/customer-request/update?id=1234567'},text:async()=>''});
 await new Promise(setImmediate);assert.equal(f.calls.filter(c=>c.kind==='readback').length,0);
 await f.run();assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
 assert.equal(f.timers.size,0);
});
test('headers and body share the original observation deadline',async()=>{
 const f=fixture({hang:true}),pending=f.run();await new Promise(setImmediate);
 f.advance(119000);f.scope.finishTransport({status:200,url:CRM.BASES.mnc+'/admin/domain/customer-request/create',headers:{get:()=>'/admin/domain/customer-request/update?id=1234567'},text:()=>new Promise(()=>{})});
 await new Promise(setImmediate);assert.equal([...f.timers.values()][0].ms,1000);
 f.expire();assert.equal((await pending).unknown,true);
});
for(const existing of [false,true])test('index redirect recovers only one fresh fully matching customer request: existing='+existing,async()=>{
 const f=fixture({recover:true,existing,header:'/admin/domain/customer-request/index',beforeIDs:[9000000],afterIDs:[9000000,1234567]});
 // A new customer has no historical requests; even a greater ID is never preferred.
 if(!existing)f.scope.findCustomerId=async()=>f.calls.some(c=>c.kind==='POST')?{id:'11',count:1}:{id:'',count:0};
 if(!existing){const original=f.scope.fetchDoc;f.scope.fetchDoc=async url=>url.includes('/customer/update')?{querySelector:()=>null,querySelectorAll:()=>linksForNew()}:original(url)}
 function linksForNew(){return[{getAttribute:()=>'/admin/domain/customer-request/update?id=1234567'}]}
 const r=await f.run();assert.equal(r.ok,true,JSON.stringify(r));assert.equal(r.id,1234567);
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);assert.equal(f.calls.filter(c=>c.kind==='readback').length,1);
});
for(const options of [
 {beforeIDs:[1234567],afterIDs:[1234567]},
 {beforeIDs:[],afterIDs:[1234567,7654321]},
 {beforeIDs:[],afterIDs:[1234567],unreadableHistory:true},
 {beforeIDs:[],afterIDs:[1234567],savedCustomer:'22'},
 {beforeIDs:[],afterIDs:[1234567],profileURL:CRM.BASES.mnc+'/login?id=11'},
 {beforeIDs:[],afterIDs:[1234567],savedURL:'https://foreign.invalid/admin/domain/customer-request/update?id=1234567'},
 ...['city_id','appliance_type_id','partner_id','type','comments','appliance_sub_type_id'].map(name=>({beforeIDs:[],afterIDs:[1234567],savedMismatch:'CustomerRequest['+name+']'})),
])test('index recovery refuses old, ambiguous, unreadable or mismatched candidate: '+JSON.stringify(options),async()=>{
 const f=fixture({existing:true,recover:true,header:'/admin/domain/customer-request/index',...options}),r=await f.run();
 assert.equal(r.ok,false,JSON.stringify(r));assert.equal(r.unknown,true);
 assert.equal(f.calls.filter(c=>c.kind==='readback').length,0);assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
});
for(const status of [200,400,422])test('proved creation form validation rejection permits one corrected attempt: status='+status,async()=>{
 const f=fixture({status,header:'',validationForm:true,errors:['synthetic required field']}),r=await f.run();
 assert.equal(r.crm_create_rejected,true);assert.equal(r.refused,true);assert.notEqual(r.unknown,true);
 await f.run();assert.equal(f.calls.filter(c=>c.kind==='POST').length,2);
});
test('a conflicting redirect cannot be erased by a non-success status and form errors',async()=>{
 const f=fixture({status:400,validationForm:true,errors:['synthetic required field']}),r=await f.run();
 assert.equal(r.unknown,true);assert.notEqual(r.crm_create_rejected,true);await f.run();
 assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
});
for(const read of [false,true])test('bounded followup retains the created ID and fences a late modifying step: read='+read,async()=>{
 const f=fixture({note:'synthetic note',omitPartnerField:true,hangFollowup:!read,hangFollowupRead:read});
 const pending=f.run();await new Promise(setImmediate);
 assert.equal(f.calls.filter(c=>c.kind==='followup_read').length,1);
 assert.equal(f.timers.size,1);f.expire();const r=await pending;
 assert.equal(r.unknown,true);assert.equal(r.id,1234567);
 if(read){f.advance(120001);f.scope.finishFollowupRead();await new Promise(setImmediate);assert.equal(f.calls.filter(c=>c.kind==='followup_POST').length,0)}
 await f.run();assert.equal(f.calls.filter(c=>c.kind==='POST').length,1);
});
