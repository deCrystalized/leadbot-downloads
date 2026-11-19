'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{panelHarness}=require('./helpers/panel_harness236.cjs');
test('connection timestamp comes from confirmed I/O, not a redraw or queue scan',async t=>{
 const h=await panelHarness();t.after(()=>h.stop());
 const first=h.ui.personal.state.lastConfirmedAt;
 assert.ok(Number.isFinite(first));
 assert.ok(h.panel.textContent.includes('Последняя связь:'),h.panel.textContent);
 let now=first+5000;t.mock.method(Date,'now',()=>now);
 await h.ui.personal.scan();assert.equal(h.ui.personal.state.lastConfirmedAt,first);
 assert.ok(h.panel.textContent.includes('Подключён · авто выключено'));
 now+=10000;await h.ui.personal.heartbeat();assert.equal(h.ui.personal.state.lastConfirmedAt,now);
 assert.equal(h.ui.runner.state.mode,'stopped');assert.deepEqual(h.effects,[]);
 assert.ok(!h.calls.some(c=>['preview','personal_mode'].includes(c.action)));
 await h.ui.personal.stop();assert.equal(h.ui.personal.state.active,false);
 assert.ok(h.panel.textContent.includes('Авто выключено'));
});
