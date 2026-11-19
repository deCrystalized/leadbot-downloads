'use strict';
const fs=require('fs'),cp=require('child_process'),crypto=require('crypto');
const pid=cp.execFileSync('systemctl',['show','-p','MainPID','--value','lc-brain'],{encoding:'utf8'}).trim();
const env=Object.fromEntries(fs.readFileSync('/proc/'+pid+'/environ','utf8').split('\0').filter(Boolean).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
if(!env.LEADBOT_PERSONAL_OWNER_ID||!env.LEADBOT_PERSONAL_OPERATOR_ID)throw Error('Missing personal binding');
const ownerToken='synthetic-personal-owner-entry-token',otherToken='synthetic-colleague-entry-token';
const memory=new Map([['brain/tokens.json',{tokens:[{id:env.LEADBOT_PERSONAL_OWNER_ID,sha:crypto.createHash('sha256').update(ownerToken).digest('hex'),label:'synthetic-owner'},
 {id:'synthetic-other-owner',sha:crypto.createHash('sha256').update(otherToken).digest('hex'),label:'synthetic-other'}]}]]);
const store={get:async(k,d)=>structuredClone(memory.has(k)?memory.get(k):d),put:async(k,v)=>memory.set(k,structuredClone(v))};
const compiled=require('/opt/lead-centre/brain/dist/index.js');
const handler=compiled.создать({env,store,log:()=>{},sleep:async()=>{}});
const event=(token,args)=>({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op:'assistant',args}),requestContext:{identity:{sourceIp:'127.0.0.1'}}});
(async()=>{
 const denied=await handler(event(otherToken,{action:'status',owner:env.LEADBOT_PERSONAL_OWNER_ID}));if(denied.statusCode!==403)throw Error('Owner gate failed');
 const valid=await handler(event(ownerToken,{action:'status'}));const b=JSON.parse(valid.body);
 if(valid.statusCode!==200||!b.ok||b.auto_enabled!==false||compiled.ВЕРСИЯ!=='2.3.0')throw Error('Compiled entry failed');
 const off=await handler(event(ownerToken,{action:'personal_authorize',operator_id:env.LEADBOT_PERSONAL_OPERATOR_ID,ctx:{convId:'synthetic-compiled-workflow'}}));if(off.statusCode!==403||JSON.parse(off.body).code!=='auto_disabled')throw Error('Workflow guard failed');
 const audit=await handler(event(ownerToken,{action:'personal_audit',operator_id:env.LEADBOT_PERSONAL_OPERATOR_ID,ctx:{convId:'synthetic-compiled-workflow'}}));if(audit.statusCode!==200||!JSON.parse(audit.body).events.length)throw Error('Audit route failed');
 console.log(JSON.stringify({workflow_guard_http:off.statusCode,audit_route:'passed',compiled_authenticated_entry:'passed',version:compiled.ВЕРСИЯ,policy_version:b.policy_version,other_token_http:denied.statusCode,auto_enabled:b.auto_enabled}));
})().catch(e=>{console.log(JSON.stringify({error:e.message}));process.exitCode=1});
