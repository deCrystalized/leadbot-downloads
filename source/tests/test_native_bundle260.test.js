'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {собрать}=require('../extension-server/brain/build');

function compiled(t){
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'leadbot-compiled260-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const file=path.join(root,'brain.js');
  собрать(path.join(__dirname,'../ext'),file);
  return {root,index:require(file)};
}

test('actual freshly compiled native service stays off before directory or network access',async t=>{
  const f=compiled(t),directory=path.join(f.root,'must-not-be-created');let calls=0;
  const handler=f.index.создать({env:{LEADBOT_NATIVE_NOTIFICATIONS_DIR:directory},
    запрос:async()=>{calls++;throw Error('No transport authorized')}});
  const result=await handler.notifyNative({action:'send',payload:{}});
  assert.deepEqual(result,{ok:false,state:'disabled',telegram_confirmed:false});
  assert.equal(fs.existsSync(directory),false);assert.equal(calls,0);
});

test('compiled private native module prepares then records one fake post and restart cannot post twice',async t=>{
  const f=compiled(t),now=1000000,chat='-100123456789',topic=71;let sends=0;
  const directory=path.join(f.root,'private-journal'),ops=[];
  const payload={v:1,intent_id:crypto.randomUUID(),work_id:'a'.repeat(64),
    principal_id:crypto.randomUUID(),operator_id:crypto.randomUUID(),run_id:crypto.randomUUID(),
    generation:1,cid:crypto.randomUUID(),source_sha256:'b'.repeat(64),snapshot_hash:'c'.repeat(64),
    form_reference:'d'.repeat(64),card_sha256:'e'.repeat(64),crm_request_id:'1234567',
    direction:'mnc',source_code:'С76',dispatch_before:1090};
  const request=async(url,args)=>{
    const op=new URL(url).searchParams.get('op');ops.push(op);let value;
    if(op==='tg_chats')value={[chat]:{title:'Авито-Чаты',forum:true}};
    else if(op==='tg_topics')value={topics:[{id:topic,title:'Созданные с Авито'}]};
    else{
      assert.equal(op,'tg_send');sends++;
      assert.equal(fs.existsSync(path.join(directory,payload.work_id,'sending.json')),true);
      const body=JSON.parse(args.body);
      assert.equal(body.native_intent,payload.intent_id);assert.equal(body.conv,payload.cid);
      assert.equal(body.chat,chat);assert.equal(body.reply_to,topic);
      value={ok:true,message_id:779,native_intent:body.native_intent,chat_id:chat,
        reply_to:topic,text_sha256:crypto.createHash('sha256').update(body.text).digest('hex')};
    }
    return {ok:true,status:200,headers:{'content-type':'application/json'},
      text:async()=>JSON.stringify(value)};
  };
  const create=()=>f.index.создать({env:{TEAM_URL:'https://synthetic-team.invalid',
    BRAIN_TOKEN:'synthetic-compiled-test-token',LEADBOT_NATIVE_NOTIFICATIONS_ENABLED:'1',
    LEADBOT_NATIVE_NOTIFICATIONS_DIR:directory},now:()=>now,запрос:request});
  const handler=create(),prepared=await handler.notifyNative({action:'prepare',payload});
  assert.equal(prepared.prepared,true);assert.equal(sends,0);
  const result=await handler.notifyNative({action:'send',payload,send_before:1005});
  assert.equal(result.telegram_confirmed,true);assert.equal(result.crm_request_id,'1234567');
  assert.equal(result.message_id,779);assert.equal(result.topic_id,topic);
  const recovered=await create().notifyNative({action:'send',payload,send_before:1005});
  assert.deepEqual(recovered,result);assert.equal(sends,1);
  assert.deepEqual(ops,['tg_chats','tg_topics','tg_send']);
});
