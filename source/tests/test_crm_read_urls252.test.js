'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const CRM=require('../ext/crm');
function fixture(url){
 const sub={id:'sub',name:'subappl',attributes:[],getAttribute:key=>key==='data-krajee-depdrop'?'config-sub':null};
 const doc={querySelectorAll:()=>[{textContent:'config-sub '+JSON.stringify({url,depends:['appl']})}],
  querySelector:selector=>({content:selector.includes('csrf-param')?'_csrf':'synthetic-csrf-only'})};
 return{doc,sub};
}
function network(t){
 const calls=[];
 class Parser{parseFromString(){return{querySelector:()=>({querySelectorAll:()=>[],ownerDocument:{createElement:()=>({})},append:()=>{}})}}}
 t.mock.method(global,'fetch',async(url,init)=>{calls.push({url:String(url),init});return{ok:true,status:200,url:String(url),headers:{},text:async()=>'[]'}});
 const previous=Object.getOwnPropertyDescriptor(global,'DOMParser');
 Object.defineProperty(global,'DOMParser',{value:Parser,configurable:true,writable:true});
 t.after(()=>{if(previous)Object.defineProperty(global,'DOMParser',previous);else delete global.DOMParser});
 return calls;
}
test('DepDrop metadata cannot bypass read-only relative path validation',()=>{
 for(const url of ['https://external.invalid/types','//external.invalid/services','/admin/domain/customer-request/delete?id=1','/admin/logout?service=1']){
  const {doc,sub}=fixture(url);assert.deepEqual(CRM.кандидатыВидаУслуг(doc,sub),[],url);
 }
});
test('directory preparation never posts CSRF to an untrusted or modifying endpoint',async t=>{
 const calls=network(t),{doc,sub}=fixture('https://external.invalid/types');
 await CRM.subTypes(CRM.BASES.kp,'1','2',[],doc,sub,false);
 assert.equal(calls.some(c=>c.init?.method==='POST'),false);
 assert.ok(calls.every(c=>new URL(c.url).origin===CRM.BASES.kp));
});
test('a legitimate same-origin directory POST is still supported but cannot follow redirects',async t=>{
 const calls=network(t),{doc,sub}=fixture('/api/appliance/service-list');
 await CRM.subTypes(CRM.BASES.kp,'1','2',[],doc,sub,false);
 const post=calls.find(c=>c.init?.method==='POST');assert.ok(post);
 assert.equal(new URL(post.url).origin,CRM.BASES.kp);assert.equal(post.init.redirect,'error');
});
test('a hanging read-only directory POST is bounded and aborted like directory GET',async t=>{
 network(t);const originalFetch=global.fetch.bind(global),clock=global.setTimeout;
 const posts=[];
 t.mock.method(global,'setTimeout',(fn,ms,...args)=>clock(fn,ms===15000?1:ms,...args));
 t.mock.method(global,'fetch',(url,init)=>{
  if(init?.method!=='POST')return originalFetch(url,init);
  posts.push(init);
  return new Promise((resolve,reject)=>init.signal?.addEventListener('abort',()=>reject(Object.assign(Error('aborted'),{name:'AbortError'})),{once:true}));
 });
 const {doc,sub}=fixture('/api/appliance/service-list');
 let timer;const escaped=new Promise(resolve=>{timer=clock(()=>resolve('hung'),100)});
 const result=await Promise.race([CRM.subTypes(CRM.BASES.kp,'1','2',[],doc,sub,false),escaped]);
 clearTimeout(timer);
 assert.notEqual(result,'hung');assert.equal(posts.length,1);assert.equal(posts[0].signal.aborted,true);
});
