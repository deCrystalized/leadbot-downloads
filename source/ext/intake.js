/* Additional browser intake boundaries. Evidence hints never become CRM facts. */
const LC_INTAKE=(()=>{
  const failed=new Set(['failed','error','cancelled','canceled']);
  const envelope=m=>!(m.attachments||[]).length&&!m.voice_transcript&&/^\s*\[Системное сообщение\]\s*(?:🪄\s*)?Ассистент Авито ответил:\s*["«][\s\S]+["»]\s*💡\s*Ассистент помогает собирать контакты тех, кто действительно заинтересован в ваших услугах\.\s*$/u.test(String(m.body||m.text||''));
  const speech=m=>m&&m.direction!=='note'&&!['system','avito','bot'].includes(m.sender_type)&&!envelope(m)
    &&!failed.has(String(m.delivery_status||m.delivery||'').toLowerCase());
  const client=m=>speech(m)&&m.direction==='in'&&['','client','customer','user','contact','lead'].includes(m.sender_type||'');
  const delivered=m=>speech(m)&&m.direction==='out'&&['delivered','read'].includes(String(m.delivery_status||m.delivery||'').toLowerCase());
  const text=m=>String(m?.body||m?.text||'').trim();
  const nameReferences=name=>[...new Set(String(name||'').replace(/(?:\+?7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}/gu,'').match(/(?<!\d)\d{6,8}(?!\d)/g)||[])];
  const normalize=s=>String(s||'').toLowerCase().replace(/ё/g,'е').replace(/^(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[!, .]*/,'').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  const questionKind=s=>/[?]|подскаж|уточн|пришлите|напишите/iu.test(s)&&/схем|инструкц/i.test(s)&&/сборк|есть|налич/i.test(s)?'assembly_instructions':'';
  const block=(step,reason,code)=>({ok:true,eligible:false,step,action:step==='wait'?'wait':'handoff',admission:step==='wait'?'wait':'skip',reason,code,needs_operator:step==='handoff'});
  function inspect(ctx){
    if(ctx.crmRequestId||ctx.hasCrmJob)return block('skip','По диалогу уже есть заявка. Сопровождение — сотруднику','existing_order');
    if(nameReferences(ctx.clientName).length)return block('skip','В имени клиента указан номер заявки. Сначала проверьте существующую заявку','order_name_hint');
    const rows=(ctx.messages||[]).filter(speech),lastClient=rows.findLastIndex(client);
    if(lastClient<0)return block('wait','Нового сообщения клиента нет','no_client_turn');
    const after=rows.slice(lastClient+1);
    if(after.some(m=>m.direction==='out'))return block('wait','На сообщение клиента уже ответили. Ждём следующего сообщения','client_turn_answered');
    const latest=rows[lastClient],body=text(latest),previous=rows.slice(0,lastClient).findLast(delivered);
    // A first-person promise is not a picture, a diagram or a new booking.
    const unquoted=body.replace(/«[^»]*»|“[^”]*”|"[^"]*"/gu,'');
    const promise=/(?<![\p{L}])(?:скину|пришлю|вышлю|отправлю)(?![\p{L}])/iu.test(unquoted)
      &&/(?:фото|картинк|изображени|снимок|схем)/iu.test(unquoted)
      &&!/[?]|(?<![\p{L}])(?:не|если|когда|потом|завтра)(?![\p{L}])|сказал|говорит|написал|попросил|обещал|мастер|сотрудник/iu.test(unquoted);
    if(previous&&promise&&!(latest.attachments||[]).length&&!/цен|стоит|сможете|сможите|приех|приед|адрес|телефон/iu.test(body))
      return block('wait','Клиент собирается прислать изображение. Ждём его, вопрос не повторяем','promised_image');
    return null;
  }
  function replyIssue(ctx,reply){
    const normalized=normalize(reply);if(!normalized)return '';
    const kind=questionKind(reply),rows=(ctx.messages||[]).filter(delivered);
    if(rows.some(m=>normalize(text(m))===normalized||kind&&questionKind(text(m))===kind))
      return 'Этот вопрос уже был доставлен клиенту. Повтор остановлен: проверьте его ответ';
    return '';
  }
  async function check(ctx,readHistory,contact){
    const local=inspect(ctx);if(local)return local;
    if(contact?.сомнение)return block('skip','Контакт требует проверки перед поиском существующей заявки','contact_uncertain');
    const digits=String(contact?.phone||'').replace(/\D/g,'');
    if(!digits)return null;
    if(!/^(?:7|8)?\d{10}$/.test(digits))return block('skip','Не подтверждён номер для проверки истории CRM','contact_uncertain');
    let history;try{history=await readHistory(digits.slice(-10))}catch(_e){return block('skip','История CRM не проверена. Новый диалог не берём','crm_unchecked')}
    if(history?.ok!==true||!Array.isArray(history.found)||!Array.isArray(history.unchecked)||history.unchecked.length)
      return block('skip','История CRM не проверена полностью. Новый диалог не берём','crm_unchecked');
    // Closed history is also a repeat request requiring a human decision.
    if(history.found.length)return block('skip','По этому номеру есть история заявок. Сначала проверка сотрудником','crm_history');
    return null;
  }
  return {inspect,check,replyIssue,nameReferences,normalize};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_INTAKE;
