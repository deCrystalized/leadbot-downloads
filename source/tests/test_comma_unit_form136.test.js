'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const workflow=require('../ext/workflow');
const root=path.resolve(__dirname,'..');
function project(text){
 const code="import sys,json;sys.path.insert(0,'leadbot/brain');import contact_facts;print(json.dumps(contact_facts.collect([dict(id='source',direction='in',body=sys.argv[1])],dict(city='Саратов',direction='kp')),ensure_ascii=False))";
 const p=spawnSync('python3',['-B','-c',code,text],{cwd:root,encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);
 const facts=JSON.parse(p.stdout);
 const result=workflow.projectContactFacts({lead:{addr:{street:'Чужая',building:'1',office:'999',floor:'8'},addr_need:['кв'],comment:''},checks:[]},
  {ok:true,reviewed_policy:true,auto_enabled:false,facts,policy_version:'synthetic136'});
 return {facts,...result};
}
test('literal comma flat reaches the real form and replaces a guessed unit without an extra click',()=>{
 const {facts,lead,checks}=project('Шехурдина 8а, 91');
 assert.equal(facts.evidence['address.office'].quote,'Шехурдина 8а, 91');
 assert.equal(lead.addr.street,'Шехурдина');assert.equal(lead.addr.building,'8а');assert.equal(lead.addr.office,'91');
 assert.equal(lead.addr.floor,undefined);assert.deepEqual(lead.addr_need,[]);assert.equal(lead.addr_full,true);
 assert.equal(checks.find(x=>x.field==='address').ok,true);
});
test('numbered microdistrict preserves its house and comma flat through the shared form projection',()=>{
 const {lead}=project('11 микрорайон дом 8а, 91');
 assert.equal(lead.addr.street,'11 микрорайон');assert.equal(lead.addr.building,'8а');assert.equal(lead.addr.office,'91');
});
test('price or clock after the house never preserves a guessed flat in the form',()=>{
 for(const text of ['Шехурдина 8а, 1500 рублей','Шехурдина 8а, 13:00']){
  const {lead}=project(text);assert.equal(lead.addr.office,undefined);assert.ok(lead.addr_need.includes('кв'));
 }
});
test('an explicitly obsolete address clears a model worksite guess until the client supplies a current one',()=>{
 const {facts,lead,checks}=project('Прежний адрес был Шехурдина 8а, 91. Сейчас нужен ремонт по другому адресу.');
 assert.equal(facts.address_references[0].role,'previous');assert.equal(lead.addr.office,undefined);
 assert.equal(lead.addr.building,undefined);assert.equal(checks.find(x=>x.field==='address').ok,false);
 assert.match(lead.comment,/Прежний адрес/);
});
