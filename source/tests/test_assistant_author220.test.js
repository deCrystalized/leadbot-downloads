'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('author change retains the selected employee before stop and redraw reset the select value',async()=>{
 const source=fs.readFileSync(require.resolve('../ext/assistant-ui'),'utf8');
 const start=source.indexOf('async function changeAuthor('),end=source.indexOf('    function personalView(',start);
 assert.ok(start>0&&end>start);
 const selected={value:'new-author'},calls=[],state={activation:{},epoch:0};
 const context={state,runner:{stop:()=>calls.push('stop-runner')},workflow:{stop:()=>calls.push('stop-workflow')},
  observer:{reset:()=>{calls.push('reset-observer');selected.value='old-author'},refresh:async()=>calls.push('refresh')},
  personal:{selectAuthor:async id=>calls.push('author:'+id)}};
 vm.createContext(context);const handler=vm.runInContext('('+source.slice(start,end).trim()+')',context);
 await handler({target:selected,currentTarget:selected});
 assert.ok(calls.includes('author:new-author'));assert.ok(!calls.includes('author:old-author'));
 assert.equal(state.activation,null);assert.equal(state.epoch,1);
 assert.deepEqual(calls.slice(0,2),['stop-runner','stop-workflow']);
});
