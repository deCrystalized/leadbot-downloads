'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {projectAcceptedVisit}=require('../ext/workflow');
const now=Date.parse('2026-10-21T09:00:03Z');
const window={source:'authorized_extension_reply',appointment_created:false,
  proposal_message_id:'p',answer_message_id:'a',operation_id:'op',proposal_quote:'Через час-полтора вам удобно будет?',
  answer_quote:'Да, ждём',earliest_at:Date.parse('2026-10-21T10:00:01Z')/1000,
  latest_at:Date.parse('2026-10-21T10:30:01Z')/1000,min_minutes:60,timezone:'Europe/Saratov'};
const reviewed={ok:true,auto_enabled:false,policy_version:'candidate137',accepted_visit:window};
test('accepted source window replaces a guessed clock and rounds inside its bound',()=>{
  const original={visit_date:'2026-10-22',visit_time:'20:00',visit_auto:{kind:'ближайшее'},phone:'unchanged'};
  const lead=projectAcceptedVisit(original,reviewed,now);
  assert.equal(lead.visit_date,'2026-10-21');assert.equal(lead.visit_time,'14:01');
  assert.equal(lead.visit_auto,null);assert.equal(lead.phone,'unchanged');
  assert.equal(lead.time_window.until,'14:30');assert.equal(original.visit_time,'20:00');
  assert.equal(lead.time_text,window.proposal_quote);assert.equal(lead.accepted_visit.answer_quote,'Да, ждём');
});
test('latest minute is not exceeded by rounding or a slow CRM preparation',()=>{
  const at=Date.parse('2026-10-21T09:30:02Z');
  assert.throws(()=>projectAcceptedVisit({},reviewed,at),/не успеваем/);
  const lead=projectAcceptedVisit({},reviewed,Date.parse('2026-10-21T09:29:59Z'));
  assert.equal(lead.visit_time,'14:30');
});
test('raw guessed approval, missing source or unknown timezone cannot become a visit',()=>{
  for(const change of [{source:'browser_receipt'},{appointment_created:true},{proposal_message_id:''},
      {answer_quote:''},{min_minutes:0},{latest_at:NaN},{timezone:'Invalid/Zone'}]){
    assert.throws(()=>projectAcceptedVisit({}, {...reviewed,accepted_visit:{...window,...change}},now));
  }
  assert.throws(()=>projectAcceptedVisit({}, {...reviewed,ok:false},now));
  assert.throws(()=>projectAcceptedVisit({}, {...reviewed,auto_enabled:true},now));
});
test('satellite timezone and two-hour minimum remain local and literal',()=>{
  const r={...reviewed,accepted_visit:{...window,timezone:'Europe/Moscow',min_minutes:120,
    earliest_at:Date.parse('2026-10-21T11:00:01Z')/1000,latest_at:Date.parse('2026-10-21T11:30:01Z')/1000}};
  const l=projectAcceptedVisit({},r,now);assert.equal(l.visit_time,'14:01');assert.equal(l.time_window.until,'14:30');
});
test('an absent verified acceptance leaves normal manual extraction untouched',()=>{
  const l={visit_time:'17:00'};assert.equal(projectAcceptedVisit(l,{ok:true},now),l);
});
