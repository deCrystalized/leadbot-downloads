'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {spawnSync}=require('node:child_process'),workflow=require('../ext/workflow');
function facts(rows){
 const script="import sys,json;sys.path.insert(0,'leadbot/brain');import contact_facts;print(json.dumps(contact_facts.collect(json.load(sys.stdin)),ensure_ascii=False))";
 const r=spawnSync('python3',['-c',script],{cwd:path.resolve(__dirname,'..'),input:JSON.stringify(rows.map(([direction,body],i)=>({direction,body,id:String(i)}))),encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);
}
function project(f,lead){return workflow.projectContactFacts({lead,checks:[]},{ok:true,reviewed_policy:true,auto_enabled:false,facts:f,policy_version:'synthetic-context69'}).lead;}

test('a source-retracted entrance cannot remain in the legacy draft while another address conflict is unresolved',()=>{
 const f=facts([['in','Ленина 5, подъезд 3'],['in','Садовая 6'],['in','С подъездом могла ошибиться, там подъезд около Озона']]);
 assert.equal(f.address_needs_confirmation,true);assert.ok(f.uncertain_address_fields.length);
 const lead=project(f,{addr:{street:'Ленина',building:'5',entrance:'3'},addr_echo:'подъезд3'});
 assert.equal(lead.addr.entrance,undefined);assert.equal(lead.addr.building,'5');assert.equal(lead.addr_echo,'');
 assert.match(lead.comment,/Озона/);
});

test('a later explicit entrance survives initial form preparation',()=>{
 const f=facts([['in','Ленина 5, подъезд 3'],['in','С подъездом могла ошибиться'],['in','Подъезд 2, уточнила']]);
 const lead=project(f,{addr:{street:'Ленина',building:'5',entrance:'3'}});
 assert.equal(lead.addr.entrance,'2');
});

test('an unproven uncertainty entry does not erase an operator draft',()=>{
 const f={address:{},address_needs_confirmation:true,uncertain_address_fields:[{field:'entrance',verified:false}]};
 const lead=project(f,{addr:{street:'Ленина',building:'5',entrance:'3'}});
 assert.equal(lead.addr.entrance,'3');
});
