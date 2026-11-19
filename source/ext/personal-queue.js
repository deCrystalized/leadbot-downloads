/* Page through the entire own/free queue without downloading or capping it. */
const LC_PERSONAL_QUEUE=(()=>{
  function create(deps){
    const active=new Set(['new','in_progress','waiting_client']);
    const total=p=>{if(!Number.isInteger(p?.page?.total)||p.page.total<0||!Array.isArray(p.items))throw Error('Не подтверждён полный размер очереди');return p.page.total};
    const owner=r=>String(r.assignee?.id||r.assignee_id||r.claimed_by?.id||r.claimed_by_id||'');
    const created=r=>{
      if(typeof LC_INTAKE!=='undefined'?LC_INTAKE.nameReferences(r?.client?.name).length:/(?<!\d)\d{6,8}(?!\d)/.test(String(r?.client?.name||'')))return true;
      const id=r?.crm_request_id;
      return (typeof id==='string'||Number.isSafeInteger(id))&&/^[1-9]\d{0,11}$/.test(String(id).trim());
    };
    // A confirmed order finishes this bot's intake. Keep the conversation in
    // its actual folder; filtering only avoids history/model work on it.
    const convert=r=>({id:r.id,name:r.client?.name||'Клиент',assigneeId:owner(r)});
    async function load(options={}){
      const me=String(await deps.identity()||'');if(!me)throw Error('Не определён личный аккаунт LeadChat');
      const mine=deps.minePath?deps.minePath(me):'/conversations?tab=mine&assignee_id='+encodeURIComponent(me);
      const free=deps.freePath?deps.freePath(me):'/inbox';
      if(options.countOnly){const page=await deps.get(mine+'&limit=1');return{mineCount:total(page),rows:[],total:total(page)}}
      const ids=[...new Set(Array.isArray(options.priorityIds)?options.priorityIds:[])].filter(id=>typeof id==='string'&&/^[\w-]{1,64}$/.test(id)).slice(0,12);
      const [mineHead,freeHead,urgent]=await Promise.all([deps.get(mine+'&limit=2'),deps.get(free+(free.includes('?')?'&':'?')+'limit=6'),Promise.all(ids.map(id=>deps.detail(id)))]);
      const mineCount=total(mineHead),freeCount=total(freeHead),count=mineCount+freeCount;
      const priority=urgent.filter(r=>r?.id&&active.has(r.status)&&!created(r)&&(owner(r)===me||!owner(r)&&r.in_inbox===true&&r.can_claim!==false));
      // Refresh the free head on EVERY cycle, even if the rotating cursor is deep in old assignments.
      // Keep at least four rotating slots so repeated head rows cannot starve the backlog.
      const fast=[...new Map([...priority,...freeHead.items,...mineHead.items].filter(r=>r?.id&&active.has(r.status)&&!created(r)&&(owner(r)===me||!owner(r)&&r.can_claim!==false)).map(r=>[r.id,r])).values()].slice(0,8);
      const budget=12-fast.length;
      const start=Number.isInteger(options.offset)&&options.offset>=0&&options.offset<count?options.offset:0;
      const freeSize=Math.max(0,Math.min(budget,freeCount-start)),ownSize=budget-freeSize;
      const [ownPage,freePage]=await Promise.all([
        ownSize&&mineCount?deps.get(mine+'&limit='+ownSize+'&offset='+Math.max(0,start-freeCount)):Promise.resolve({items:[]}),
        freeSize?deps.get(free+(free.includes('?')?'&':'?')+'limit='+freeSize+'&offset='+start):Promise.resolve({items:[]})]);
      if(!Array.isArray(ownPage?.items)||!Array.isArray(freePage?.items))throw Error('Не удалось прочитать страницу очереди');
      const normal=[...freePage.items,...ownPage.items];
      // A colleague may take/close the last rows between the head and page reads.
      // Keep fresh head candidates (each gets a new ownership check) and restart
      // pagination next cycle. A normal queue race must not stop the runner.
      const changed=!!(budget&&start<count&&!normal.length);
      const rows=[...new Map([...fast,...normal].filter(r=>r?.id&&active.has(r.status)&&!created(r)&&(owner(r)===me||!owner(r)&&r.can_claim!==false)).map(r=>[r.id,convert(r)])).values()];
      return{mineCount,total:count,rows,paged:true,nextOffset:changed?0:start+normal.length,more:changed?count>0:start+normal.length<count,queueChanged:changed};
    }
    return{load};
  }return{create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_PERSONAL_QUEUE;
