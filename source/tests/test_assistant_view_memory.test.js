'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const root={activeElement:null},body={scrollTop:220};let elements=[];
 const button=(key,disabled=false)=>({disabled,getAttribute:name=>name==='data-assistant-focus'?key:'',focus:()=>root.activeElement=elements.find(x=>x.key===key)||null,key});
 const detail=(key,text,open)=>({dataset:{assistantDisclosure:key},open,querySelector:()=>({textContent:text})});
 let details=[detail('audit-a','15:00 · Прочитал',true),detail('audit-b','15:00 · Прочитал',false),detail('queue','Очередь · подходят 2',false)];
 const view={dataset:{},contains:x=>elements.includes(x)||x===view,querySelectorAll:()=>details,querySelector:sel=>elements.find(x=>sel.includes('"'+x.key+'"')),
  focus:()=>root.activeElement=view,getAttribute:name=>name==='data-assistant-focus'?view.dataset.assistantFocus:null};
 const panel={getRootNode:()=>root,querySelector:sel=>sel==='.pb'?body:view};
 const source=fs.readFileSync(require.resolve('../ext/assistant-ui'),'utf8'),start=source.indexOf('  function captureAssistantView'),end=source.indexOf('  function create(',start),s={};
 vm.createContext(s);vm.runInContext(source.slice(start,end)+';globalThis.capture=captureAssistantView;globalThis.restore=restoreAssistantView;',s);
 elements=[button('row-one'),button('row-two')];root.activeElement=elements[1];
 return {s,root,body,panel,view,replace:()=>{elements=[button('row-one'),button('row-two')];details=[detail('audit-a','15:00 · Прочитал',false),detail('audit-b','15:00 · Прочитал',true),detail('queue','Очередь · подходят 3',true)];body.scrollTop=0;return{elements,details}},elements,button};
}
test('rerender preserves the actual second client, scroll and independently keyed details with identical labels',()=>{
 const f=fixture(),m=f.s.capture(f.panel),next=f.replace();f.s.restore(f.panel,m);
 assert.equal(f.root.activeElement,next.elements[1]);assert.equal(f.body.scrollTop,220);assert.deepEqual(next.details.map(x=>x.open),[true,false,false]);
});
test('background updates do not steal keyboard focus from outside the assistant',()=>{
 const f=fixture(),outside={key:'outside'};f.root.activeElement=outside;const m=f.s.capture(f.panel);f.replace();f.s.restore(f.panel,m);assert.equal(f.root.activeElement,outside);
});
test('a temporarily disabled action keeps its focus bookmark for the ready state',()=>{
 const f=fixture(),m=f.s.capture(f.panel);f.elements[1].disabled=true;f.s.restore(f.panel,m);assert.equal(f.root.activeElement,f.view);assert.equal(f.view.dataset.assistantLastFocus,'row-two');
 const pending=f.s.capture(f.panel),next=f.replace();f.s.restore(f.panel,pending);assert.equal(f.root.activeElement,next.elements[1]);
});
test('focus fallback cannot assign a reconciliation key to the entire assistant subtree',()=>{
 const f=fixture(),m=f.s.capture(f.panel);f.elements[1].disabled=true;f.s.restore(f.panel,m);
 assert.equal(f.view.getAttribute('data-assistant-focus'),undefined);
 assert.equal(f.s.capture(f.panel).focus,'row-two');
});
