'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {spawnSync}=require('node:child_process'),workflow=require('../ext/workflow');
function facts(rows){
 const script="import sys,json;sys.path.insert(0,'leadbot/brain');import contact_facts;print(json.dumps(contact_facts.collect(json.load(sys.stdin)),ensure_ascii=False))";
 const r=spawnSync('python3',['-c',script],{cwd:path.resolve(__dirname,'..'),input:JSON.stringify(rows.map(([direction,body],i)=>({direction,body,id:String(i)}))),encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);
}
function project(f,lead){return workflow.projectContactFacts({lead,checks:[]},{ok:true,reviewed_policy:true,auto_enabled:false,facts:f,policy_version:'synthetic-graphics71'});}
const symptom='Подарили рабочую видеокарту, нет картинки, экран чёрный';

test('source-confirmed PC diagnostics corrects a guessed card topic and keeps the literal problem',()=>{
 const f=facts([['in',symptom],['out','Видеокарта вставлена в ПК?'],['in','Да конечно']]);
 const result=project(f,{device:'Видеокарта GTX 1650',topics:['видеокарта','полка'],problem:symptom,addr:{}});
 assert.equal(result.lead.device,'компьютер');assert.deepEqual(result.lead.topics,['компьютер','полка']);
 assert.equal(result.lead.problem,symptom);assert.equal(result.contact_facts.graphics_scope.component_fault_confirmed,false);
 const empty=project(f,{device:'',topics:[],addr:{}}).lead;
 assert.equal(empty.device,'компьютер');assert.deepEqual(empty.topics,['компьютер']);
});

test('an uncertain host and an explicit card repair never rewrite the draft as PC diagnostics',()=>{
 for(const rows of [[['in',symptom]],[['in','Нужен ремонт видеокарты, пайка. В ПК нет изображения']]]){
  const lead=project(facts(rows),{device:'Видеокарта',topics:['видеокарта'],problem:'Слова клиента',addr:{}}).lead;
  assert.equal(lead.device,'Видеокарта');assert.deepEqual(lead.topics,['видеокарта']);
 }
});

test('a model-only or incomplete host assertion cannot change the work item',()=>{
 const scope={kind:'host_diagnostic',component_fault_confirmed:false,source:'client_message',message_id:'a',quote:'Видеокарта в ПК'};
 for(const graphics_scope of [{...scope,source:'model'},{...scope,message_id:''},{...scope,quote:''},{...scope,component_fault_confirmed:true}]){
  const lead=project({address:{},graphics_scope},{device:'Видеокарта',topics:['видеокарта'],addr:{}}).lead;
  assert.equal(lead.device,'Видеокарта');assert.deepEqual(lead.topics,['видеокарта']);
 }
});

test('a separately selected TV and other topics are not collapsed into the graphics complaint',()=>{
 const f=facts([['in',symptom],['out','Видеокарта установлена в компьютере?'],['in','Да']]);
 const result=project(f,{device:'телевизор',topics:['телевизор','видеокарта'],addr:{}}),lead=result.lead;
 assert.equal(lead.device,'телевизор');assert.deepEqual(lead.topics,['телевизор','компьютер']);
 assert.ok(!result.checks.some(c=>c.field==='device'&&c.ok));
});
