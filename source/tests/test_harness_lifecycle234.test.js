'use strict';
// The integration driver must exercise the same live observer as the panel.
// All customer/model/CRM/Telegram transports remain the synthetic fixture.
const test=require('node:test'),assert=require('node:assert/strict');
const {harness}=require('./helpers/auto_harness232.cjs');

test('full-chain harness starts the real personal observer and renews only its live session',async t=>{
 const timers=[];
 t.mock.method(global,'setInterval',(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer});
 const cleared=[];t.mock.method(global,'clearInterval',timer=>cleared.push(timer));
 const h=await harness(t,['first']);
 assert.equal(timers.length,1,'A manual active=true skips the production observer');
 assert.equal(timers[0].ms,15000);
 assert.equal(h.personal.state.active,true);
 await timers[0].fn();
 assert.ok(h.wire.some(r=>r.action==='personal_heartbeat'));
 const session=await h.call('personal_status');
 assert.equal(session.active,true);assert.equal(session.auto_enabled,false);
 assert.deepEqual(h.effects,[]);
 await h.personal.stop();
 assert.ok(cleared.includes(timers[0]));
 assert.equal((await h.call('personal_status')).active,false);
});

test('the real harness observer cannot revive a session stopped on the server',async t=>{
 const timers=[];
 t.mock.method(global,'setInterval',(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer});
 t.mock.method(global,'clearInterval',()=>{});
 const h=await harness(t,['first']);
 assert.equal(timers.length,1);
 const current=await h.call('personal_status');
 await h.call('personal_stop',undefined,{connection_epoch:current.connection_epoch,control_seq:current.control_seq+1});
 const starts=h.wire.filter(r=>r.action==='personal_start').length;
 await timers[0].fn();
 assert.equal(h.personal.state.active,false);
 assert.equal(h.personal.state.error,'Личная сессия остановлена. Подключите её заново');
 assert.equal(h.wire.filter(r=>r.action==='personal_start').length,starts);
 assert.equal((await h.call('personal_status')).active,false);
 assert.deepEqual(h.effects,[]);
});
