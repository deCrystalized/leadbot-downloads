/* Replies to one branch query: stable cursor, no promises inferred from acknowledgements. */
const LC_CITY_REPLY = (() => {
  const seconds = v => { const n=Number(v)||0;return n>1e11?Math.floor(n/1000):n; };
  const key = x => x.id || x.message_id ? JSON.stringify(['id',String(x.id||x.message_id),String(x.text||'')]) : JSON.stringify([seconds(x.at),String(x.from||''),String(x.text||'')]);
  function describe(text) {
    const t=String(text||'').trim().toLowerCase().replace(/ё/g,'е');
    const ack=/^(?:сек(?:унду)?|минут(?:у|ку)|сейчас(?: уточню| посмотрю| проверю)?|уточняю|ок(?:ей)?|хорошо|принято|понял[аи]?|\+|👍|👌)[.!\s]*$/u.test(t);
    if(!t||ack)return {notify:false,reply:'',lateMinutes:0};
    if(/[?]|(?:^|[\s,])(?:если|наверно\S*|возмож\S*|может)(?:[\s,.]|$)|не\s+(?:выехал|едет|приедет|будет|позвонит)|клиент|диспетчер|\bя\s+(?:еду|выехал|буду)/u.test(t))return {notify:true,reply:'',lateMinutes:0};
    if(/(?:позвонит|свяжется)/.test(t))return {notify:true,reply:'Мастер свяжется с вами.',lateMinutes:0};
    const delay=t.match(/(?:опаздыва\S*|опозда\S*|задержива\S*|задержится)\s+(?:на\s*)?(\d{1,3})\s*мин/);
    if(delay){const n=Number(delay[1]);return {notify:true,reply:'Мастер задерживается на '+n+' минут. Извините за ожидание!',lateMinutes:n};}
    const eta=t.match(/(?:будет|приедет|подъедет)\s+(?:примерно\s+)?через\s+(\d{1,3})\s*мин/)
      ||t.match(/через\s+(\d{1,3})\s*мин\S*\s+(?:будет|приедет|подъедет)/);
    if(eta)return {notify:true,reply:'По информации филиала, мастер будет у вас примерно через '+Number(eta[1])+' минут.',lateMinutes:0};
    if(/(?:^|\s)(?:в пути|едет|выехал|подъезжает)(?:[.!\s]|$)/.test(t))return {notify:true,reply:'Мастер едет к вам.',lateMinutes:0};
    return {notify:true,reply:'',lateMinutes:0};
  }
  function select(rows,cursor={}) {
    const seen=seconds(cursor.seen),keys=new Set(cursor.seenReplies||[]);
    const fresh=(Array.isArray(rows)?rows:[]).filter(x=>x&&typeof x==='object'&&!keys.has(key(x))&&(!seconds(x.at)||seconds(x.at)>=seen))
      .sort((a,b)=>seconds(a.at)-seconds(b.at)||(Number(a.id||a.message_id)||0)-(Number(b.id||b.message_id)||0));
    let latest=null,max=seen;
    for(const x of fresh){keys.add(key(x));max=Math.max(max,seconds(x.at));if(describe(x.text).notify)latest=x;}
    return {latest,cursor:{seen:max,seenReplies:[...keys].slice(-100)}};
  }
  return {select,describe};
})();
if(typeof module==='object'&&module.exports)module.exports=LC_CITY_REPLY;
