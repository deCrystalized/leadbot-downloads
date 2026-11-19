/* Generated from LeadBot ext/assistant-native.js; do not edit independently.
 * createRun SHA256: 378a3423459b2963cc56a8a463f34d83d844611b5a4ac6fb7992009c242009e8
 */
/* eslint @typescript-eslint/no-unused-vars: ["error", { "caughtErrorsIgnorePattern": "^_error$" }] */
export const createRun = function createRun(deps){
    if(['get','post','identity','principal','operator'].some(k=>typeof deps[k]!=='function'))throw Error('Нужен серверный контроль аккаунта');
    const base='/bot-dialogs/assistant/native-run',now=deps.now||Date.now;
    const schedule=deps.schedule||setTimeout,clear=deps.clear||clearTimeout;
    const state={view:null,stale:true,lastConfirmedAt:null,error:'',busy:false,unknown:null};
    let epoch=0,timer=null,watching=false,pending=null,prepared=null;
    const emit=()=>deps.onChange?.(state);
    const uuid=x=>typeof x==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(x);
    const failure=message=>Error(message);
    async function identity(){
      const me=await deps.identity(),principal=String(deps.principal()||'');
      if(me?.role!=='admin'||!uuid(me.id)||me.id!==principal
          ||state.view&&state.view.principal_id!==principal||state.unknown&&state.unknown.principal_id!==principal){
        unwatch();state.view=null;state.unknown=null;state.stale=true;state.lastConfirmedAt=null;
        state.error='Аккаунт изменился. Откройте панель под своим администратором';emit();
        throw failure(state.error);
      }
      return principal;
    }
    function snapshot(value,principal,readiness){
      if(!value||typeof value!=='object'||Array.isArray(value)||value.principal_id!==principal
          ||!['running','stopped','blocked'].includes(value.state)||!['auto','rehearsal'].includes(value.mode)
          ||!Number.isSafeInteger(value.generation)||value.generation<0
          ||typeof value.auto_enabled!=='boolean'||value.auto_enabled!==(value.state==='running'&&value.mode==='auto')
          ||value.generation===0&&(value.run_id!==null||value.operator_id!==null||value.state!=='stopped')
          ||value.generation>0&&(!uuid(value.run_id)||!uuid(value.operator_id)))throw failure('Сервер не подтвердил состояние выбранного аккаунта');
      if(readiness&&(value.native_supported!==true||value.observer_disconnect_stops_run!==false
          ||['configured','worker_ready','start_available'].some(k=>typeof value[k]!=='boolean')
          ||value.start_available&&(!value.configured||!value.worker_ready)))throw failure('Серверный запуск ещё не подтверждён');
      return {...value};
    }
    function accept(value,principal,generation){
      if(generation!==epoch||String(deps.principal()||'')!==principal)return null;
      if(state.view?.principal_id===principal&&value.generation<state.view.generation)throw failure('Получено устаревшее состояние сервера');
      state.view=value;state.stale=false;state.lastConfirmedAt=now();state.error='';
      if(state.unknown?.principal_id===principal&&value.generation>state.unknown.expected_generation)state.unknown=null;
      emit();return value;
    }
    function inspect(){
      if(pending?.epoch===epoch)return pending.promise;
      const entry={epoch,promise:null};
      entry.promise=(async()=>{
        try{
          const principal=await identity();
          if(entry.epoch!==epoch)return null;
          const value=snapshot(await deps.get(base),principal,true);
          return accept(value,principal,entry.epoch);
        }catch(error){
          if(entry.epoch===epoch){state.stale=true;state.error='Связь с сервером не подтверждена. Последнее состояние сохранено';emit()}
          throw error;
        }finally{if(pending===entry)pending=null}
      })();pending=entry;return entry.promise;
    }
    async function prepareStart(){
      if(state.busy||state.unknown)throw failure('Сначала проверьте результат прежней команды');
      const view=await inspect(),operator=String(deps.operator()||'');
      if(!view||state.stale||view.state==='running'||!view.start_available||!uuid(operator))throw failure('Проверьте автора и готовность серверного обработчика');
      prepared=Object.freeze({principal_id:view.principal_id,operator_id:operator,
        expected_generation:view.generation,observed_at:now()});
      return prepared;
    }
    async function start(ticket){
      if(state.busy||state.unknown||ticket!==prepared||!ticket
          ||now()-ticket.observed_at<0||now()-ticket.observed_at>60000
          ||ticket.operator_id!==String(deps.operator()||''))throw failure('Подтверждение устарело. Проверьте запуск заново');
      const generation=epoch;prepared=null;state.busy=true;state.error='';emit();
      try{
        const view=await inspect();
        if(generation!==epoch||!view||state.stale||view.principal_id!==ticket.principal_id
            ||view.generation!==ticket.expected_generation||view.state==='running'||!view.start_available
            ||ticket.operator_id!==String(deps.operator()||''))throw failure('Состояние или автор изменились. Авто не запущено');
        state.unknown={operation:'start',principal_id:ticket.principal_id,expected_generation:ticket.expected_generation};
        const value=snapshot(await deps.post(base+'/start',{expected_principal_id:ticket.principal_id,
          operator_id:ticket.operator_id,expected_generation:ticket.expected_generation}),ticket.principal_id,false);
        if(value.state!=='running'||value.mode!=='auto'||value.operator_id!==ticket.operator_id
            ||value.generation!==ticket.expected_generation+1)throw failure('Исходный запуск пока не подтверждён');
        return accept({...view,...value},ticket.principal_id,generation);
      }catch(error){
        if(generation===epoch){
          if(Number.isInteger(error?.status)&&error.status>=400&&error.status<500)state.unknown=null;
          state.stale=true;state.error=state.unknown?'Результат запуска пока неизвестен. Повтор не отправлялся':error.message;emit();
        }throw error;
      }finally{if(generation===epoch){state.busy=false;emit()}}
    }
    async function stop(){
      if(state.busy||state.unknown?.operation==='stop')throw failure('Результат прежней команды ещё проверяется');
      // Stop exactly the Run the owner saw and selected. A preliminary GET
      // must not silently substitute another tab's later launch. The server
      // rechecks actual principal and generation before the stop transaction.
      const view=state.view;
      if(!view||view.principal_id!==String(deps.principal()||''))throw failure('Не подтверждён аккаунт для остановки');
      if(view.state!=='running'){
        if(state.unknown)throw failure('Прежний запуск пока не подтверждён. Остановка ещё не выполнена');
        return view;
      }
      const generation=epoch;state.busy=true;state.error='';prepared=null;
      state.unknown={operation:'stop',principal_id:view.principal_id,expected_generation:view.generation};emit();
      try{
        const value=snapshot(await deps.post(base+'/stop',{expected_principal_id:view.principal_id,
          expected_generation:view.generation}),view.principal_id,false);
        if(value.state!=='stopped'||value.generation!==view.generation+1)throw failure('Остановка сервера пока не подтверждена');
        return accept({...view,...value},view.principal_id,generation);
      }catch(error){
        if(generation===epoch){
          if(Number.isInteger(error?.status)&&error.status>=400&&error.status<500)state.unknown=null;
          state.stale=true;state.error='Остановка пока не подтверждена. Повтор не отправлялся';emit();
        }throw error;
      }finally{if(generation===epoch){state.busy=false;emit()}}
    }
    function watch(){
      if(watching)return;watching=true;const generation=epoch;
      const tick=async()=>{
        try{await inspect()}catch(_error){/* The last confirmed state remains visibly stale. */}
        if(watching&&generation===epoch)timer=schedule(tick,5000);
      };tick();
    }
    function unwatch(){watching=false;epoch++;prepared=null;state.busy=false;if(timer!==null)clear(timer);timer=null}
    return {state,inspect,prepareStart,start,stop,watch,unwatch};
  };
