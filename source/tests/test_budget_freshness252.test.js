'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {создатьБюджет}=require('../extension-server/brain/budget');
const {создать}=require('../extension-server/brain/index');
const {sha}=require('../extension-server/brain/tokens');
for(const path of ['state','usage'])test('expired '+path+' cache cannot grant model permission while storage is unavailable',async()=>{
 let at=Date.UTC(2026,9,30),fail=false;
 const b=создатьБюджет({env:{},now:()=>at,sleep:async()=>{},store:{
  get:async(key,def)=>{if(fail&&(path==='state'?key==='brain/state.json':key.startsWith('brain/usage/')))throw Error('synthetic read failure');return structuredClone(def)},put:async()=>{}}});
 assert.equal((await b.состояние()).mode,'normal');fail=true;at+=29000;assert.equal((await b.состояние()).mode,'normal');
 at+=2000;await assert.rejects(b.состояние(),/synthetic read failure/);
 at+=300000;await assert.rejects(b.состояние(),/synthetic read failure/);
 fail=false;assert.equal((await b.состояние()).mode,'normal');
});
test('the real handler returns unknown rules mode instead of using stale authorization to call a model',async()=>{
 let at=Date.UTC(2026,9,30),fail=false,models=0;
 const token='synthetic-budget-token-123456789';
 const objects=new Map([['brain/tokens.json',{tokens:[{id:'a',sha:sha(token)}]}]]);
 const brain=создать({env:{},now:()=>at,log:()=>{},sleep:async()=>{},
  store:{get:async(key,def)=>{if(fail&&key==='brain/state.json')throw Error('synthetic read failure');return structuredClone(objects.get(key)??def)},put:async(key,value)=>objects.set(key,structuredClone(value))},
  запрос:async()=>{models++;throw Error('Model must not be called')}});
 const request=op=>brain({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op,args:{task:'synthetic question'}})});
 assert.equal((await request('status')).statusCode,200);fail=true;at+=31000;
 const result=await request('ahk_chat');assert.equal(result.statusCode,402);
 const body=JSON.parse(result.body);assert.equal(body.budget.unknown,true);assert.equal(body.mode,'rules');assert.equal(models,0);
 fail=false;objects.set('brain/state.json',{mode:'rules',modeMonth:'2026-10'});
 const recovered=await request('ahk_chat');assert.equal(recovered.statusCode,402);assert.equal(models,0);
});
