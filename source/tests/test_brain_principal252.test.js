'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {создать}=require('../extension-server/brain/index');
const {создатьТокены,sha}=require('../extension-server/brain/tokens');
test('an expired token cache cannot authorize after its refresh fails',async()=>{
 let at=100000,fail=false,revoked=0,reads=0;
 const token='synthetic-token-value-not-real';
 const store={get:async(key,def)=>{if(key==='brain/tokens.json'){reads++;if(fail)throw Error('synthetic store unavailable');return {tokens:[{id:'a',sha:sha(token),revoked}]}}return structuredClone(def)},put:async()=>{}};
 const tokens=создатьТокены({store,env:{},now:()=>at,sleep:async()=>{}});
 assert.equal((await tokens.проверить(token)).ok,true);const before=reads;
 fail=true;at+=29000;assert.equal((await tokens.проверить(token)).ok,true);assert.equal(reads,before);
 at+=2000;await assert.rejects(tokens.проверить(token),/хранилище|токен/);
 at+=300000;await assert.rejects(tokens.проверить(token),/хранилище|токен/);
 fail=false;revoked=at;assert.equal((await tokens.проверить(token)).ok,false);
});
test('concurrent authenticated team reads retain the principal of their own request',async()=>{
 const tokens={a:'synthetic-principal-A-123456789',b:'synthetic-principal-B-123456789'};
 const objects=new Map([['brain/tokens.json',{tokens:Object.entries(tokens).map(([id,token])=>({id,sha:crypto.createHash('sha256').update(token).digest('hex')}))}]]);
 let release,entered;const gate=new Promise(r=>release=r),ready=new Promise(r=>entered=r);let stateReads=0;
 const calls=[];
 const brain=создать({env:{TEAM_URL:'https://synthetic.invalid/team',BRAIN_TOKEN:'synthetic-server-token'},M:{},sleep:async()=>{},log:()=>{},
  store:{get:async(key,def)=>{if(key==='brain/state.json'&&++stateReads===1){entered();await gate}return structuredClone(objects.get(key)??def)},put:async(key,value)=>objects.set(key,structuredClone(value))},
  запрос:async(url,options)=>{const u=new URL(url);assert.equal(u.hostname,'synthetic.invalid');assert.equal(u.searchParams.get('op'),'links_get');calls.push({account:u.searchParams.get('account'),principal:options.headers['X-Team-User']});return {ok:true,status:200,text:async()=>'{}'}}});
 const request=id=>brain({httpMethod:'POST',headers:{'x-brain-auth':tokens[id]},body:JSON.stringify({op:'links_get',args:{account:id}})});
 const a=request('a');await ready;const b=await request('b');release();const result=await a;
 assert.equal(b.statusCode,200);assert.equal(result.statusCode,200);
 assert.deepEqual(calls.sort((x,y)=>x.account.localeCompare(y.account)),[{account:'a',principal:'brain-a'},{account:'b',principal:'brain-b'}]);
});
