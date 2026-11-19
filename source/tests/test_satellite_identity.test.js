'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const territory=require('../ext/territory');
const cls={inMap:true,branch:'Симферополь',approval:false,zones:[],own:{}};
const ctx={city:'Евпатория',mainCity:'Симферополь',locality:'Евпатория'};
test('a broad parent map polygon keeps the actual satellite city and travel profile',()=>{
 const r=territory.decide('mnc',cls,ctx);
 assert.equal(r.branch,'Евпатория (Симферополь)');assert.equal(r.satelliteOf,'Симферополь');
 assert.equal(r.hours,'2–2,5');assert.equal(r.earliest,'11:00');assert.equal(r.far,false);assert.equal(r.approval,false);
 const agreed=territory.decide('mnc',{...cls,approval:true},ctx);assert.equal(agreed.approval,true);
 const main=territory.decide('mnc',cls,{...ctx,locality:'Симферополь'});
 assert.equal(main.branch,'Симферополь');assert.equal(main.satelliteOf,undefined);assert.equal(main.hours,'1–1,5');
});
test('a locality outside both cities never inherits an inside-city admission',()=>{
 const r=territory.decide('mnc',{...cls,inMap:false},{...ctx,locality:'Неизвестный посёлок'});
 assert.equal(r.approval,true);assert.notEqual(r.branch,'Евпатория (Симферополь)');
});
test('actual CRM picker retains the satellite option and never matches a parent just inside parentheses',()=>{
 const code=fs.readFileSync(require.resolve('../ext/crm'),'utf8');
 const start=code.indexOf('  const закрытый ='),end=code.indexOf('  const В_ЛАТ',start);
 const s={norm:x=>String(x||'').trim().toLowerCase(),начинаетсяСоСлова:(a,b)=>a===b||a.startsWith(b+' '),скелет:x=>x};
 vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.pick=pickCity;',s);
 const select={options:[{value:'synthetic-child',textContent:'Евпатория (Симферополь)'},{value:'synthetic-parent',textContent:'Симферополь'}]};
 for(const city of ['Евпатория','Евпатория (Симферополь)'])assert.equal(s.pick(select,city),'synthetic-child');
 assert.equal(s.pick(select,'Симферополь'),'synthetic-parent');
 assert.equal(s.pick({options:[select.options[0]]},'Симферополь'),'');
});
test('actual server territory result resolves bare city via current registry and fails closed on invalid relation',async()=>{
 const code=fs.readFileSync(require.resolve('../extension-server/brain/ops'),'utf8');
 const start=code.indexOf('  async function итогТерритории('),end=code.indexOf('  /* ---------- сервер команды',start);
 assert.ok(start>=0&&end>start);
 for(const fail of [false,true]){
  const calls=[];const s={LC_TERRITORY:{...territory,classify:()=>cls},deps:{policyGeo:async a=>{calls.push(a);if(fail)throw Error('offline');return {policy_version:'current',policy:{status:'known',physical_city:'Евпатория',main_branch:'Симферополь',acceptance_city:'Симферополь'}}}},геокод:()=>{throw Error('unexpected network')}};
  vm.createContext(s);vm.runInContext(code.slice(start,end)+';globalThis.run=итогТерритории;',s);
  const r=await s.run({city:'Евпатория',dir:'mnc'}, {},{pt:[33.36,45.20],locality:'Евпатория',text:'synthetic'},'',false,[33.36,45.20]);
  assert.equal(calls.length,1);assert.equal(calls[0].city,'Евпатория');
  if(fail){assert.equal(r.approval,true)}else{assert.equal(r.satelliteOf,'Симферополь');assert.equal(r.branch,'Евпатория (Симферополь)');assert.equal(r.acceptanceCity,'Симферополь');assert.equal(r.policyVersion,'current')}
 }
});
