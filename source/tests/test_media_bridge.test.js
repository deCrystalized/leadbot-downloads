'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createAssistant}=require('../extension-server/brain/assistant');
test('image review reaches server with exact binding and authenticated owner, without a model call',async()=>{
  let sent;
  const b=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'test-service-token'},
    запрос:async(_url,options)=>{sent=JSON.parse(options.body);return {ok:true,json:async()=>({ok:true,auto_enabled:false})}},
    ai:{спросить:async()=>{throw Error('No model call allowed')}}});
  const args={action:'personal_media_review',owner:'spoofed',ctx:{convId:'synthetic'},message_id:'m3',media_signature:'exact-image',revision:'fresh',confirmed:true,activation_nonce:'reviewed-nonce',policy_ack:'current',client_version:'2.7.9',observations:{model:'Xiaomi PMDYJ02HT',content_kind:'device_label'}};
  const out=await b(args,'actual-owner','normal');
  assert.equal(out.ok,true);assert.equal(sent.owner,'actual-owner');assert.equal(sent.message_id,'m3');
  assert.equal(sent.media_signature,'exact-image');assert.equal(sent.revision,'fresh');assert.equal(sent.activation_nonce,'reviewed-nonce');
  assert.deepEqual(sent.observations,args.observations);assert.equal(sent.client_version,'2.7.9');
});
