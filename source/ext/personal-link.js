/* A scheduling backstop, never session/action authority. No credentials here. */
const LC_PERSONAL_LINK=(()=>{
  const KEY='lczPersonalLink',ALARM='lcz-personal-link',MAX=8;
  const token=value=>typeof value==='string'&&/^[a-zA-Z0-9-]{24,80}$/.test(value);
  function create(api,origins,isDedicated){
    let writing=Promise.resolve();const running=new Map();
    const quietClear=()=>Promise.resolve().then(()=>api.alarms.clear(ALARM)).catch(()=>{});
    const read=async()=>{
      const value=(await api.storage.session.get(KEY))[KEY];
      if(!value)return {};
      if(value.schema!==1||!value.rows||typeof value.rows!=='object'||Array.isArray(value.rows))throw Error('Не подтверждены настройки связи');
      const rows={};
      for(const[id,row]of Object.entries(value.rows)){
        if(!/^\d+$/.test(id)||!Number.isSafeInteger(Number(id))||!row||!token(row.connection_id)||!origins.includes(row.origin))throw Error('Не подтверждена вкладка связи');
        rows[id]={origin:row.origin,connection_id:row.connection_id};
      }
      if(Object.keys(rows).length>MAX)throw Error('Слишком много вкладок связи');
      return rows;
    };
    const update=fn=>{
      const job=writing.then(async()=>{const rows=await read();fn(rows);await api.storage.session.set({[KEY]:{schema:1,rows}});await alarm(rows);return rows});
      writing=job.catch(()=>{});return job;
    };
    async function alarm(rows){
      if(Object.keys(rows).length){
        if(!await api.alarms.get(ALARM))await api.alarms.create(ALARM,{periodInMinutes:0.5});
      }else await api.alarms.clear(ALARM);
    }
    async function senderTab(sender){
      if(sender?.id!==api.runtime.id||sender.frameId!==0||!Number.isSafeInteger(sender.tab?.id))throw Error('Откройте личного помощника');
      const url=new URL(sender.url);
      if(!origins.includes(url.origin)||!await isDedicated(sender.tab.id,url.href))throw Error('Связь доступна только во вкладке помощника');
      const tab=await api.tabs.get(sender.tab.id);
      if(tab.id!==sender.tab.id||new URL(tab.url).origin!==url.origin||!await isDedicated(tab.id,tab.url))throw Error('Вкладка помощника изменилась');
      return {id:tab.id,origin:url.origin};
    }
    async function remove(id,expected){
      await update(rows=>{if(rows[id]&&(!expected||rows[id].connection_id===expected))delete rows[id]});
    }
    async function action(kind,sender,id){
      if(!token(id))throw Error('Не подтверждена версия подключения');
      const tab=await senderTab(sender);
      if(kind==='start'){
        await update(rows=>{
          if(!rows[tab.id]&&Object.keys(rows).length>=MAX)throw Error('Слишком много вкладок связи');
          rows[tab.id]={origin:tab.origin,connection_id:id};
        });
      }else if(kind==='stop')await remove(tab.id,id);
      else throw Error('Неизвестная операция связи');
      return {ok:true,connection_id:id};
    }
    async function one(id,row,entry){
      const current=()=>!entry.cancelled&&Date.now()<entry.until;
      const tab=await api.tabs.get(Number(id));
      if(!current())return;
      if(new URL(tab.url).origin!==row.origin||!await isDedicated(tab.id,tab.url)){await remove(id,row.connection_id);return}
      // A stopped/replaced registration cannot dispatch a late pulse.
      if((await read())[id]?.connection_id!==row.connection_id||!current())return;
      const reply=await api.tabs.sendMessage(Number(id),{kind:'lcz-personal-pulse',connection_id:row.connection_id});
      if(current()){
        if(!reply?.ok||reply.active!==true||reply.connection_id!==row.connection_id)await remove(id,row.connection_id);
      }
    }
    async function tick(){
      const rows=await read();
      await Promise.all(Object.entries(rows).map(async([id,row])=>{
        if(running.has(id))return;
        const entry={cancelled:false,until:Date.now()+12000};running.set(id,entry);let timer;
        try{await Promise.race([one(id,row,entry),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Нет ответа вкладки связи')),12000)})])}
        catch(_e){entry.cancelled=true;await remove(id,row.connection_id)}
        finally{clearTimeout(timer);if(running.get(id)===entry)running.delete(id)}
      }));
      await restore();
    }
    async function restore(){
      const job=writing.then(async()=>{try{await alarm(await read())}catch(_e){await quietClear()}});
      writing=job.catch(()=>{});await job;
    }
    api.alarms.onAlarm.addListener(event=>{if(event.name===ALARM)tick().catch(quietClear)});
    api.tabs.onRemoved?.addListener(id=>{remove(id).catch(quietClear)});
    return {action,tick,restore};
  }
  return {create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_PERSONAL_LINK;
