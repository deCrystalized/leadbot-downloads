/* One assistant tab per LeadChat origin. Never navigate the sending work tab. */
const LC_PERSONAL_TAB=(()=>{
  function create(api,allowedOrigins) {
    const opening=new Map();let writing=Promise.resolve();
    const memory={};
    const read=async()=>api.storage?.session?(await api.storage.session.get('lczPersonalTabs')).lczPersonalTabs||{}:{...memory};
    const update=fn=>{const job=writing.then(async()=>{const rows=await read();fn(rows);if(api.storage?.session)await api.storage.session.set({lczPersonalTabs:rows});else{for(const key of Object.keys(memory))delete memory[key];Object.assign(memory,rows)}});writing=job.catch(()=>{});return job};
    const register=(id,origin)=>update(rows=>{rows[id]=origin});
    api.tabs.onRemoved?.addListener(id=>{update(rows=>{delete rows[id]}).catch(()=>{})});
    const originOf=sender=>{const u=new URL(sender?.url||'');if(!allowedOrigins.includes(u.origin)||!Number.isInteger(sender?.tab?.id))throw Error('Откройте помощника из LeadChat');return u};
    const dedicated=(tab,origin)=>{try{const u=new URL(tab.url);return u.origin===origin&&u.searchParams.get('lcz-assistant')==='1'}catch(_e){return false}};
    async function isDedicated(id,url){try{const u=new URL(url);return allowedOrigins.includes(u.origin)&&(await read())[id]===u.origin}catch(_e){return false}}
    async function surface(sender){const u=originOf(sender);if(u.searchParams.get('lcz-assistant')==='1')await register(sender.tab.id,u.origin);return {ok:true,dedicated:await isDedicated(sender.tab.id,u.href)}}
    async function open(sender) {
      const source=originOf(sender);if(opening.has(source.origin))return opening.get(source.origin);
      const pending=(async()=>{
        const tabs=await api.tabs.query({url:allowedOrigins.map(origin=>origin+'/*')});
        const registered=await read();let tab=tabs.find(t=>{try{return new URL(t.url).origin===source.origin&&(registered[t.id]===source.origin||dedicated(t,source.origin))}catch(_e){return false}});
        if(tab)await api.tabs.update(tab.id,{active:true});
        else tab=await api.tabs.create({url:source.origin+'/chats?lcz-assistant=1',active:true});
        await register(tab.id,source.origin);
        if(Number.isInteger(tab.windowId))await api.windows.update(tab.windowId,{focused:true});
        return {ok:true,tab_id:tab.id};
      })();opening.set(source.origin,pending);try{return await pending}finally{if(opening.get(source.origin)===pending)opening.delete(source.origin)}
    }
    async function occupied(sender){
      originOf(sender);const tabs=await api.tabs.query({url:allowedOrigins.map(origin=>origin+'/*')}),registered=await read();
      return {ok:true,ids:[...new Set(tabs.flatMap(t=>{try{const u=new URL(t.url);return allowedOrigins.includes(u.origin)&&registered[t.id]!==u.origin&&u.searchParams.get('lcz-assistant')!=='1'?[decodeURIComponent((u.pathname.match(/^\/chats\/([^/]+)/)||[])[1]||'')]:[]}catch(_e){return[]}}).filter(Boolean))]};
    }
    async function action(kind,sender) {
      if(kind==='open')return open(sender);
      const source=originOf(sender);
      if(!await isDedicated(sender.tab.id,source.href)&&!dedicated({url:source.href},source.origin))throw Error('Действие доступно только во вкладке помощника');
      if(kind==='detach'){await api.windows.create({tabId:sender.tab.id,type:'normal',focused:true});return {ok:true}}
      if(kind==='close'){await api.tabs.remove(sender.tab.id);return {ok:true}}
      throw Error('Неизвестное действие вкладки');
    }
    return {action,surface,isDedicated,occupied};
  }return {create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_PERSONAL_TAB;
