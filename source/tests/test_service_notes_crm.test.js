'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),NOTES=require('../ext/request-notes');
const code=fs.readFileSync(require.resolve('../ext/crmact'),'utf8');
function fixture(){
 const values={'CustomerRequest[comments_service]':{value:'мс опоздал на 15 минут'},'CustomerRequest[comments]':{value:'Исходная работа'},'CustomerRequest[partner_comment]':{value:'C79.2'},'CustomerRequest[partner_id]':{value:'7'}};
 const s={NOTES,КОММ:{addComment:'CustomerRequest[comments]',addService:'CustomerRequest[comments_service]',addPartner:'CustomerRequest[partner_comment]'},String,Object,URLSearchParams,
  поле:(_f,k)=>values[k],значение:e=>e?.value||'',норм:x=>String(x||'').trim().toLowerCase().replace(/\s+/g,' ')};
 vm.createContext(s);const a=code.indexOf('  const естьСтрока ='),b=code.indexOf('  const предупредитьКомментарии =',a);
 vm.runInContext(code.slice(a,b)+';globalThis.check=комментарииНаМесте;globalThis.needed=нужныКомментарии;',s);return{s,values};
}
test('actual full-form writer promotes phone instruction and validates literal first-line placement',()=>{
 const f=fixture(),allowed=new Set(),ctx={warnings:[]};
 const written=f.s.комментарииВФорму(ctx,{}, {addService:'Звонить на 2-й номер, уточнить что было на заявке'},allowed);
 const expected='Звонить на 2-й номер\nуточнить что было на заявке\nмс опоздал на 15 минут';
 assert.equal(f.values['CustomerRequest[comments_service]'].value,expected);assert.equal(written.addService,expected);
 assert.equal(f.values['CustomerRequest[comments]'].value,'Исходная работа');assert.equal(f.values['CustomerRequest[partner_comment]'].value,'C79.2');
 const doc={querySelector:()=>({})};assert.equal(f.s.check(doc,written),true);
 f.values['CustomerRequest[comments_service]'].value=expected.replace(/\n/g,' ');assert.equal(f.s.check(doc,written),false);
});
test('an existing directive lower in the service field is corrected even when no new words are needed',()=>{
 const f=fixture(),form={},params={addService:'Звонить на 2-й номер'};
 f.values['CustomerRequest[comments_service]'].value='Другие примечания\nЗвонить на 2-й номер';
 assert.equal(f.s.needed(form,params),true);
 f.s.комментарииВФорму({warnings:[]},form,params,new Set());
 assert.equal(f.values['CustomerRequest[comments_service]'].value,'Звонить на 2-й номер\nДругие примечания');
 assert.equal(f.s.needed(form,params),false);
});
test('actual comments-only recipe preserves other fields and rejects flattened saved service text',async()=>{
 const f=fixture(),posted=[];
 const saved={comments:'Исходная работа',comments_service:'мс опоздал на 15 минут',partner_comment:'C79.2',date_changes:'Изначальный перенос'};
 const doc={querySelector:q=>({value:saved[q.replace('#customerrequest-','')]})};
 Object.assign(f.s,{csrf:()=>['_csrf','synthetic-csrf'],AJAX:{},запросФормы:(url,o)=>({url,...o}),
  записать:async(_c,r)=>{posted.push(r);return {}},
  послеЗаписи:async(_c,_w,goal)=>{
   assert.equal(goal({},doc),false);
   Object.assign(saved,Object.fromEntries(posted[0].body));assert.equal(goal({},doc),true);
   saved.comments_service=saved.comments_service.replace(/\n/g,' ');assert.equal(goal({},doc),false);return {ok:true};
  }});
 const a=code.indexOf('    comments(к, doc)'),b=code.indexOf('    /* «Не отвечает»',a);vm.runInContext('globalThis.recipe=({'+code.slice(a,b)+'}).comments;',f.s);
 const plan=f.s.recipe({params:{addService:'Звонить на 2-й номер'},url:'https://synthetic.invalid/save'},doc);
 const result=await plan.сделать();assert.equal(result.ok,true);assert.equal(posted.length,1);
 assert.equal(posted[0].body.get('comments_service'),'Звонить на 2-й номер\nмс опоздал на 15 минут');
 assert.equal(posted[0].body.get('comments'),'Исходная работа');assert.equal(posted[0].body.get('partner_comment'),'C79.2');assert.equal(posted[0].body.get('date_changes'),'Изначальный перенос');
});
