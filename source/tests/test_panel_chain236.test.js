'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const{panelHarness}=require('./helpers/panel_harness236.cjs');
test('the actual panel distinguishes the finite API reservation from a cash balance',async t=>{
 const h=await panelHarness();t.after(()=>h.stop());await h.start();
 h.ui.personal.state.apiAllowance={limit:128,remaining:124,blocked:false};h.ui.draw();
 assert.match(h.panel.textContent,/124 из 128 вызовов/);assert.match(h.panel.textContent,/не остаток денег/);
 h.ui.personal.state.apiAllowance.blocked=true;h.ui.draw();assert.match(h.panel.textContent,/Допуск API остановлен/);
 h.ui.personal.state.auto=false;h.ui.draw();assert.ok(!h.panel.textContent.includes('124 из 128 вызовов'));
});
test('actual panel buttons reach API admission after claim, without paid or customer transport',async t=>{
 const h=await panelHarness();t.after(()=>h.stop());await h.start();
 assert.ok(h.calls.some(c=>c.action==='preview'&&c.wording==='neural_auto'),JSON.stringify({calls:h.calls,runner:h.ui.runner.state}));
 assert.equal(h.ui.runner.state.rows[0]?.research_state,'awaiting_admission');
 assert.deepEqual(h.effects,['claim']);assert.ok(h.panel.textContent.includes('Ожидается допуск контролируемой API-проверки'));
 assert.ok(h.panel.textContent.includes('Ответы пока не запущены'));
});
test('a later screening refresh cannot replace the real API-wait status with eligibility text',async t=>{
 const h=await panelHarness();t.after(()=>h.stop());await h.start();
 await h.ui.personal.scan();
 assert.ok(h.panel.textContent.includes('Ожидается допуск контролируемой API-проверки'),h.panel.textContent);
 assert.deepEqual(h.effects,['claim']);
});
