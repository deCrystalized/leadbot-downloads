'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{create}=require('../ext/personal-tab');
function fixture(){
 const origins=['https://first.lead.test','https://second.lead.test'];
 const tabs=[{id:1,url:origins[0]+'/chats/customer',windowId:7}],calls=[];
 const api={tabs:{query:async()=>tabs,create:async args=>{
  const tab={id:Math.max(...tabs.map(t=>t.id))+1,windowId:7,...args};tabs.push(tab);calls.push(['create',tab.url]);return tab;
 },update:async(id,args)=>{calls.push(['update',id]);return tabs.find(t=>t.id===id)},remove:async id=>calls.push(['remove',id])},
 windows:{update:async()=>{},create:async args=>calls.push(['detach',args.tabId])}};
 return{ui:create(api,origins),tabs,calls,origins,sender:index=>({url:tabs[index].url,tab:{id:tabs[index].id}})};
}
test('opening from another allowed origin creates its own helper instead of focusing a different account domain',async()=>{
 const f=fixture();await f.ui.action('open',f.sender(0));
 f.tabs.push({id:3,url:f.origins[1]+'/chats/second-customer',windowId:7});
 await f.ui.action('open',f.sender(2));
 assert.deepEqual(f.calls.filter(c=>c[0]==='create').map(c=>c[1]),f.origins.map(o=>o+'/chats?lcz-assistant=1'));
});
test('navigation to another allowed origin cannot retain helper detach/close authority',async()=>{
 const f=fixture();await f.ui.action('open',f.sender(0));f.tabs[1].url=f.origins[1]+'/chats/second-customer';
 assert.equal(await f.ui.isDedicated(2,f.tabs[1].url),false);
 for(const action of ['close','detach'])await assert.rejects(f.ui.action(action,f.sender(1)));
 assert.equal(f.calls.some(c=>['close','detach','remove'].includes(c[0])),false);
});
test('an old helper at another origin is an occupied work tab',async()=>{
 const f=fixture();await f.ui.action('open',f.sender(0));f.tabs[1].url=f.origins[1]+'/chats/second-customer';
 assert.deepEqual((await f.ui.occupied(f.sender(0))).ids,['customer','second-customer']);
});
test('concurrent opens on distinct origins never share an in-flight helper creation',async()=>{
 const f=fixture();f.tabs.push({id:3,url:f.origins[1]+'/chats/other',windowId:7});
 await Promise.all([f.ui.action('open',f.sender(0)),f.ui.action('open',f.sender(1))]);
 assert.deepEqual(f.calls.filter(c=>c[0]==='create').map(c=>c[1]).sort(),f.origins.map(o=>o+'/chats?lcz-assistant=1').sort());
});
