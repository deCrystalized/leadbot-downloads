'use strict';
// Installed compiled extension adapter + actual Python policy. Synthetic drafts only.
const fs = require('fs'), cp = require('child_process'), crypto = require('crypto'), path = require('path');
const pid = cp.execFileSync('systemctl', ['show', '-p', 'MainPID', '--value', 'lc-brain'], {encoding:'utf8'}).trim();
const env = Object.fromEntries(fs.readFileSync('/proc/' + pid + '/environ', 'utf8').split('\0').filter(Boolean)
  .map(x => [x.slice(0,x.indexOf('=')), x.slice(x.indexOf('=')+1)]));
if (!env.LEADBOT_PERSONAL_OWNER_ID) throw Error('Missing owner binding');
// This shadow instance checks reviewed price/form rules with synthetic CIDs,
// not authenticated research. The production process keeps its API profile;
// its factory is in explicit maintenance during installed rule acceptance.
const productionResearchProfile = env.LEADBOT_RESEARCH_PROFILE || '';
if (productionResearchProfile && productionResearchProfile !== 'sol_only') throw Error('Unexpected research profile');
delete env.LEADBOT_RESEARCH_PROFILE;
const token = 'synthetic-diagnostic-scope117-token';
const memory = new Map([['brain/tokens.json', {tokens:[{id:env.LEADBOT_PERSONAL_OWNER_ID,
  sha:crypto.createHash('sha256').update(token).digest('hex'), label:'synthetic-diagnostic-test'}]}]]);
const store = {get:async(k,d)=>structuredClone(memory.has(k)?memory.get(k):d),
  put:async(k,v)=>memory.set(k,structuredClone(v))};
const compiled = require('/opt/lead-centre/brain/dist/index.js');
const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../test-artifacts/deploy-manifest.json'),'utf8'));
if (compiled.ВЕРСИЯ !== manifest.brain_version) throw Error('Brain version mismatch');
const handler = compiled.создать({env, store, log:()=>{}, sleep:async()=>{}});
const rule = 'OWNER-KP-PARTNER-DIAGNOSTIC-20261020';
async function request(op,args) {
  const r = await handler({httpMethod:'POST',headers:{'x-brain-auth':token},body:JSON.stringify({op,args}),
    requestContext:{identity:{sourceIp:'127.0.0.1'}}});
  const b = JSON.parse(r.body);
  if (r.statusCode !== 200 || !b.ok || b.auto_enabled !== false || b.policy_version !== manifest.policy_version)
    throw Error('Compiled policy response mismatch: ' + op);
  if (b.pending_model) throw Error('Unexpected model call');
  return b;
}
(async()=>{
  const checks=[];
  for (const partner of ['7','723','748','340']) for (const dir of ['kp','bt','mnc']) {
    const titles={kp:'Ремонт принтеров',bt:'Ремонт холодильников',mnc:'Услуги электрика'};
    const jobs={kp:'Принтер не печатает.',bt:'Холодильник не морозит.',mnc:'Нужно заменить розетку.'};
    const ctx={convId:'synthetic-compiled-fee117-'+dir+'-'+partner,city:'Оренбург',dir,partner,channel:'avito',
      accountTitle:'Учебный мастер',itemTitle:titles[dir],origin:'С1',
      messages:[{id:'client',direction:'in',sender_type:'client',body:jobs[dir]+' Сколько стоит диагностика?'}]};
    const out=await request('assistant',{action:'preview',wording_mode:'reviewed',ctx});
    const whiteBt=dir==='bt'&&partner==='723';
    if (whiteBt) {
      if (out.action!=='handoff'||out.reply||!out.rule_ids.includes('TGAVITO-16610')) throw Error('White BT guard bypass');
    } else if (!out.reply || !out.rule_ids.includes(dir==='mnc'?'OWNER-MNC-FREE-CALLOUT-20261021':dir==='bt'?'OWNER-BT-800-20261027':rule) ||
        (dir==='mnc' ? !out.reply.includes('Выезд в черте города бесплатный.')||/500|800|1000/.test(out.reply)
          : dir==='kp' ? !out.reply.includes('1000 рублей') : out.reply.includes('1000')||out.reply.includes('500')||!out.reply.includes('без разбора техники — 800 рублей')||!out.reply.includes('с разбором — от 800 рублей')))
      throw Error('Wrong direction fee: '+dir+'/'+partner);
    checks.push({case:dir+'/'+partner,operation:'preview',passed:true});
    const quote=dir==='mnc'?'Выезд в черте города бесплатный.':dir==='kp'?'Выезд и диагностика бесплатны при выполнении работ. При отказе от работ стоимость составит 1000 рублей.':
      'Первичная диагностика без разбора техники — 800 рублей. Техническая диагностика с разбором — от 800 рублей. При продолжении работ диагностика бесплатная.';
    const form=await request('checklist',{dir,ctx:{...ctx,convId:ctx.convId+'-form',messages:[...ctx.messages,
      {id:'quote',direction:'out',sender_type:'operator',body:quote},{id:'accept',direction:'in',body:'Да, устраивает'}]}});
    const terms=form.results.find(r=>r.key==='partner_visit_terms');
    if (dir==='kp' ? !terms?.done : terms!==undefined) throw Error('Wrong form fee requirement: '+dir+'/'+partner);
    const feeConsent=form.results.find(r=>r.key==='price_consent');
    if (dir==='mnc' ? feeConsent && !feeConsent.done : !feeConsent?.done)
      throw Error('Correct fee not verified: '+dir+'/'+partner);
    checks.push({case:dir+'/'+partner,operation:'normal_form',passed:true});
  }
  const onlyRule='OWNER-DIAGNOSTIC-ONLY-MIN-20261020';
  for (const partner of ['7','723','748','340']) for (const dir of ['kp','bt','mnc']) {
    const jobs={kp:'Принтер не печатает.',bt:'Холодильник не морозит.',mnc:'Течёт смеситель.'};
    const titles={kp:'Ремонт принтеров',bt:'Ремонт холодильников',mnc:'Услуги сантехника'};
    const ctx={convId:'synthetic-compiled-only120-'+dir+'-'+partner,city:'Оренбург',dir,partner,channel:'avito',
      accountTitle:'Учебный мастер',itemTitle:titles[dir],origin:'С1',messages:[{id:'client',direction:'in',sender_type:'client',
        body:jobs[dir]+' Нужна только диагностика, без ремонта. Сколько стоит?'}]};
    const out=await request('assistant',{action:'preview',wording_mode:'reviewed',ctx});
    if (dir==='bt'&&partner==='723') {
      if(out.action!=='handoff'||out.reply||!out.rule_ids.includes('TGAVITO-16610')) throw Error('White BT only guard bypass');
    } else if(dir==='mnc' ? !out.reply.includes('Выезд в черте города бесплатный.')||/500|800|1000/.test(out.reply)||!out.rule_ids.includes('OWNER-MNC-FREE-CALLOUT-20261021')
        : dir==='bt' ? out.reply.includes('500')||!out.reply.includes('без разбора техники — 800 рублей')||!out.reply.includes('с разбором — от 800 рублей')||!out.rule_ids.includes('OWNER-BT-800-20261027') : !out.reply.includes('от 500 рублей')||out.reply.includes('1000')||!out.rule_ids.includes(onlyRule))
      throw Error('Wrong diagnostic-only minimum: '+dir+'/'+partner);
    checks.push({case:dir+'/'+partner,operation:'diagnostic_only_preview',passed:true});
    const form=await request('checklist',{dir,ctx:{...ctx,convId:ctx.convId+'-form',messages:[...ctx.messages,
      {id:'quote',direction:'out',sender_type:'operator',body:dir==='mnc'?'Выезд в черте города бесплатный.':dir==='bt'?'Первичная диагностика без разбора техники — 800 рублей. Техническая диагностика с разбором — от 800 рублей. При продолжении работ диагностика бесплатная.':'Диагностика без ремонта — от 500 рублей.'},
      {id:'accept',direction:'in',body:'Да, устраивает'}]}});
    const onlyConsent=form.results.find(r=>r.key==='price_consent');
    if(form.results.some(r=>r.key==='partner_visit_terms')||(dir==='mnc' ? onlyConsent && !onlyConsent.done : !onlyConsent?.done))
      throw Error('Diagnostic-only form differs: '+dir+'/'+partner);
    checks.push({case:dir+'/'+partner,operation:'diagnostic_only_normal_form',passed:true});
  }
  console.log(JSON.stringify({policy:manifest.policy_version,brain:compiled.ВЕРСИЯ,compiled_adapter_checks:checks,
    acceptance_scope:'isolated_reviewed_price_and_form_rules_not_API_quality',production_research_profile:productionResearchProfile,
    customer_sends:0,crm_writes:0,actual_model_calls:0,auto_enabled:false}));
})().catch(error=>{ console.error('Installed diagnostic scope verification failed: '+String(error.message).slice(0,300)); process.exit(1); });
