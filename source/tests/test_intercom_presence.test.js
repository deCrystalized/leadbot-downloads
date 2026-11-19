'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const workflow=require('../ext/workflow'),crm=require('../ext/crm'),helpers=crm._внутр;
const code=fs.readFileSync(require.resolve('../ext/crm'),'utf8'),content=fs.readFileSync(require.resolve('../ext/content'),'utf8'),FIELD=helpers.ДОМОФОН;
function form(value='yes-id',options=[{value:'yes-id',text:'Да'},{value:'no-id',text:'Нет'}]){
 const elements=['locality','street','building','office','entrance','floor'].map(k=>({name:'Customer[address_'+k+']',tagName:'INPUT',type:'text',value:''}));
 const el={name:FIELD,tagName:'SELECT',value,options};elements.push(el);for(const e of elements)elements[e.name]=e;
 return {elements,getAttribute:()=>''};
}
test('source evidence projects known presence and discards an unsupported model guess',()=>{
 for(const value of [true,false,null]){
  const facts={intercom_present:value,evidence:value===null?{}:{intercom_present:{message_id:'client'}}};
  const out=workflow.projectContactFacts({lead:{addr:{intercom:true,has_intercom:true}}},{ok:true,reviewed_policy:true,auto_enabled:false,facts});
  assert.equal(out.lead.addr.has_intercom,value);if(value!==true)assert.equal(out.lead.addr.intercom,false);
 }
 const out=workflow.projectContactFacts({lead:{addr:{intercom:true,has_intercom:true}}},{ok:true,reviewed_policy:true,auto_enabled:false,facts:{intercom_present:false}});
 assert.equal(out.lead.addr.has_intercom,null);
});
test('actual form reading preserves unknown, explicit negative and operator changes',()=>{
 const a=content.indexOf('  function readForm()'),b=content.indexOf('\n  /*',a);assert.ok(a>=0&&b>a);
 for(const [prior,checked,indeterminate,want] of [[null,false,true,null],[false,false,false,false],[true,false,false,false],[false,true,false,true]]){
  const input={type:'checkbox',checked,indeterminate};
  const s={S:{lead:{addr:{has_intercom:prior}},prep:{}},LC_WORKFLOW:workflow,LC_EXTRACT:{advertiserComment:(_l,c)=>c},panel:{querySelector:q=>q.includes('"intercom"')?input:null}};
  vm.createContext(s);vm.runInContext(content.slice(a,b)+';globalThis.read=readForm;',s);assert.equal(s.read().lead.addr.has_intercom,want);
 }
 assert.equal(workflow.readIntercomField({has_intercom:false},null).has_intercom,false);
 assert.equal(workflow.readIntercomField({}, {checked:false,indeterminate:false}).has_intercom,undefined);
});
test('a known negative clears old yes using the actual No option value; unknown leaves it alone',()=>{
 const f=form();const plan=helpers.планКлиента(f,{has_intercom:false},[]);
 assert.equal(plan.ставим[FIELD],'no-id');assert.ok(plan.changed.includes('домофон'));
 assert.equal(Object.keys(helpers.планКлиента(f,{has_intercom:null,intercom:false},[]).ставим).length,0);
 assert.equal(Object.keys(helpers.планКлиента(f,{intercom:false},[]).ставим).length,0);
 assert.match(helpers.планКлиента(form('yes-id',[{value:'yes-id',text:'Да'}]),{has_intercom:false},[]).error,/Нет/);
 assert.equal(helpers.несохранено(f,{[FIELD]:'no-id'})[0],'домофон');
 f.elements[FIELD].value='no-id';assert.equal(helpers.несохранено(f,{[FIELD]:'no-id'}).length,0);
 assert.equal(Object.keys(helpers.планКлиента(f,{has_intercom:false},[]).ставим).length,0);
});
test('new customer serialization records No and refuses a form without a supported negative',()=>{
 const a=code.indexOf('    // адрес — по своим полям карточки'),b=code.indexOf('    // дата и время визита',a);
 for(const supported of [true,false]){
  const f=form('yes-id',supported?undefined:[{value:'yes-id',text:'Да'}]);
  const s={lead:{addr:{has_intercom:false}},cust:{},form:f,warnings:[],setVal:helpers.setVal,intercomChoice:helpers.intercomChoice,ДОМОФОН:FIELD};
  vm.createContext(s);vm.runInContext('globalThis.run=()=>{'+code.slice(a,b)+'};',s);const out=s.run();
  if(supported)assert.equal(helpers.serializeForm(f).get(FIELD),'no-id');else {assert.equal(out.refused,true);assert.equal(f.elements[FIELD].value,'yes-id');}
 }
});
test('profile update performs one mocked POST and verifies No; a stale Yes is an error',async()=>{
 const a=code.indexOf('  async function обновитьКлиента('),b=code.indexOf('  /* АДРЕС КЛИЕНТА ПО ЗАЯВКЕ',a);assert.ok(a>=0&&b>a);
 for(const saves of [true,false]){
  let reads=0,posts=0,submitted;
  const s={...helpers,URL,URL_КЛИЕНТА:(base,id)=>base+'/customer/'+id,формаКлиента:d=>d,тел10:x=>String(x).replace(/\D/g,'').slice(-10),маскаТел:x=>x,БЕЗ_ОТВЕТА:new Map(),записьБезОтвета:()=>null,суть:e=>e.message,
   fetchDoc:async()=>form(++reads===1?'yes-id':saves?'no-id':'yes-id'),
   записьКлиента:async(_url,body)=>{posts++;submitted=new URLSearchParams(body);return {status:200,ok:true,headers:{get:()=>''},url:'https://synthetic.invalid/customer/1',text:async()=>''}},formErrors:()=>[],DOMParser:class {parseFromString(){return {querySelector:()=>null}}}};
  vm.createContext(s);vm.runInContext(code.slice(a,b)+';globalThis.update=обновитьКлиента;',s);
  const out=await s.update('https://synthetic.invalid','1',{addr:{has_intercom:false}});
  assert.equal(posts,1);assert.equal(submitted.get(FIELD),'no-id');assert.equal(out.ok,saves);if(!saves)assert.match(out.error,/не сохранила.*домофон/);
 }
});
test('post-create verification reads actual customer profile even if embedded request field says No',async()=>{
 const a=code.indexOf('  async function verifyCreated('),b=code.indexOf('  /* СОЗДАНИЕ —',a);assert.ok(a>=0&&b>a);
 for(const profile of ['no-id','yes-id',null]){
  const calls=[],request=form('no-id');
  const s={ДОМОФОН:FIELD,intercomElement:f=>f.elements[FIELD],intercomValue:helpers.intercomValue,полеФормы:(f,n)=>f.elements[n],полеВидаУслуг:()=>null,АДРЕС_КЛИЕНТА:{},одно:()=>false,цифры:x=>String(x).replace(/\D/g,''),суть:e=>e.message,клиентЗаявкиИз:()=> '1',URL_КЛИЕНТА:()=> 'https://synthetic.invalid/customer/1',формаКлиента:d=>d,
   fetchDoc:async url=>{calls.push(url);return url.includes('customer-request')?{querySelector:()=>request}:profile===null?null:form(profile)}};
  vm.createContext(s);vm.runInContext(code.slice(a,b)+';globalThis.verify=verifyCreated;',s);
  const out=await s.verify('https://synthetic.invalid','2',new URLSearchParams({_intercom_presence_expected:'0'}));
  assert.equal(calls.length,2);assert.equal(out.fields.includes('домофон'),profile==='no-id');assert.equal(out.diffs.length===0,profile==='no-id');
 }
});
test('actual create path sends known No once and adds verification-only marker after mocked transport',async()=>{
 const a=code.indexOf('  async function создатьЗаявку('),b=code.indexOf('  // адрес и комментарий в карточке',a);
 const end=b>a?b:code.indexOf('\n  async function ',a+10);assert.ok(a>=0&&end>a);
 for(const existing of [false,true]){
  const f=form('yes-id');for(const name of ['Customer[phone]','Customer[first_name]','CustomerRequest[city_id]','CustomerRequest[comments]','CustomerRequest[customer_id]']){
   const el={name,tagName:'INPUT',type:'text',value:''};f.elements.push(el);f.elements[name]=el;
  }
  let posts=0,updates=0,verified=0,submitted;
  const s={...helpers,URL,URLSearchParams,BASES:{mnc:'https://synthetic.invalid'},CREATE:'/admin/domain/customer-request/create',ИМЯ:{mnc:'МНЧ'},
   DOMParser:class {parseFromString(){return {querySelector:()=>null,querySelectorAll:()=>[]}}},
   customerRequestIds:async()=>[],
   заранее:p=>()=>p,searchAllBases:async()=>({found:[],unchecked:[]}),findCustomerId:async()=>existing?{id:'11'}:{},customerStatuses:async()=>[],
   ЖИВЫЕ:/active/,МОДЕРАЦИЯ:/moderation/,fetchDoc:async()=>({querySelector:()=>f}),pickOption:()=>'',pickNumber:()=>'',полеВидаУслуг:()=>null,
   fetch:async(url,o)=>{assert.equal(url,'https://synthetic.invalid/admin/domain/customer-request/create'+(existing?'?customer_id=11':''));posts++;submitted=new URLSearchParams(o.body);return {status:302,text:async()=>'',headers:{get:n=>n==='X-Redirect'?'/admin/domain/customer-request/update?id=999':''}}},
   обновитьКлиента:async(_base,id,o)=>{updates++;assert.equal(id,'11');assert.equal(o.addr.has_intercom,false);return {ok:true,changed:['домофон'],warnings:[]}},
   verifyCreated:async(_base,id,body)=>{verified++;assert.equal(id,999);assert.equal(body.get('_intercom_presence_expected'),'0');return {fields:['домофон'],diffs:[]}},
   АДРЕС_НЕ_ТОТ:'',суть:e=>e.message};
  vm.createContext(s);vm.runInContext(code.slice(a,end)+';globalThis.run=создатьЗаявку;',s);
  const out=await s.run({dir:'mnc',lead:{phone:'9001112233',name:'Иван',addr:{has_intercom:false},comment:'Сборка'},sel:{cityId:'1'}},{отправлено:false});
  assert.equal(out.ok,true);assert.equal(posts,1);assert.equal(updates,existing?1:0);assert.equal(verified,1);
  assert.equal(submitted.get(FIELD),'no-id');assert.equal(submitted.has('_intercom_presence_expected'),false);
 }
});
