'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../ext/background'),'utf8');
function fixture(options={}){
 const disk=options.disk||{},calls=[];
 const scope={Set,Date,chrome:{storage:{local:{
  get:async key=>{calls.push('get');if(options.getError)throw Error('storage');return {[key]:structuredClone(disk[key])}},
  set:async data=>{calls.push('set');if(options.setError)throw Error('storage');if(!options.dropSet)Object.assign(disk,structuredClone(data))},
  remove:async key=>{calls.push('remove');if(options.removeError)throw Error('storage');delete disk[key]},
 }}}};
 vm.createContext(scope);const start=source.indexOf('const СОЗДАНИЯ_ИДУТ ='),end=source.indexOf('\nasync function crm(',start);
 assert.ok(start>=0&&end>start);vm.runInContext(source.slice(start,end)+';this.run=созданиеСЖурналом;',scope);
 const args={dir:'mnc',lead:{phone:'9000000000'}};
 return {disk,calls,scope,args,run:send=>scope.run(structuredClone(args),async()=>{calls.push('dispatch');return send()})};
}
test('durable reservation is persisted and read back before the one actual dispatch',async()=>{
 const f=fixture(),r=await f.run(async()=>({ok:true,id:1234567,crm_create_dispatched:true}));
 assert.equal(r.ok,true);assert.deepEqual(f.calls,['get','set','get','dispatch','remove']);assert.deepEqual(f.disk,{});
});
test('a concurrent activation does not share the first success or dispatch twice',async()=>{
 const f=fixture();let release;const first=f.run(()=>new Promise(resolve=>{release=resolve}));await new Promise(setImmediate);
 const second=await f.run(async()=>assert.fail('Second dispatch'));
 assert.equal(second.ok,false);assert.equal(second.unknown,true);
 release({ok:true,id:1234567,crm_create_dispatched:true});assert.equal((await first).ok,true);
 assert.equal(f.calls.filter(c=>c==='dispatch').length,1);
});
for(const result of [undefined,{ok:false,unknown:true,crm_create_dispatched:true},{ok:false,refused:true}])
 test('unknown or legacy unproved response survives a fresh worker: '+JSON.stringify(result),async()=>{
  const f=fixture();assert.equal((await f.run(async()=>result)).unknown,true);
  const next=fixture({disk:f.disk});const r=await next.run(async()=>assert.fail('Restart replay'));
  assert.equal(r.unknown,true);assert.equal(next.calls.includes('dispatch'),false);
 });
test('a lost sendMessage reply retains the original durable pending record',async()=>{
 const f=fixture(),r=await f.run(async()=>{throw Error('port closed')});
 assert.equal(r.unknown,true);assert.equal(Object.keys(f.disk).length,1);assert.equal(f.calls.includes('remove'),false);
});
for(const option of ['getError','setError','dropSet'])test(option+' prevents dispatch rather than silently using RAM',async()=>{
 const f=fixture({[option]:true}),r=await f.run(async()=>assert.fail('Storage bypass'));
 assert.equal(r.refused,true);assert.equal(f.calls.includes('dispatch'),false);
});
test('proved preflight refusal releases only its own reservation',async()=>{
 const f=fixture();f.disk.unrelated={keep:true};const r=await f.run(async()=>({ok:false,refused:true,crm_create_dispatched:false}));
 assert.equal(r.refused,true);assert.deepEqual(f.disk,{unrelated:{keep:true}});
});
test('failed journal cleanup preserves the confirmed ID and blocks another worker',async()=>{
 const f=fixture({removeError:true}),r=await f.run(async()=>({ok:true,id:1234567,crm_create_dispatched:true}));
 assert.equal(r.ok,true);assert.equal(r.id,1234567);assert.equal(r.warnings.length,1);
 assert.equal((await fixture({disk:f.disk}).run(async()=>assert.fail('Cleanup replay'))).unknown,true);
});
test('durable record contains no dialog text, credential or full customer form',async()=>{
 const f=fixture();f.args.lead.comment='synthetic private text';f.args.workflow_guard={sensitive:'not persisted'};
 await f.run(async()=>({ok:false,unknown:true}));
 const row=Object.values(f.disk)[0];assert.deepEqual(Object.keys(row).sort(),['at','dir','state','version']);
 assert.equal(JSON.stringify(row).includes('synthetic private'),false);
});
test('proved server validation rejection releases the attempt for a corrected form',async()=>{
 const f=fixture(),r=await f.run(async()=>({ok:false,refused:true,crm_create_dispatched:true,crm_create_rejected:true}));
 assert.equal(r.refused,true);assert.deepEqual(f.disk,{});
 assert.equal((await f.run(async()=>({ok:true,id:1234567,crm_create_dispatched:true}))).ok,true);
});
