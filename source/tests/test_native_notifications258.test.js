'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {create,strictJSON}=require('../extension-server/brain/native-notifications');
const {создатьКоманду}=require('../extension-server/brain/team');
const {создатьСервер}=require('../extension-server/vps/brain_http');
const {создатьСеть}=require('../extension-server/brain/net');
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const KEY='synthetic-private-team-token-258',CHAT='-100123456789',TOPIC=71;
function payload(){return{v:1,intent_id:crypto.randomUUID(),work_id:'a'.repeat(64),
  principal_id:crypto.randomUUID(),operator_id:crypto.randomUUID(),run_id:crypto.randomUUID(),
  generation:1,cid:crypto.randomUUID(),source_sha256:'b'.repeat(64),snapshot_hash:'c'.repeat(64),
  form_reference:'d'.repeat(64),card_sha256:'e'.repeat(64),crm_request_id:'1234567',
  direction:'mnc',source_code:'С76',dispatch_before:1090};}
function fixture(t,options={}){
  const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'native-notice258-')));
  fs.chmodSync(directory,0o700);t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const f={directory,calls:[],sends:0,now:1000000,payload:payload()};
  const rawResponse=(body,status=200)=>({ok:status>=200&&status<300,status,
    headers:{'content-type':'application/json'},text:async()=>body});
  const request=async(url,args)=>{
      const op=new URL(url).searchParams.get('op');f.calls.push(op);
      const p=args.body?JSON.parse(args.body):null;
      if(op==='tg_chats')return rawResponse(JSON.stringify(options.chats||{[CHAT]:{title:'Авито-Чаты',forum:true}}));
      if(op==='tg_topics')return rawResponse(JSON.stringify({topics:options.topics||[{id:TOPIC,title:'Созданные с Авито'}]}));
      assert.equal(op,'tg_send');f.sends++;
      assert.ok(fs.existsSync(path.join(directory,f.payload.work_id,'sending.json')));
      assert.deepEqual(p,{chat:CHAT,reply_to:TOPIC,text:'1234567 - С76 МНЧ',conv:f.payload.cid,
        native_receipt:true,native_intent:f.payload.intent_id});
      if(options.lost)throw Error('Synthetic reply lost after possible send');
      if(options.onSend)await options.onSend(f);
      const result={ok:true,message_id:779,native_intent:p.native_intent,chat_id:p.chat,
        reply_to:p.reply_to,text_sha256:hash(p.text),...(options.result||{})};
      return rawResponse(options.raw??JSON.stringify(result),options.status??200);
    };
  f.request=request;
  const team=создатьКоманду({env:{TEAM_URL:'https://synthetic-team.invalid',BRAIN_TOKEN:KEY},
    user:'synthetic_native',запрос:request});
  f.create=()=>create({enabled:true,directory,team,now:()=>f.now});f.service=f.create();
  f.run=async(service=f.service,value=f.payload)=>{
    const planned=await service.prepare(value);if(planned.prepared!==true)return planned;
    return service.send(value,f.now/1000+5);
  };
  f.raw=()=>JSON.parse(fs.readFileSync(path.join(directory,f.payload.work_id,'send-raw.json'),'utf8'));
  return f;
}

test('native notification is explicitly disabled without directory/key/network access',async()=>{
  assert.deepEqual(await create({enabled:false}).send({}),{ok:false,state:'disabled',telegram_confirmed:false});
});
test('actual existing Team client uses one durable native service post and preserves original raw',async t=>{
  const f=fixture(t),result=await f.run();
  assert.equal(result.telegram_confirmed,true);assert.equal(result.message_id,779);
  assert.equal(result.crm_request_id,'1234567');assert.equal(result.chat_id,CHAT);assert.equal(result.topic_id,TOPIC);
  assert.deepEqual(f.calls,['tg_chats','tg_topics','tg_send']);
  assert.equal(result.original_http.sha256,f.raw().sha256);
  assert.equal(fs.statSync(path.join(f.directory,f.payload.work_id,'request.json')).mode&0o777,0o600);
  await f.run(f.create());assert.equal(f.sends,1);assert.equal(f.calls.length,3);
});
test('parallel same-work calls share the original one send',async t=>{
  let release;const paused=new Promise(r=>{release=r});
  const f=fixture(t,{onSend:()=>paused});const one=f.run(),two=f.run();
  await new Promise(setImmediate);release();const results=await Promise.all([one,two]);
  assert.ok(results.every(x=>x.telegram_confirmed));assert.equal(f.sends,1);
});
test('possible sent result lost on transport is unknown and restart cannot send again',async t=>{
  const f=fixture(t,{lost:true});assert.equal((await f.run()).state,'notification_unknown');
  assert.equal((await f.run(f.create())).state,'notification_unknown');assert.equal(f.sends,1);
});
for(const [name,result]of Object.entries({missing:{message_id:null},bool:{message_id:true},zero:{message_id:0},
  wrong_chat:{chat_id:'-100987654321'},wrong_topic:{reply_to:72},wrong_intent:{native_intent:crypto.randomUUID()},
  wrong_text:{text_sha256:'f'.repeat(64)},false_ok:{ok:false}})){
  test('native receipt '+name+' never confirms or repeats a possible post',async t=>{
    const f=fixture(t,{result});const result1=await f.run();
    assert.equal(result1.telegram_confirmed,false);assert.equal(f.sends,1);
    assert.ok(f.raw().body);await assert.rejects(f.run(f.create()));assert.equal(f.sends,1);
  });
}
for(const raw of ['not JSON','{"ok":true,"ok":false}','{"ok":NaN}','null','[]']){
  test('original malformed receipt is durably retained before parse: '+raw,async t=>{
    const f=fixture(t,{raw});assert.equal((await f.run()).state,'notification_unknown');
    assert.equal(Buffer.from(f.raw().body,'base64').toString(),raw);assert.equal(f.sends,1);
  });
}
test('non2xx success-shaped body cannot confirm a native message',async t=>{
  const f=fixture(t,{status:503});assert.equal((await f.run()).telegram_confirmed,false);
  assert.equal(f.raw().status,503);assert.equal(f.sends,1);
});
test('reflected credential is not persisted in original receipt or public error',async t=>{
  const f=fixture(t,{raw:JSON.stringify({ok:true,secret:KEY})}),result=await f.run();
  assert.equal(result.telegram_confirmed,false);assert.ok(!JSON.stringify(result).includes(KEY));
  assert.equal(fs.existsSync(path.join(f.directory,f.payload.work_id,'send-raw.json')),false);
});
test('same Work cannot mint another intent or change an expired original request',async t=>{
  const f=fixture(t);await f.run();
  await assert.rejects(f.run(f.create(),{...f.payload,intent_id:crypto.randomUUID()}));assert.equal(f.sends,1);
  f.now+=200000;assert.equal((await f.run(f.create())).telegram_confirmed,true);assert.equal(f.sends,1);
});
for(const options of [{chats:{}},{chats:{[CHAT]:{title:'Авито-Чаты',forum:true},'-100123456788':{title:'Авито-Чаты',forum:true}}},
  {topics:[]},{topics:[{id:1,title:'Созданные с Авито'},{id:2,title:'Созданные с Авито'}]}]){
  test('missing or ambiguous current native Telegram destination stops before send '+JSON.stringify(options),async t=>{
    const f=fixture(t,options);assert.equal((await f.run()).state,'notification_stopped');assert.equal(f.sends,0);
  });
}
test('new expired intent and caller text/target cannot reach Team',async t=>{
  const f=fixture(t);await assert.rejects(f.service.prepare({...f.payload,dispatch_before:999}));
  for(const extra of [{text:'arbitrary'},{chat_id:CHAT},{telegram_confirmed:true}])
    await assert.rejects(f.service.prepare({...f.payload,...extra}));
  assert.equal(f.calls.length,0);
});
test('strict private JSON never repairs duplicates/nonfinite/trailing input',()=>{
  for(const s of ['{"x":1,"x":2}','{"nested":{"x":1,"x":2}}','{"x":1e400}','{} trailing','{"x":true,}'])
    assert.throws(()=>strictJSON(s));
  assert.deepEqual(strictJSON('{"x":[1,true,null,{"s":"\\u0410"}]}'),{x:[1,true,null,{s:'А'}]});
});
test('destination preparation cannot send without a fresh short issue',async t=>{
  const f=fixture(t);assert.equal((await f.service.prepare(f.payload)).prepared,true);
  assert.equal(f.sends,0);assert.deepEqual(f.calls,['tg_chats','tg_topics']);
  for(const permit of [undefined,999,1006,Infinity,true])await assert.rejects(f.service.send(f.payload,permit));
  assert.equal(f.sends,0);assert.equal((await f.service.send(f.payload,1005)).telegram_confirmed,true);
});
test('unsafe symlink journal path cannot reach the broker',t=>{
  const f=fixture(t),link=f.directory+'-link';fs.symlinkSync(f.directory,link);t.after(()=>fs.unlinkSync(link));
  assert.throws(()=>create({enabled:true,directory:link,team:()=>{throw Error('No network')}}));
});
test('actual index private method prepares then sends through existing Team client exactly once',async t=>{
  const f=fixture(t),index=require('../extension-server/brain/index');
  const handler=index.создать({env:{TEAM_URL:'https://synthetic-team.invalid',BRAIN_TOKEN:KEY,
    LEADBOT_NATIVE_NOTIFICATIONS_ENABLED:'1',LEADBOT_NATIVE_NOTIFICATIONS_DIR:f.directory},
    now:()=>f.now,запрос:f.request});
  const prepared=await handler.notifyNative({action:'prepare',payload:f.payload});
  assert.equal(prepared.prepared,true);assert.equal(f.sends,0);
  assert.equal((await handler.notifyNative({action:'send',payload:f.payload,send_before:1005})).telegram_confirmed,true);
  assert.equal(f.sends,1);
  assert.equal((await handler.notifyNative({action:'send',payload:f.payload,send_before:1005})).telegram_confirmed,true);
  assert.equal(f.sends,1);
});
test('actual private HTTP route requires loopback service key and refuses duplicate JSON',async t=>{
  const previous=process.env.LEADBOT_SERVICE_TOKEN;process.env.LEADBOT_SERVICE_TOKEN='synthetic-loopback258';
  t.after(()=>{if(previous===undefined)delete process.env.LEADBOT_SERVICE_TOKEN;else process.env.LEADBOT_SERVICE_TOKEN=previous});
  let calls=0;const server=создатьСервер({handler:()=>{throw Error('No public route')},
    notifyNative:async args=>{calls++;return {ok:true,intent_id:args.intent_id}}});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
  const url='http://127.0.0.1:'+server.address().port+'/internal/leadbot/notification';
  assert.equal((await fetch(url,{method:'POST',body:'{}'})).status,403);
  const headers={'X-Leadbot-Token':'synthetic-loopback258'};
  assert.equal((await fetch(url,{method:'POST',headers:{...headers,Forwarded:'for=127.0.0.1'},body:'{}'})).status,403);
  assert.equal((await fetch(url,{method:'POST',headers,body:'{"x":1,"x":2}'})).status,502);
  const response=await fetch(url,{method:'POST',headers,body:JSON.stringify({intent_id:'synthetic'})});
  assert.equal(response.status,200);assert.equal(calls,1);
});
test('actual network keeps original invalid UTF8 bytes until native receipt fsync rejects parse',async t=>{
  const bytes=Buffer.from([123,34,120,34,58,34,255,34,125]);
  const server=require('node:http').createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');res.end(bytes);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(()=>{server.closeAllConnections();return new Promise(r=>server.close(r))});
  const team=создатьКоманду({env:{TEAM_URL:'http://127.0.0.1:'+server.address().port,BRAIN_TOKEN:KEY},
    запрос:создатьСеть()});let saved=null;
  await assert.rejects(team('tg_send',null,{text:'synthetic'},{parse:strictJSON,
    observeRaw:async(meta,raw)=>{assert.equal(meta.content_type,'application/json');saved=raw}}));
  assert.deepEqual(saved,bytes);
});
test('native authenticated Team requests cannot follow a redirect; ordinary network default is preserved',async t=>{
  let target=0;
  const server=require('node:http').createServer((req,res)=>{
    if(req.url.startsWith('/redirect')){res.statusCode=302;res.setHeader('Location','/target');res.end();return}
    target++;res.setHeader('Content-Type','application/json');res.end('{"ok":true}');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(()=>{server.closeAllConnections();return new Promise(r=>server.close(r))});
  const root='http://127.0.0.1:'+server.address().port,net=создатьСеть();
  const team=создатьКоманду({env:{TEAM_URL:root+'/redirect',BRAIN_TOKEN:KEY},запрос:net});
  await assert.rejects(team('tg_status',null,null,{observeRaw:async()=>assert.fail('No original final body')}));
  assert.equal(target,0);
  const ordinary=await net(root+'/redirect',{timeout:2000});assert.equal(ordinary.ok,true);assert.equal(target,1);
});
test('opt-in network response budget stops streamed oversized bytes without repeating the request',async t=>{
  let calls=0;
  const server=require('node:http').createServer((req,res)=>{calls++;res.setHeader('Content-Type','application/json');
    res.write(Buffer.alloc(80,32));res.end(Buffer.alloc(80,32));});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(()=>{server.closeAllConnections();return new Promise(r=>server.close(r))});
  await assert.rejects(создатьСеть()('http://127.0.0.1:'+server.address().port,{timeout:2000,maxResponseBytes:100}));
  assert.equal(calls,1);
});
