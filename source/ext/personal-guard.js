/* Offscreen CRM must ask its original assistant tab again immediately before POST. */
const LC_PERSONAL_GUARD=(()=>{
  function create(api,origins,isDedicated){return async function check(sender,g){
    if(sender?.id!==api.runtime.id||sender?.url!==api.runtime.getURL('offscreen.html')||!Number.isInteger(g?.tab_id))return {ok:false,error:'Источник проверки не подтверждён'};
    let tab;try{tab=await api.tabs.get(g.tab_id)}catch(_e){return {ok:false,error:'Вкладка помощника закрыта'}}
    const u=new URL(tab.url);if(!origins.includes(u.origin)||!(isDedicated?await isDedicated(g.tab_id,tab.url):u.searchParams.get('lcz-assistant')==='1'))return {ok:false,error:'Это не вкладка личного помощника'};
    try{const r=await api.tabs.sendMessage(g.tab_id,{kind:'lcz-personal-check',guard:g});return r?.ok?r:{ok:false,error:r?.error||'Личный аккаунт или данные изменились'}}catch(_e){return {ok:false,error:'Помощник не подтвердил личный аккаунт'}}
  }}return {create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_PERSONAL_GUARD;
