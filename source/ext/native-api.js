/* Native controls/office: one authenticated HTTP attempt, strict original JSON.
   No request replay, provider access, credential journal, or server Run start
   occurs when constructing this transport. */
const LC_NATIVE_API=(()=>{
  const base='/bot-dialogs/assistant';
  const office=new Set(['heartbeat','poll','prepare','request-create','issue-create',
    'created','followup','card','failed','status']);
  // Chrome storage may return object keys in a different order. Array order
  // and every serialized value still belong to the original authorization.
  function sameRecord(left,right){
    const serialize=value=>JSON.stringify(value,(_key,entry)=>{
      if(!entry||typeof entry!=='object'||Array.isArray(entry))return entry;
      return Object.fromEntries(Object.keys(entry).sort().map(key=>[key,entry[key]]));
    });
    return serialize(left)===serialize(right);
  }
  function create(deps){
    if(!deps||['fetch','token','loggedOut'].some(k=>typeof deps[k]!=='function'))
      throw Error('Нужен штатный доступ LeadChat');
    const timeout=deps.timeout??15000,maxRequest=120000,maxResponse=2000000;
    if(!Number.isInteger(timeout)||timeout<1||timeout>30000)throw Error('Нужен конечный срок запроса');
    const fail=(code,status=0,started=false)=>Object.assign(
      Error('LeadChat не подтвердил исходный запрос. Повтор не отправлялся'),
      {code,status,request_started:started,native:true});
    function allowed(method,path){
      if(typeof path!=='string')return false;
      if(method==='GET')return path===base+'/native-run';
      if(method!=='POST')return false;
      return path===base+'/native-run/start'||path===base+'/native-run/stop'
        ||path.startsWith(base+'/native-office/')&&office.has(path.slice((base+'/native-office/').length));
    }
    function payload(value){
      const seen=new Set();
      function walk(v,depth){
        if(depth>24)throw fail('native_input',400);
        if(v===null||typeof v==='string'||typeof v==='boolean')return;
        if(typeof v==='number'){if(!Number.isFinite(v))throw fail('native_input',400);return}
        if(!v||typeof v!=='object'||seen.has(v))throw fail('native_input',400);
        if(!Array.isArray(v)&&Object.getPrototypeOf(v)!==Object.prototype
           &&Object.getPrototypeOf(v)!==null)throw fail('native_input',400);
        seen.add(v);
        if(Array.isArray(v)){for(let i=0;i<v.length;i++)walk(v[i],depth+1)}
        else for(const k of Object.keys(v))walk(v[k],depth+1);
        seen.delete(v);
      }
      walk(value,0);
      const body=JSON.stringify(value);
      if(new TextEncoder().encode(body).byteLength>maxRequest)throw fail('native_input',400);
      return body;
    }
    async function text(response){
      const length=response.headers?.get?.('content-length');
      if(length!==null&&length!==undefined&&(!/^\d+$/.test(length)||Number(length)>maxResponse))
        throw fail('native_response',response.status,true);
      if(!/application\/json(?:\s*;|$)/i.test(response.headers?.get?.('content-type')||''))
        throw fail('native_response',response.status,true);
      if(response.body?.getReader){
        const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});
        let size=0,out='';
        try{
          while(true){
            const next=await reader.read();if(next.done)break;
            size+=next.value.byteLength;
            if(size>maxResponse){await reader.cancel();throw fail('native_response',response.status,true)}
            out+=decoder.decode(next.value,{stream:true});
          }
          return out+decoder.decode();
        }finally{reader.releaseLock()}
      }
      const out=await response.text();
      if(new TextEncoder().encode(out).byteLength>maxResponse)throw fail('native_response',response.status,true);
      return out;
    }
    async function request(method,path,value){
      if(!allowed(method,path)||method==='GET'&&value!==undefined)throw fail('native_path',400);
      const body=method==='POST'?payload(value):undefined;
      if(deps.loggedOut())throw fail('native_logout',401);
      let token;
      try{token=await deps.token()}catch(_){throw fail('native_access')}
      if(typeof token!=='string'||!token||token.length>16384)throw fail('native_access');
      let timer,started=false;
      const ctl=new AbortController();
      try{
        return await Promise.race([
          (async()=>{
            started=true;
            const response=await deps.fetch('/api/v1'+path,{
              method,signal:ctl.signal,redirect:'error',credentials:'omit',
              headers:{Authorization:'Bearer '+token,...(body!==undefined?{'Content-Type':'application/json'}:{})},
              ...(body!==undefined?{body}:{}),
            });
            if(!response||!Number.isInteger(response.status)||!response.ok)
              throw fail('native_http',Number.isInteger(response?.status)?response.status:0,true);
            let result;
            try{result=JSON.parse(await text(response))}
            catch(e){if(e?.native)throw e;throw fail('native_response',response.status,true)}
            if(!result||typeof result!=='object'||Array.isArray(result))
              throw fail('native_response',response.status,true);
            return result;
          })(),
          new Promise((_,reject)=>{timer=setTimeout(()=>{
            ctl.abort();reject(fail('native_timeout',0,started));
          },timeout)}),
        ]);
      }catch(e){
        if(e?.native)throw e;
        throw fail('native_network',0,started);
      }finally{clearTimeout(timer);token=''}
    }
    return {get:path=>request('GET',path),post:(path,body)=>request('POST',path,body)};
  }
  return {create,sameRecord};
})();
if(typeof module!=='undefined')module.exports=LC_NATIVE_API;
