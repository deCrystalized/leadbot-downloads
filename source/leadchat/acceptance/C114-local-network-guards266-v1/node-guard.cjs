'use strict';
// Authored local tests only: a connection must belong to this test process
// or its live parent/child listener. Never permit working service ports.
const fs=require('node:fs'),path=require('node:path'),net=require('node:net'),dns=require('node:dns');
const root=process.env.CODEX_LOCAL_TEST_GUARD_ROOT,nonce=process.env.CODEX_LOCAL_TEST_GUARD_NONCE;
if(!root||!nonce)throw Error('Private local test guard configuration missing');
const loopback=h=>['127.0.0.1','::1','localhost','[::1]'].includes(String(h));
const log=value=>fs.appendFileSync(path.join(root,'transport.jsonl'),JSON.stringify({pid:process.pid,...value})+'\n',{mode:0o600});
function denied(kind){log({event:'denied',kind});throw Error('External or unowned transport denied by local test guard');}
function owned(port){
  for(const name of fs.readdirSync(root).filter(n=>n.endsWith('.listener.json'))){
    let item;try{item=JSON.parse(fs.readFileSync(path.join(root,name),'utf8'));}catch{continue;}
    if(item.nonce!==nonce||item.port!==Number(port)||!loopback(item.host))continue;
    if(item.pid!==process.pid&&item.pid!==process.ppid&&item.ppid!==process.pid)continue;
    try{process.kill(item.pid,0);return true;}catch{}
  }
  return false;
}
const connect=net.Socket.prototype.connect;
net.Socket.prototype.connect=function(...args){
  const a=Array.isArray(args[0])?args[0]:args;
  const options=typeof a[0]==='object'?a[0]:{port:a[0],host:typeof a[1]==='string'?a[1]:'localhost'};
  if(!options||!loopback(options.host||options.hostname||'localhost')||!owned(options.port))return denied('socket');
  log({event:'owned_connect',port:Number(options.port)});return connect.apply(this,args);
};
const listen=net.Server.prototype.listen;let counter=0;
net.Server.prototype.listen=function(...args){
  if(typeof args[0]==='object'){
    const value={...args[0]};
    if(Number(value.port)!==0||value.host&&!loopback(value.host))return denied('listen');
    value.host=value.host==='::1'?'::1':'127.0.0.1';args[0]=value;
  }else{
    if(Number(args[0])!==0||typeof args[1]==='string'&&!loopback(args[1]))return denied('listen');
    args=[0,typeof args[1]==='string'&&args[1]==='::1'?'::1':'127.0.0.1',...args.slice(typeof args[1]==='string'?2:1)];
  }
  let file;
  this.once('listening',()=>{
    const address=this.address();if(!address||!loopback(address.address))return denied('listen_address');
    file=path.join(root,process.pid+'-'+address.port+'-'+(++counter)+'.listener.json');
    fs.writeFileSync(file,JSON.stringify({nonce,pid:process.pid,ppid:process.ppid,host:address.address,port:address.port}),{flag:'wx',mode:0o600});
    log({event:'owned_listener',port:address.port});
  });
  this.once('close',()=>{if(file)try{fs.unlinkSync(file);}catch(e){if(e.code!=='ENOENT')throw e;}});
  return listen.apply(this,args);
};
const fetch=globalThis.fetch;
if(fetch)globalThis.fetch=function(input,...args){
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
  if(!loopback(url.hostname)||!owned(url.port||({http:80,https:443}[url.protocol.slice(0,-1)])))return denied('fetch');
  return fetch.call(this,input,...args);
};
for(const name of ['lookup','resolve','resolve4','resolve6','resolveAny','reverse']){
  const original=dns[name];
  if(original)dns[name]=function(host,...args){if(!loopback(host))return denied('dns');return original.call(this,host,...args);};
}
const dgram=require('node:dgram');
dgram.Socket.prototype.send=function(){return denied('udp');};
