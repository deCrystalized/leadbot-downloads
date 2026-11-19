/* Explicitly started browser loop. No persisted enable flag or server sender. */
const LC_ASSISTANT_RUNNER=(()=>{
  function create(deps){
    const state={mode:'stopped',busy:false,rows:[],error:'',lastMs:0,cycles:0};
    let generation=0,timer=0,pending=false,firstWake=0;const urgent=new Set();
    const now=deps.now||Date.now,schedule=deps.schedule||setTimeout,clear=deps.clear||clearTimeout;
    const emit=()=>deps.onChange?.(state);
    const valid=g=>g===generation&&state.mode!=='stopped'&&deps.visible()&&deps.active();
    const stop=()=>{generation++;clear(timer);timer=0;pending=false;firstWake=0;urgent.clear();deps.stopWorkflow();state.mode='stopped';state.busy=false;emit()};
    function later(delay){clear(timer);timer=schedule(()=>tick(),delay)}
    async function start(mode){
      if(!['review','auto'].includes(mode))throw Error('Неизвестный режим');
      stop();const g=generation;state.error='';state.rows=[];state.mode='starting';emit();
      try{
        const confirmed=await deps.setMode(mode==='auto'?'auto':'review');
        if(g!==generation)return;
        if(!confirmed?.ok||!deps.active()||!deps.visible()||mode==='auto'&&confirmed.auto_enabled!==true)throw Error(confirmed?.error||'Режим не подтверждён сервером');
        state.mode=mode;emit();await tick();
      }catch(e){if(g===generation){stop();state.error=String(e.message||e);emit()}throw e}
    }
    async function tick(){
      const g=generation;if(state.busy||!valid(g))return;
      state.busy=true;pending=false;firstWake=0;const t0=now();let fallback=5000;emit();
      try{
        const priority=[...urgent];urgent.clear();
        const jobs=[],slots=[],seen=new Set(),running=new Set();let next=0,workerError=null;
        function pump(){while(valid(g)&&!workerError&&running.size<4&&next<jobs.length){
          const index=next++,row=jobs[index],started=now();
          const work=(async()=>{let result;
          try{result=await(state.mode==='auto'?deps.step(row.id):deps.inspect(row.id))}
          catch(e){
            if(['research_stopped','research_disabled','research_configuration','native_source_unavailable',
                'operator_identity','personal_identity','personal_expired','auto_disabled','workflow_permission'].includes(e?.code))throw e;
            result=['manual_occupied','busy','workflow_not_started'].includes(e?.code)?{step:'wait',needs_operator:false,reason:String(e.message||e)}
            :['assistant_paused','assistant_unavailable'].includes(e?.code)?{step:'paused',needs_operator:false,reason:String(e.message||e)}
            :{step:'handoff',needs_operator:true,reason:String(e.message||e)}}
          if(!valid(g))return;
          if(state.mode==='auto'&&(result.needs_operator===true||['handoff','created_review'].includes(result.step))&&deps.park){
            const parked=await deps.park(row.id,result);if(!valid(g))return;result={...result,...parked};
          }
          slots[index]={...result,crm_id:result.id||'',id:row.id,name:row.name,duration_ms:now()-started,executed:state.mode==='auto'};
          state.rows=slots.filter(Boolean);emit();
          })().catch(error=>{workerError=error;deps.stopWorkflow()});
          running.add(work);work.finally(()=>{running.delete(work);pump()});
        }}
        const ready=row=>{if(!valid(g)||workerError||!row?.eligible||seen.has(row.id)||seen.size>=12)return;seen.add(row.id);jobs.push(row);pump()};
        const rows=await deps.scan(priority,ready);if(!valid(g))return;
        if(workerError)throw workerError;
        for(const row of rows)ready(row);
        while(running.size){await Promise.all([...running]);if(!valid(g))return}
        if(workerError)throw workerError;
        const results=slots.filter(Boolean);
        // Plan + result reads per dialogue: target 80/min of the public 150/min
        // allowance, leaving room for identity, heartbeat and urgent events.
        // Realtime still wakes promptly; no backend limit or action guard changes.
        fallback=Math.max(5000,results.length*1500);
        state.rows=results;state.lastMs=now()-t0;state.cycles++;
        await deps.log?.({mode:state.mode,duration_ms:state.lastMs,checked:rows.length,actions:results.length});
      }catch(e){
        if(g===generation){stop();state.error=String(e.message||e);await deps.setMode('review').catch(()=>{});emit()}
      }finally{
        if(g===generation){state.busy=false;emit();if(valid(g))later(pending?Math.max(0,800-(now()-firstWake)):fallback)}
      }
    }
    function wake(event){
      if(!['review','auto'].includes(state.mode)||!deps.visible())return;
      if(event?.t==='message:new'&&['system','avito','bot'].includes(event.from))return;
      if(event?.t&&!/^(?:message:|inbox:|conversation:|client:|bot:)/.test(event.t))return;
      if(event?.owner&&deps.operator?.()&&event.owner!==deps.operator())return;
      if(typeof event?.id==='string'&&/^[\w-]{1,64}$/.test(event.id)&&urgent.size<12)urgent.add(event.id);
      if(!firstWake)firstWake=now();pending=true;
      if(!state.busy)later(Math.max(0,Math.min(800,2500-(now()-firstWake))));
    }
    return {state,start,stop,wake,tick};
  }return {create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_ASSISTANT_RUNNER;
