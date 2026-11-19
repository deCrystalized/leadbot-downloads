'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(call=async()=>({chain_valid:true,events:[]})){
 const source=fs.readFileSync(require.resolve('../ext/assistant-ui'),'utf8');
 const start=source.indexOf('    function researchAuditView'),end=source.indexOf('    function auditView',start);
 const state={epoch:1,result:{research_job_id:'job',request_id:'rid',revision:'rev'}};
 const researchAudit={job:'job',rows:[],busy:false,error:''};
 const scope={state,researchAudit,call,draw:()=>{},button:(label,fn,disabled)=>({label,fn,disabled}),
  h:(tag,props,...children)=>({tag,props,children}),Date,JSON};
 vm.createContext(scope);vm.runInContext(source.slice(start,end)+';globalThis.view=researchAuditView;globalThis.load=loadResearchAudit;',scope);
 return scope;
}
test('owner journal shows sourced model assertion as text and preserves source data for inspection',()=>{
 const f=fixture();f.researchAudit.rows=[{sequence:1,at:1000,event:'decision_basis',detail:{summary:'<script>not executable</script>',basis:['current:message'],source:'model_assertion_unverified'}}];
 const tree=f.view(),text=JSON.stringify(tree);
 assert.match(text,/утверждение модели/);assert.match(text,/current:message/);assert.match(text,/<script>not executable<\/script>/);
 assert.equal(tree.tag,'details');assert.equal(tree.props['data-assistant-disclosure'],'research-audit-job');
});
test('late audit response from previous dialogue cannot populate another selected job',async()=>{
 let release;const waiting=new Promise(resolve=>{release=resolve});const f=fixture(async()=>waiting);
 const work=f.load();f.state.epoch++;f.state.result={research_job_id:'different'};
 release({chain_valid:true,events:[{sequence:1,event:'old-private-source'}]});await work;
 assert.equal(f.researchAudit.rows.length,0);assert.equal(f.researchAudit.busy,false);
});
test('an invalid audit chain is displayed as an error without claiming verified data',async()=>{
 const f=fixture(async()=>({chain_valid:false,events:[{event:'tampered'}]}));await f.load();
 assert.match(f.researchAudit.error,/не подтверждён/);assert.equal(f.researchAudit.rows.length,0);
});
