/* Read-only spectator. Only native assistant enrollment is a managed dialogue.
   Opening/focusing/polling never marks messages read, claims or starts auto. */
const LC_OBSERVER=(()=>{
  const style=`
  :host-context(.lcz-personal-page) .panel:has(.observer){--ob-surface:var(--raise,#18201f);--ob-line:var(--line,#303b39);--ob-muted:var(--t3,#a1ada8)}
  :host-context(.lcz-personal-page) .panel .pb{max-width:none;width:100%;padding:18px 24px}
  :host-context(.lcz-personal-page) .panel .ph{padding:16px 24px;background:var(--bg,#101614)}
  :host-context(.lcz-personal-page) .assistant-view{grid-template-columns:minmax(0,1fr);gap:20px}
  :host-context(.lcz-personal-page) .assistant-view>[data-personal]{grid-column:1/-1!important;grid-row:auto!important;border-right:0;padding:0;display:grid;grid-template-columns:minmax(220px,1fr) auto;gap:14px;align-items:center}
  :host-context(.lcz-personal-page) .assistant-view>:not([data-personal]){grid-column:1/-1!important}
  .observer-controls-main{display:flex;gap:18px;align-items:center;min-width:0}.observer-owner{display:grid;gap:3px;min-width:0}.observer-owner small{color:var(--t3);font-size:11px}.observer-owner strong{font-size:13px}.observer-author{display:grid;gap:5px;font-size:11px;color:var(--t3);min-width:180px;max-width:300px}.observer-author select{min-height:38px;width:100%;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:8px;padding:6px 32px 6px 10px;background:var(--raise,var(--sunk));color:var(--t1)}
  .observer-control-actions{display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap}.observer-control-actions .go{min-height:40px;height:auto;min-width:140px;padding:8px 14px;font-size:13px;border-radius:8px}.observer-session{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--t3)}.observer-session i{width:6px;height:6px;background:currentColor;border-radius:50%}.observer-session.running{color:var(--ok,#8ad09e)}
  [data-personal]>.assistant-notice,[data-personal]>.assistant-sources,[data-personal]>.assistant-reason{grid-column:1/-1}
  .observer{min-width:0}.observer-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px}.observer-toolbar>div:first-child{flex:1}.observer-toolbar h2{font-size:19px;letter-spacing:-.4px;margin:0 0 5px;font-weight:650}.observer-toolbar small{color:var(--t3);font-size:11px}.observer-search{display:flex;align-items:center;gap:8px;border:1px solid var(--line);background:var(--sunk);border-radius:8px;padding:0 10px;min-width:220px;height:38px}.observer-search span{font-size:23px;color:var(--t3)}.observer-search input{width:100%;height:36px;background:none;border:0;padding:0;color:var(--t1);font:inherit;font-size:12px}.observer-search:focus-within{outline:2px solid var(--acc);outline-offset:2px}.observer-search input:focus-visible{outline:0;box-shadow:none}
  .observer-filters{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:0 0 16px}.observer-filter{min-height:34px;display:flex;align-items:center;gap:8px;border-radius:7px;border:1px solid transparent;background:transparent;color:var(--t3);font:inherit;font-size:12px;padding:5px 10px;cursor:pointer}.observer-filter span{font-size:10px;font-variant-numeric:tabular-nums;border-radius:4px;background:var(--sunk);padding:2px 5px}.observer-filter:hover{color:var(--t1);background:var(--sunk)}.observer-filter.selected{border-color:var(--line);color:var(--t1);background:var(--raise,var(--sunk));font-weight:600}
  .observer-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.observer-card{display:flex;flex-direction:column;min-width:0;height:clamp(230px,calc((100dvh - 330px)/2),420px);padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--ob-surface,var(--raise,var(--sunk)));gap:9px;box-shadow:0 2px 8px #00000008;transition:border-color .15s,box-shadow .15s}.observer-card:hover{border-color:var(--t4,var(--t3));box-shadow:0 4px 14px #00000012}.observer-card.attention{border-top:2px solid var(--warn,#d3aa65)}.observer-card header{display:flex;align-items:center;gap:8px;min-height:34px}.observer-avatar{height:32px;width:32px;border:1px solid var(--line);background:var(--sunk);border-radius:10px;color:var(--t2);font-size:11px;font-weight:650;display:grid;place-items:center;flex-shrink:0}.observer-person{min-width:0;flex:1}.observer-person .btn{display:block;border:0!important;padding:0!important;min-height:0!important;font-size:12px!important;font-weight:650;line-height:1.5;max-width:100%;white-space:nowrap!important;overflow:hidden;text-overflow:ellipsis;border-radius:2px!important}.observer-person small{display:block;font-size:10px;color:var(--t3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.observer-card kbd{font:10px ui-monospace,monospace;color:var(--t3);border:1px solid var(--line);border-radius:4px;padding:2px 4px;align-self:flex-start}.observer-state-row{display:flex;align-items:center;justify-content:space-between;gap:6px}.observer-state-row time{font-size:10px;color:var(--t3);font-variant-numeric:tabular-nums}.observer-badge{display:flex;align-items:center;gap:5px;font-size:10px;font-weight:550;color:var(--t2)}.observer-badge i{width:5px;height:5px;border-radius:50%;background:currentColor}.observer-badge.attention{color:var(--warn,#d3aa65)}.observer-badge.completed{color:var(--ok,#8ad09e)}.observer-badge.paused{color:var(--info,#93b4d3)}
  .observer-messages{flex:1;overflow:auto;min-height:50px;display:flex;flex-direction:column;gap:7px;overscroll-behavior:contain;padding:2px 3px 2px 0;scrollbar-width:thin;scrollbar-color:var(--line) transparent}.observer-message{font-size:11px;line-height:1.55;overflow-wrap:anywhere;padding:7px 8px;border-radius:8px;background:var(--sunk);margin-right:12px}.observer-message.outgoing{margin-right:0;margin-left:12px;background:color-mix(in srgb,var(--acc,#70b68c) 8%,var(--sunk));border:1px solid color-mix(in srgb,var(--acc,#70b68c) 15%,transparent)}.observer-message small{display:block;color:var(--t3);font-size:9px;margin-bottom:3px}.observer-messages>small{font-size:9px;color:var(--t3)}.observer-next{display:grid;gap:2px;border-top:1px solid var(--line);padding-top:7px;min-height:34px}.observer-next small,.observer-draft small{font-size:9px;color:var(--t3)}.observer-next>span{font-size:10px;line-height:1.5;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.observer-card footer{display:flex;gap:6px}.observer-card footer .btn{flex:1;padding:5px 7px;font-size:10px;min-height:30px;border-radius:6px}.observer-card footer .btn:first-child{background:var(--sunk)}.observer-draft{font-size:11px;max-height:55px;overflow:auto;color:var(--t2)}.observer-draft small{display:block;margin-bottom:3px}
  .observer-grid.focused{grid-template-columns:1fr;max-width:1100px;margin:0 auto}.observer-grid.focused .observer-card{height:calc(100dvh - 310px);min-height:380px;padding:20px;gap:12px}.observer-grid.focused .observer-message{max-width:72%;padding:12px 14px;font-size:13px;margin-right:auto}.observer-grid.focused .observer-message.outgoing{margin-left:auto;margin-right:0}.observer-grid.focused .observer-message small{font-size:10px}.observer-grid.focused .observer-person .btn{font-size:15px!important}.observer-grid.focused .observer-next>span{white-space:normal;font-size:12px}.observer-grid.focused .observer-card footer .btn{flex:none;min-height:36px;font-size:12px;padding:7px 14px}.observer-grid.focused .observer-card footer .btn:nth-child(2){margin-left:auto}
  .observer-pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:16px;color:var(--t3)}.observer-pagination>div{display:flex;gap:12px;align-items:center}.observer-pagination small,.observer-pagination span{font-size:11px}.observer-pagination .btn{min-height:32px;padding:5px 10px;font-size:11px}.observer-empty{padding:42px 20px;text-align:center;color:var(--t3);border:1px dashed var(--line);border-radius:12px;min-height:220px;display:grid;justify-items:center;align-content:center;gap:10px}.observer-empty h3{font-size:16px;color:var(--t1);margin:0}.observer-empty p{max-width:420px;font-size:12px;line-height:1.6;margin:0}.observer-empty-mark{font-size:28px;color:var(--t3)}.observer-error{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:var(--warn-bg,#2b2418);border:1px solid var(--warn-line,#554832);border-radius:8px;padding:12px;margin-bottom:12px;font-size:12px}.observer-error span{flex:1}.observer-read-error{font-size:11px;color:var(--warn,#d3aa65);margin:0}
  @media(min-width:1200px) and (max-height:820px){
    :host-context(.lcz-personal-page) .panel .ph{padding:10px 24px}
    :host-context(.lcz-personal-page) .panel .pb{padding:12px 24px}
    :host-context(.lcz-personal-page) .assistant-view{gap:12px}
    :host-context(.lcz-personal-page) .assistant-view>[data-personal]{gap:8px}
    [data-personal]>.assistant-sources summary{padding:2px 0;min-height:22px}
    .observer-toolbar{margin-bottom:8px}.observer-toolbar h2{font-size:17px;margin-bottom:3px}.observer-filters{margin-bottom:10px}.observer-card{height:202px;padding:10px;gap:6px}.observer-avatar{width:28px;height:28px;border-radius:8px}.observer-card header{min-height:30px}.observer-messages{min-height:32px}.observer-next{min-height:31px;padding-top:5px}.observer-card footer .btn{min-height:28px;padding:4px 6px}.observer-grid.focused .observer-card{height:calc(100dvh - 270px);min-height:360px}.observer-pagination{margin-top:10px}
  }
  @media(max-width:1199px){.observer-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.observer-card{height:300px}}
  @media(max-width:780px){:host-context(.lcz-personal-page) .assistant-view>[data-personal]{grid-template-columns:1fr}.observer-control-actions{justify-content:flex-start}.observer-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.observer-toolbar{gap:8px}.observer-search{min-width:190px}}
  @media(max-width:480px){:host-context(.lcz-personal-page) .panel .pb{padding:16px 14px}.observer-grid{grid-template-columns:1fr}.observer-controls-main{flex-wrap:wrap;gap:12px}.observer-control-actions{display:grid;grid-template-columns:1fr 1fr}.observer-control-actions>.go:last-child{grid-column:1/-1}.observer-author{max-width:none;flex:1}.observer-toolbar>div:first-child{flex-basis:100%}.observer-search{flex:1;min-width:0}.observer-filters{gap:2px}.observer-filter{font-size:11px;padding:6px 7px}.observer-card{height:360px}.observer-grid.focused .observer-card{padding:12px;min-height:400px}.observer-grid.focused .observer-message{max-width:90%}.observer-grid.focused .observer-card footer{flex-wrap:wrap}.observer-pagination{align-items:flex-start;flex-wrap:wrap}}
  .observer{font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
  .observer-toolbar{gap:16px;margin:8px 0 20px}.observer-toolbar h2{font-size:26px;line-height:1.25;letter-spacing:-.7px;text-wrap:balance;margin:6px 0 7px}.observer-toolbar small{font-size:12px}.observer-toolbar .observer-eyebrow{font-size:10px;letter-spacing:1.8px;color:var(--acc,#8acbab);font-weight:650}.observer-toolbar .btn{min-height:40px}
  .observer-view-controls{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:14px 0;border-top:1px solid var(--line);margin-bottom:10px}.observer-scope{flex:1;color:var(--t3);font-size:12px;min-width:180px}.observer-option{display:flex;align-items:center;gap:8px;color:var(--t3);font-size:11px}.observer-option select{min-height:40px;padding:7px 28px 7px 11px;border:1px solid var(--line);border-radius:9px;background:var(--raise,var(--sunk));color:var(--t1);font:inherit;font-size:12px;cursor:pointer}.observer-option select:focus-visible,.observer .btn:focus-visible,.observer-filter:focus-visible{outline:2px solid var(--acc);outline-offset:3px}
  .observer-search{height:42px;min-width:260px;border-radius:10px}.observer-search input{height:40px;font-size:13px}.observer-filters{gap:8px;margin-bottom:20px}.observer-filter{min-height:40px;padding:8px 12px;border-radius:9px;font-size:12px}.observer-filter.selected{border-color:color-mix(in srgb,var(--acc) 35%,var(--line));background:color-mix(in srgb,var(--acc) 8%,var(--sunk))}.observer-filter span{min-width:22px;text-align:center;font-size:11px}
  .observer-grid{grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:16px}.observer .observer-card{height:350px;padding:16px;gap:12px;border-radius:16px;box-shadow:0 3px 14px #0000000b}.observer-card.attention{border-top-width:1px;border-color:color-mix(in srgb,var(--warn,#d3aa65) 50%,var(--line))}.observer-card header{min-height:40px}.observer-avatar{width:38px;height:38px;border-radius:12px;font-size:13px}.observer-person .btn{font-size:14px!important}.observer-person small{font-size:11px}.observer-badge{font-size:11px}.observer-message{font-size:12px;padding:9px 10px;border-radius:10px;line-height:1.6;text-wrap:pretty}.observer-message small{font-size:10px}.observer-message.service{border:1px dashed var(--line);background:transparent;margin:0;color:var(--t3);font-size:11px}.observer-next{gap:4px;min-height:42px;padding-top:10px}.observer-next small,.observer-draft small{font-size:10px}.observer-next>span{font-size:12px}.observer-card footer .btn{min-height:40px;padding:7px 10px;font-size:12px;border-radius:9px}.observer-draft{font-size:12px}.observer-pagination{padding:16px 0 4px;margin-top:12px;border-top:1px solid var(--line)}.observer-pagination .btn{min-height:40px}.observer-empty{border-style:solid;background:var(--sunk);padding:56px 24px;border-radius:16px}.observer-empty h3{font-size:19px;text-wrap:balance}.observer-empty p{font-size:13px;text-wrap:pretty}
  .observer.compact .observer-grid{grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:12px}.observer.compact .observer-card{height:285px;padding:12px;gap:8px}.observer.compact .observer-message{font-size:11px;padding:7px 8px}.observer.compact .observer-next{min-height:34px;padding-top:6px}.observer.compact .observer-card footer .btn{font-size:11px;min-height:36px}
  .observer.layout-list .observer-grid:not(.focused){grid-template-columns:1fr}.observer.layout-list .observer-grid:not(.focused) .observer-card{display:grid;grid-template-columns:200px minmax(0,1fr) 220px;grid-template-rows:auto 1fr;height:210px;gap:10px 20px}.observer.layout-list .observer-grid:not(.focused) .observer-messages{grid-column:2;grid-row:1/3}.observer.layout-list .observer-grid:not(.focused) .observer-next{grid-column:3;grid-row:1;border-top:0;padding-top:0}.observer.layout-list .observer-grid:not(.focused) .observer-next>span{white-space:normal}.observer.layout-list .observer-grid:not(.focused) footer{grid-column:3;grid-row:2;align-self:end}.observer.layout-list .observer-grid:not(.focused) .observer-draft{display:none}.observer .observer-grid.focused{grid-template-columns:1fr;max-width:1100px}.observer .observer-grid.focused .observer-card{height:max(480px,calc(100dvh - 300px));padding:24px}
  @media(max-width:900px){.observer.layout-list .observer-grid:not(.focused) .observer-card{display:flex;height:340px}.observer-view-controls{gap:10px}.observer-scope{flex-basis:100%}.observer-search{min-width:200px}.observer-toolbar h2{font-size:23px}}
  @media(max-width:480px){.observer-view-controls{display:grid;grid-template-columns:1fr}.observer-option{justify-content:space-between}.observer-option select{min-width:165px}.observer-toolbar h2{font-size:22px}.observer-grid,.observer.compact .observer-grid{grid-template-columns:1fr}.observer-pagination>div{gap:8px}.observer .observer-grid.focused .observer-card{padding:14px}}
  @media(prefers-reduced-motion:reduce){.observer-card,.observer .btn,.observer-filter{transition:none!important;animation:none!important}}
  `;
  function create(deps){
    const state={rows:[],offset:0,pageSize:25,layout:'cards',density:'comfortable',more:false,focus:'',busy:false,listBusy:false,error:'',filter:'all',query:'',updatedAt:null,source:'managed',total:null},cache=new Map(),actions=new Map(),takingOver=new Set();
    let generation=0,stopped=false,reading=0;const readQueue=[];
    const emit=()=>deps.onChange?.(state);
    function pumpReads(){
      while(reading<4&&readQueue.length){const item=readQueue.shift();if(item.g!==generation||stopped){item.resolve(false);continue}reading++;item.resolve(true)}
    }
    async function readContext(id,g){
      const admitted=await new Promise(resolve=>{readQueue.push({g,resolve});pumpReads()});
      if(!admitted)return;
      const schedule=deps.schedule||setTimeout,clear=deps.clear||clearTimeout;let handle;
      try{return await Promise.race([deps.loadContext(id),new Promise((_,reject)=>{handle=schedule(()=>reject(Error('Чтение истории заняло слишком долго')),deps.historyTimeout||12000)})])}
      finally{clear(handle);reading--;pumpReads()}
    }
    const currentRow=(row,g)=>g===generation&&!stopped&&state.rows.includes(row);
    async function readRow(row,g){
      if(row.loading||!currentRow(row,g))return;
      row.loading=true;emit();
      try{const ctx=await readContext(row.id,g);if(!currentRow(row,g))return;if(ctx?.convId&&ctx.convId!==row.id)throw Error('История относится к другому диалогу');row.ctx=ctx;row.readError=''}
      catch(e){if(currentRow(row,g))row.readError=String(e.message||e)}
      finally{if(currentRow(row,g)){row.loading=false;cache.set(row.id,row);while(cache.size>256)cache.delete(cache.keys().next().value);emit()}}
    }
    function update(rows){
      for(const row of rows||[])if(row?.id){
        const previous=actions.get(row.id),workflow=typeof row.step==='string'||!!row.research_state;
        // A scan proves eligibility, not progress. Its periodic generic reason
        // must not hide a worker's admission/review wait or prepared result.
        if(previous?._workflow&&!workflow&&row.eligible!==false)continue;
        actions.set(row.id,{...row,_workflow:workflow});
      }
      emit();
    }
    async function refresh(offset=state.offset){
      if(stopped||state.listBusy||offset===state.offset&&(state.busy||state.rows.some(row=>row.loading)))return;
      state.busy=true;state.listBusy=true;state.error='';const g=++generation;emit();
      try{
        const pageSize=state.pageSize;
        const managed=['managed','archive'].includes(state.source);
        const page=await (managed?deps.list({limit:pageSize,offset,...(state.source==='archive'?{view:'archive'}:{})}):deps.listCandidates(state.source,{limit:pageSize,offset}));
        if(!Array.isArray(page?.items)||typeof page.more!=='boolean'||page.items.length>pageSize
            ||page.items.some(row=>!row?.id)||new Set(page.items.map(row=>row.id)).size!==page.items.length)throw Error('Не подтверждён список диалогов помощника');
        if(g!==generation||stopped)return;
        if(offset>0&&page.items.length===0&&Number.isInteger(page.total)&&page.total<=offset){
          state.busy=false;state.listBusy=false;
          return await refresh(Math.max(0,Math.floor((page.total-1)/pageSize)*pageSize));
        }
        const rows=page.items.map(job=>{
          const stamp=[job.version,job.last_message_at,job.source_revision,job.conversation_status,job.assignee_id].join(':'),previous=state.rows.find(row=>row.id===job.id),saved=cache.get(job.id);
          if(Number.isInteger(previous?.version)&&Number.isInteger(job.version)&&previous.version>job.version)return previous.loading?{...previous,loading:false}:previous;
          if(previous?.stamp===stamp)return previous.loading?{...previous,...job,loading:false}:Object.assign(previous,job);
          if(previous||saved&&saved.stamp!==stamp)actions.delete(job.id); // A known source changed, including off-page changes; retain first-list progress.
          return {...job,ctx:saved?.stamp===stamp?saved.ctx:null,stamp};
        });
        state.rows=rows;state.offset=offset;state.more=page.more;state.total=page.total??null;state.updatedAt=Date.now();state.listBusy=false;
        if(state.focus&&!rows.some(r=>r.id===state.focus))state.focus='';
        emit();
        // Publish list immediately. One slow history must not hide every card.
        let next=0;
        const hydrate=async row=>{
          if(deps.loadHold){const hold=await deps.loadHold(row);if(!currentRow(row,g))return;row.human_hold=hold||null}
          if(['completed','closed','released'].includes(row.state)||row.state==='candidate'&&row.id!==state.focus)return;
          const previous=cache.get(row.id);if(previous?.stamp===row.stamp&&previous.ctx&&!previous.readError){row.ctx=previous.ctx;return}
          await readRow(row,g);
        };
        await Promise.all(Array.from({length:Math.min(4,rows.length)},async()=>{
          while(next<rows.length&&g===generation&&!stopped){const row=rows[next++];await hydrate(row)}
        }));
      }catch(e){if(g===generation)state.error=String(e.message||e)}
      finally{if(g===generation){state.busy=false;state.listBusy=false;emit()}}
    }
    function focus(id){if(!id||state.rows.some(r=>r.id===id)){state.focus=id||'';emit();const row=state.rows.find(r=>r.id===id);if(row&&!row.ctx&&!row.loading)readRow(row,generation)}}
    function reset(){generation++;cache.clear();actions.clear();state.rows=[];state.offset=0;state.more=false;state.total=null;state.focus='';state.busy=false;state.listBusy=false;state.error='';pumpReads();emit()}
    function source(value){if(!['managed','archive','incoming','mine'].includes(value)||!['managed','archive'].includes(value)&&!deps.listCandidates)return;reset();state.source=value;state.filter='all';return refresh(0)}
    function pageSize(value){const size=Number(value);if(![10,25,50,100].includes(size)||size===state.pageSize)return;reset();state.pageSize=size;return refresh(0)}
    function layout(value){if(['cards','list'].includes(value)){state.layout=value;emit()}}
    function density(value){if(['comfortable','compact'].includes(value)){state.density=value;emit()}}
    function category(row){
      if(row.state==='candidate')return 'candidate';
      if(row.state==='completed')return 'completed';
      if(row.state==='closed')return 'closed';
      if(row.state==='released')return 'released';
      if(row.human_hold?.state==='held')return 'attention';
      if(row.state==='paused')return 'paused';
      const act=actions.get(row.id),lastSpeech=row.ctx?.messages?.findLast(m=>m.direction!=='note'&&!['system','avito','bot'].includes(m.sender_type));
      return row.readError||act?.needs_operator||['handoff','created_review'].includes(act?.step)||lastSpeech?.direction==='out'&&lastSpeech.delivery_status==='failed'?'attention':'waiting';
    }
    function filter(value){if(['all','attention','waiting','paused','completed','closed','released','candidate'].includes(value)){state.filter=value;state.focus='';emit()}}
    function search(value){state.query=String(value).slice(0,200);state.focus='';emit()}
    function matches(row){
      const text=[row.ctx?.clientName,row.ctx?.name,row.candidate_name,deps.authorName?.(row.operator_id),row.crm_request_id,...(row.ctx?.messages||row.previewMessages||[]).map(m=>m.body)].join(' ').toLocaleLowerCase('ru');
      return (state.filter==='all'||category(row)===state.filter)&&(!state.query.trim()||text.includes(state.query.trim().toLocaleLowerCase('ru')));
    }
    const transcriptReady=m=>['done','ready','completed'].includes(String(m.voice_transcript_status||'').toLowerCase());
    function transcriptLabel(m){
      const status=String(m.voice_transcript_status||'').toLowerCase();
      if(transcriptReady(m))return 'расшифровка';
      if(['failed','error','cancelled','canceled'].includes(status))return 'ошибка расшифровки';
      if(['pending','queued','processing','transcribing','running'].includes(status))return 'ещё не готова';
      return 'статус не подтверждён';
    }
    async function takeover(id){
      const row=state.rows.find(r=>r.id===id);if(!row||row.state!=='waiting'||takingOver.has(id))return;
      takingOver.add(id);emit();
      try{const result=await deps.takeover(row);
        if(result?.id===row.id&&result.operator_id===row.operator_id&&result.state==='paused'&&Number.isInteger(result.version)&&result.version>row.version){
          Object.assign(row,result);actions.delete(id);cache.delete(id);emit();
        }
        await refresh()}
      catch(e){state.error=String(e.message||e);emit()}
      finally{takingOver.delete(id);emit()}
    }
    function key(event){
      if(event.altKey||event.ctrlKey||event.metaKey||/^(INPUT|TEXTAREA|SELECT)$/.test(event.target?.tagName)||event.target?.isContentEditable)return;
      if(event.key==='Escape'&&state.focus){focus('');event.preventDefault()}
      else if(/^[0-9]$/.test(event.key)){const row=state.rows[(Number(event.key)+9)%10];if(row){focus(row.id);event.preventDefault()}}
    }
    function view(){
      let buttonIndex=0;
      const h=deps.h,button=(text,fn,disabled=false,key='')=>h('button',{type:'button',class:'btn',onclick:fn,disabled,title:text,'data-assistant-focus':'observer-button-'+(key||buttonIndex++)},text);
      const filtered=state.rows.filter(matches),selected=state.focus?state.rows.filter(r=>r.id===state.focus):filtered;
      const labels={attention:'Нужны вы',waiting:'У бота',paused:'У вас',completed:'Заявка создана',closed:'Закрыт',released:'Не у бота',candidate:'Не передан боту'};
      const counts=Object.fromEntries(Object.keys(labels).map(k=>[k,state.rows.filter(r=>category(r)===k).length]));
      const time=value=>{const d=new Date(value);return value&&Number.isFinite(d.getTime())?d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):''};
      const card=row=>{
        const act=actions.get(row.id),messages=(row.ctx?.messages||row.previewMessages||[]);
        const service=m=>m.direction==='system'||m.direction==='note'||['system','avito'].includes(m.sender_type);
        const shown=state.focus?messages:messages.filter(m=>!service(m)).slice(-2);
        const title=row.ctx?.clientName||row.ctx?.name||row.candidate_name||(row.crm_request_id?'Заявка №'+row.crm_request_id:'Клиент');
        const status=row.state==='candidate'?(row.crm_request_id?'Есть заявка · обработка сотрудником':'Открыть в LeadChat для просмотра или передачи'):row.state==='completed'?'Заявка №'+row.crm_request_id:row.state==='closed'?'Диалог закрыт. Бот не обрабатывает его':row.state==='released'?'Бот не ведёт диалог: ответственный изменился, идёт передача или работает другой бот':row.human_hold?.state==='held'?row.human_hold.reason:row.state==='paused'?'У вас · бот остановлен':act?.reason||'Ожидает запуска или следующего шага';
        const kind=category(row),index=state.rows.findIndex(r=>r.id===row.id),initials=title.trim().split(/\s+/).slice(0,2).map(w=>Array.from(w)[0]).join('').toUpperCase();
        return h('article',{class:'observer-card '+kind,'data-observer-id':row.id,'aria-label':title+' · '+labels[kind]},
          h('header',{},h('span',{class:'observer-avatar','aria-hidden':'true'},initials),
            h('div',{class:'observer-person'},button(title,()=>focus(row.id),false,'title-'+row.id),h('small',{},'Автор: '+(deps.authorName?.(row.operator_id)||'Сотрудник'))),
            index<10?h('kbd',{title:'Открыть клавишей '+((index+1)%10)},String((index+1)%10)):''),
          h('div',{class:'observer-state-row'},h('span',{class:'observer-badge '+kind},h('i',{'aria-hidden':'true'}),labels[kind]),time(row.last_message_at)?h('time',{datetime:row.last_message_at},time(row.last_message_at)):''),
          row.readError?h('div',{class:'observer-read-error',role:'alert'},h('p',{},'История не обновилась. '+row.readError),button('Повторить чтение',()=>readRow(row,generation),row.loading,'retry-'+row.id)):'',
          h('div',{class:'observer-messages',tabindex:0,'aria-label':'Переписка с '+title},
            row.loading?h('small',{role:'status'},'Читаю полную историю…'):row.state==='candidate'&&!row.ctx?h('small',{},'Превью · полная история в фокусе'):'',
            ...shown.map((m,i)=>h('div',{'data-render-key':'message-'+(m.id||i),class:'observer-message '+(service(m)?'service':m.direction==='in'?'incoming':'outgoing')},
              h('small',{},service(m)?'Система':['bot','assistant'].includes(m.sender_type)||String(m.client_message_id||'').startsWith('lcp:')?'Автоматизация':m.direction==='in'?'Клиент':'Сотрудник',time(m.created_at)?' · '+time(m.created_at):'',
                m.direction!=='in'&&m.delivery_status?' · '+({pending:'отправляется',failed:'ошибка отправки',sent:'отправлено',delivered:'доставлено',read:'прочитано'}[m.delivery_status]||m.delivery_status):''),
              h('div',{},m.body&&m.body!==m.voice_transcript?m.body:''),
              m.voice_transcript||m.voice_transcript_status?h('div',{class:'observer-asr'},
                h('small',{},'Аудио · '+transcriptLabel(m)),
                transcriptReady(m)?m.voice_transcript||'Текст недоступен':''):'',
              m.attachments?.length?h('small',{},'Вложения: '+m.attachments.length):'')),
            !state.focus&&messages.some(service)?h('small',{},'Служебных событий: '+messages.filter(service).length+' · в полной истории'):'',
            !messages.length?h('p',{},['completed','closed','released'].includes(row.state)?'Диалог завершён. История автоматически не загружается.':'История пока недоступна'):'',
            !state.focus&&messages.length>shown.length?h('small',{},'В фокусе — вся прочитанная история: '+messages.length+' сообщений'):''),
          h('div',{class:'observer-next',title:status},h('small',{},row.state==='completed'?'Итог':'Текущий шаг'),h('span',{},status)),
          !['candidate','closed','completed','released'].includes(row.state)&&act?.reply?h('div',{class:'observer-draft'},h('small',{},'Последний подготовленный ответ'),h('div',{},act.reply)):'',
          h('footer',{},button(state.focus?'Все диалоги':'В фокус',()=>focus(state.focus?'':row.id),false,'focus-'+row.id),row.state==='candidate'?button('LeadChat ↗',()=>deps.openCandidate?.(row.id),false,'open-'+row.id):button(takingOver.has(row.id)?'Передаю…':'Забрать себе',()=>takeover(row.id),row.state!=='waiting'||takingOver.has(row.id),'takeover-'+row.id),
            state.focus&&row.state==='waiting'?button('Проверить следующий шаг',()=>deps.inspect?.(row.id)):''));
      };
      const select=(label,value,options,change,key)=>h('label',{class:'observer-option'},h('span',{},label),h('select',{'aria-label':label,'data-assistant-focus':'observer-'+key,value,onchange:e=>change(e.target.value)},...options.map(([id,text])=>h('option',{value:id,selected:String(id)===String(value)},text))));
      return h('section',{class:'observer '+state.density+' layout-'+state.layout,'aria-label':'Наблюдение за диалогами бота'},
        h('div',{class:'observer-toolbar'},h('div',{},h('small',{class:'observer-eyebrow'},'РАБОЧЕЕ ПРОСТРАНСТВО'),h('h2',{},state.focus?'Диалог в фокусе':'Обзор диалогов'),h('small',{},state.focus?'Esc — вернуться к обзору':state.updatedAt===null?(state.listBusy?'Загружаю диалоги…':'Данные ещё не подтверждены'):'Видно '+state.rows.length+(Number.isInteger(state.total)?' из '+state.total:'')+' · наблюдение не запускает бота')),
          deps.listCandidates?h('div',{'aria-label':'Очереди',style:'display:flex;gap:6px'},...Object.entries({managed:'У бота',incoming:'Входящие',mine:'У сотрудника',archive:'Архив'}).map(([key,label])=>button(label,()=>source(key),state.source===key,'source-'+key))):'',
          state.focus?button('Все диалоги',()=>focus('')):h('label',{class:'observer-search'},h('span',{'aria-hidden':'true'},'⌕'),h('input',{type:'search',value:state.query,placeholder:'Найти в этих диалогах','aria-label':'Поиск по диалогам на странице','data-assistant-focus':'observer-search',oninput:event=>search(event.target.value)})),
          button(state.busy?'Обновляю…':'Обновить',()=>refresh(),state.busy)),
        !state.focus?h('div',{class:'observer-view-controls','aria-label':'Настройки обзора'},
          h('span',{class:'observer-scope'},'Поиск и статусы — на текущей странице'),
          select('На странице',state.pageSize,[[10,'10 диалогов'],[25,'25 диалогов'],[50,'50 диалогов'],[100,'100 диалогов']],pageSize,'page-size'),
          select('Вид',state.layout,[['cards','Карточки'],['list','Список']],layout,'layout'),
          select('Плотность',state.density,[['comfortable','Удобная'],['compact','Компактная']],density,'density')):'',
        !state.focus&&['managed','archive'].includes(state.source)?h('div',{class:'observer-filters',role:'group','aria-label':'Статус диалогов'},...Object.entries({all:'Все',...Object.fromEntries(Object.entries(labels).filter(([k])=>k!=='candidate'))}).map(([key,label])=>h('button',{type:'button',class:'observer-filter '+(state.filter===key?'selected':''),'aria-pressed':String(state.filter===key),'data-assistant-focus':'observer-filter-'+key,onclick:()=>filter(key)},label,h('span',{},String(key==='all'?state.rows.length:counts[key]))))):'',
        state.error?h('div',{class:'observer-error',role:'alert'},h('b',{},'Не удалось обновить список'),h('span',{},state.error),button('Повторить',()=>refresh(),state.busy)):'',
        !state.rows.length?h('div',{class:'observer-empty',role:'status'},h('span',{class:'observer-empty-mark','aria-hidden':'true'},'＋'),h('h3',{},state.busy?'Загружаю диалоги…':state.source==='managed'?'Здесь будет работа бота':'В этой очереди нет диалогов'),h('p',{},state.busy?'Читаю выбранную очередь.':state.source==='managed'?'Проверьте «Входящие» и «У сотрудника». Передача боту выполняется отдельно в LeadChat.':'Выберите другого сотрудника или обновите список.')):'',
        state.rows.length&&!selected.length?h('div',{class:'observer-empty',role:'status'},h('h3',{},'Нет подходящих диалогов'),h('p',{},'Измените поиск или статус. Фильтры действуют на текущую страницу.'),button('Сбросить фильтры',()=>{state.filter='all';search('')})):'',
        h('div',{class:'observer-grid'+(state.focus?' focused':'')},...selected.map(card)),
        h('div',{class:'observer-pagination'},h('small',{},state.updatedAt?'Обновлено в '+time(state.updatedAt):'Данные ещё не загружены'),h('div',{},button('Назад',()=>refresh(Math.max(0,state.offset-state.pageSize)),state.listBusy||!state.offset),h('span',{},state.total===0?'Нет диалогов':state.total===null&&!state.rows.length?'Данные не загружены':'Страница '+(Math.floor(state.offset/state.pageSize)+1)),button('Далее',()=>refresh(state.offset+state.pageSize),state.listBusy||!state.more))));
    }
    function stop(){generation++;stopped=true;state.busy=false}
    return {state,refresh,view,focus,key,takeover,update,stop,filter,search,source,reset,pageSize,layout,density};
  }
  return {create,style};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_OBSERVER;
