'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync(require.resolve('../ext/background'),'utf8');
function fixture(options={}){
 const calls=[],url='chrome-extension://synthetic/offscreen.html';let release;
 const chrome={offscreen:{createDocument:async args=>{calls.push(['create',args]);if(options.defer)await new Promise(resolve=>{release=resolve})}},runtime:{getURL:name=>'chrome-extension://synthetic/'+name,
  getContexts:async args=>{calls.push(['contexts',args]);if(options.error)throw Error('context observation failed');return Object.hasOwn(options,'contexts')?options.contexts:[]}}};
 if(options.native!==undefined)chrome.offscreen.hasDocument=async()=>{calls.push(['has']);if(options.native==='error')throw Error('native observation failed');return options.native};
 const scope={chrome};vm.createContext(scope);const start=code.indexOf('let creating = null;'),end=code.indexOf('// Offscreen поддерживает',start);
 assert.ok(start>=0&&end>start);vm.runInContext(code.slice(start,end)+';this.ensure=ensureOffscreen;',scope);
 return{scope,calls,url,release:()=>release()};
}
test('Chrome without hasDocument reuses only the exact existing offscreen context',async()=>{
 const f=fixture({contexts:[{contextType:'OFFSCREEN_DOCUMENT',documentUrl:'chrome-extension://synthetic/offscreen.html'}]});await f.scope.ensure();
 assert.equal(f.calls.filter(c=>c[0]==='create').length,0);
 assert.deepEqual(JSON.parse(JSON.stringify(f.calls[0][1])),{contextTypes:['OFFSCREEN_DOCUMENT'],documentUrls:[f.url]});
});
test('legacy context lookup and two concurrent callers create only one offscreen document',async()=>{
 const f=fixture({defer:true,contexts:[{contextType:'TAB',documentUrl:'chrome-extension://synthetic/offscreen.html'},{contextType:'OFFSCREEN_DOCUMENT',documentUrl:'chrome-extension://other/offscreen.html'}]});
 const first=f.scope.ensure(),second=f.scope.ensure();await new Promise(setImmediate);
 assert.equal(f.calls.filter(c=>c[0]==='create').length,1);f.release();await Promise.all([first,second]);
 assert.equal(f.calls.find(c=>c[0]==='create')[1].url,'offscreen.html');
});
test('failed context lookup cannot create a new document blindly',async()=>{
 const f=fixture({error:true});await assert.rejects(f.scope.ensure(),/context observation failed/);assert.equal(f.calls.filter(c=>c[0]==='create').length,0);
});
test('invalid context result cannot become a false empty list',async()=>{
 const f=fixture({contexts:{unknown:true}});await assert.rejects(f.scope.ensure(),/не подтвердил/);assert.equal(f.calls.filter(c=>c[0]==='create').length,0);
});
test('null context reply is unknown rather than permission to create',async()=>{
 const f=fixture({contexts:null});await assert.rejects(f.scope.ensure(),/не подтвердил/);assert.equal(f.calls.filter(c=>c[0]==='create').length,0);
});
test('available native hasDocument path retains the existing document',async()=>{
 const f=fixture({native:true});await f.scope.ensure();assert.deepEqual(f.calls,[['has']]);
});
test('native observation failure is not silently changed to another lookup',async()=>{
 const f=fixture({native:'error'});await assert.rejects(f.scope.ensure(),/native observation failed/);assert.deepEqual(f.calls,[['has']]);
});
test('offscreen setup failure before create dispatch is a proved no-write result',async()=>{
 let sends=0;const scope={мозг:async()=>({ok:true,rule:'jivo-2026-10-15-v1',lead:{phone:'9000000000'}}),
  ensureOffscreen:async()=>{throw Error('synthetic setup failed')},chrome:{runtime:{sendMessage:async()=>{sends++}}}};
 vm.createContext(scope);const start=code.indexOf('async function crm('),end=code.indexOf('/* ВЫБОР ИИ',start);
 assert.ok(start>=0&&end>start);vm.runInContext(code.slice(start,end)+';this.run=crm;',scope);
 const result=await scope.run('create',{lead:{phone:'9000000000'}});
 assert.equal(result.refused,true);assert.equal(result.crm_create_dispatched,false);assert.equal(sends,0);
 await assert.rejects(scope.run('prepare',{}),/synthetic setup failed/);
});
