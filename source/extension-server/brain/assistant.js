/* Authenticated extension → server policy/facts → budgeted model → server validator.
   No customer-send, Telegram-send or CRM-write capability exists in this module. */
'use strict';
const { ASSISTANT_MODEL_BUDGET_MS, safeProviderError } = require('./ai');
const ASSISTANT_FLOW_MS = 40000, FINALIZE_RESERVE_MS = 6000;

function lowercaseBooleans(raw) {
  // GigaChat can emit Python's True/False in an otherwise JSON object.
  // Change only standalone tokens outside quoted strings. JSON.parse still
  // rejects expressions, comments, unquoted keys, None and all other syntax.
  let text = '', quoted = false, escaped = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (quoted) {
      text += ch;
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') quoted = false;
      continue;
    }
    if (ch === '"') {quoted = true; text += ch; continue;}
    const token = raw.startsWith('True', i) ? 'True' : raw.startsWith('False', i) ? 'False' : '';
    if (token && !/[A-Za-z0-9_$]/.test(raw[i - 1] || '') && !/[A-Za-z0-9_$]/.test(raw[i + token.length] || '')) {
      text += token.toLowerCase(); i += token.length - 1;
    } else text += ch;
  }
  return text;
}

function jsonNormalizationNeeded(text) {
  try {JSON.parse(text); return false;} catch (_e) {return true;}
}

function parseJsonObject(text) {
  try {
    let raw = String(text || '').trim();
    const fenced = raw.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
    if (fenced) raw = fenced[1];
    const value = JSON.parse(lowercaseBooleans(raw));
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch (_e) { return null; }
}

function coherentAssistantCandidate(value, format) {
  const schema = format && format.type === 'json_schema' && format.strict === true && format.schema;
  const review = schema && schema.properties && schema.properties.context_review;
  const typed = review && review.type === 'object' && review.properties
    && review.properties.selected_step_fits && review.properties.selected_step_fits.type === 'boolean'
    && Array.isArray(review.required) && review.required.includes('selected_step_fits')
    && Array.isArray(schema.required) && ['context_review','reply','needs_operator'].every(k=>schema.required.includes(k));
  // Legacy JSON and other structured operations retain their own contracts.
  if (!typed) return true;
  if (!value || typeof value.reply !== 'string' || typeof value.needs_operator !== 'boolean'
      || !value.context_review || typeof value.context_review.selected_step_fits !== 'boolean') return false;
  return value.context_review.selected_step_fits
    ? value.reply.trim().length > 0 && value.needs_operator === false
    : value.reply === '' && value.needs_operator === true;
}

function parseCandidate(text, format) {
  const value = parseJsonObject(text);
  return value && typeof value.reply === 'string' && typeof value.needs_operator === 'boolean'
    && coherentAssistantCandidate(value, format) ? value : null;
}

function createAssistant({ env, запрос, ai, now = Date.now }) {
  const E = env || {};
  async function call(owner, args, timeout = 12000) {
    const url = new URL(E.LEADBOT_ASSISTANT_URL || 'http://127.0.0.1:8788/api/extension/assistant');
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.protocol !== 'http:'
      || url.pathname !== '/api/extension/assistant' || url.username || url.password || url.search)
      throw new Error('Неверный внутренний адрес LeadBot');
    if (!E.LEADBOT_SERVICE_TOKEN) throw new Error('Не настроено соединение мозга с LeadBot');
    // Research observation has its own narrow server contract. Preview and
    // personal-operation metadata must not leak into a durable control call.
    const controlKeys = new Set(['action','ctx','identity_proof','operator_id','browser_session','request_id','revision',
      'research_job_id','audit_cursor','audit_limit']);
    const payload = String(args.action || '').startsWith('research_')
      ? Object.fromEntries(Object.entries(args).filter(([key]) => controlKeys.has(key))) : args;
    const response = await запрос(url.href, { method: 'POST', timeout,
      headers: { 'Content-Type': 'application/json', 'X-Leadbot-Token': E.LEADBOT_SERVICE_TOKEN },
      body: JSON.stringify({ ...payload, owner }) });
    const result = await response.json();
    if (!response.ok && result.ok !== false) throw new Error('LeadBot: HTTP ' + response.status);
    return result;
  }
  const assistant = async function assistant(args, owner, mode) {
    const deadline = now() + ASSISTANT_FLOW_MS;
    const remaining = () => {
      const ms = deadline - now();
      if (ms <= 0) throw new Error('Истёк срок проверки помощника');
      return ms;
    };
    const a = args && typeof args === 'object' && !Array.isArray(args) ? args : {};
    if (E.LEADBOT_PERSONAL_OWNER_ID && owner !== E.LEADBOT_PERSONAL_OWNER_ID && a.action !== 'checklist')
      return {ok:false,code:'personal_owner',auto_enabled:false,error:'Помощник доступен только владельцу личного токена'};
    const allowed = new Set(['status', 'preview', 'form_preview', 'checklist', 'observe', 'validate', 'takeover', 'resume',
      'research_start','research_status','research_cancel','research_finalize','research_audit',
      'personal_identity_challenge','personal_start','personal_stop','personal_status','personal_heartbeat','personal_mode','screen',
      'personal_plan','personal_crm_check','personal_call_confirm','personal_authorize','personal_review_authorize','personal_check_started','personal_audit','personal_event','personal_media_review']);
    if (!allowed.has(a.action || 'status')) return { ok: false, code: 'auto_disabled', auto_enabled: false,
      error: 'Автоматические отправки выключены' };
    // Never accept an owner, model prompt or completion supplied by a content script.
    const safe = { action: a.action || 'status', ctx: a.ctx, draft_id: a.draft_id, request_id: a.request_id,
      browser_session:a.browser_session,operator_id:a.operator_id,max_dialogs:a.max_dialogs,mine_count:a.mine_count,
      wording_mode:a.wording_mode,identity_proof:a.identity_proof,
      proposal:a.proposal,confirmed:a.confirmed,revision:a.revision,operation:a.operation,
      audit_event:a.audit_event,audit_before:a.audit_before,audit_event_id:a.audit_event_id,
      message_id:a.message_id,media_signature:a.media_signature,observations:a.observations,
      research_job_id:a.research_job_id,audit_cursor:a.audit_cursor,audit_limit:a.audit_limit,
      execution_mode:a.execution_mode,activation_nonce:a.activation_nonce,policy_ack:a.policy_ack,client_version:a.client_version,
      expected_mode_epoch:a.expected_mode_epoch,
      control_protocol:a.control_protocol,connection_epoch:a.connection_epoch,control_seq:a.control_seq,
      stop_reason:typeof a.stop_reason==='string'?a.stop_reason:undefined };
    if (['preview','form_preview'].includes(safe.action) && E.LEADBOT_RESEARCH_PROFILE && mode!=='rules' && safe.wording_mode!=='neural_auto')
      safe.wording_mode='neural_review';
    if (['preview','form_preview'].includes(safe.action) && E.LEADBOT_RESEARCH_PROFILE && mode!=='rules')
      safe._trusted_research_profile=E.LEADBOT_RESEARCH_PROFILE;
    const prepared = await call(owner, safe, Math.min(12000, remaining()));
    remaining();
    if (['preview','form_preview'].includes(safe.action) && E.LEADBOT_RESEARCH_PROFILE && mode !== 'rules'
        && (prepared.pending_model || ['pending','interrupted'].includes(prepared.code))) {
      if (!['sol_only','sol_astra'].includes(E.LEADBOT_RESEARCH_PROFILE))
        return {ok:false,code:'research_configuration',reply:'',auto_enabled:false,error:'Не подтверждён профиль исследовательского контура'};
      // Source/transport configuration and a finite admission live on the
      // trusted Python server. Never fall back to Giga after research fails.
      const research = await call(owner,{...safe,action:'research_start',request_id:prepared.request_id,
        revision:prepared.revision},Math.min(12000,remaining()));
      if (research.research_state==='accepted')
        return call(owner,{...safe,action:'research_finalize',request_id:prepared.request_id,
          revision:prepared.revision,research_job_id:research.research_job_id},Math.min(12000,remaining()));
      return research;
    }
    if (!prepared.pending_model) return prepared;
    const task = prepared.model_task;
    if (!task || typeof task.system !== 'string' || typeof task.task !== 'string')
      throw new Error('LeadBot не подготовил контекст');
    let candidate = null, model = '', cached = false, rub = 0, failure = '', normalized = false, modelError=null;
    if (mode !== 'rules') {
      try {
        const modelBudget = Math.min(ASSISTANT_MODEL_BUDGET_MS, remaining() - FINALIZE_RESERVE_MS);
        if (modelBudget < 1500) throw new Error('Не осталось времени на нейронную проверку');
        const result = await ai.спросить('assistant', task.system, task.task,
          { режим: mode, maxTokens: Math.min(1200, task.max_tokens || 350), срок: modelBudget,
            ...(task.response_format ? {responseFormat:task.response_format} : {}),
            singleAttempt: true, годен: (text) => !!parseCandidate(text, task.response_format) });
        remaining();
        candidate = parseCandidate(result.text, task.response_format); if (!candidate) failure = 'format'; model = result.model || '';
        normalized = !!candidate && jsonNormalizationNeeded(result.text);
        if (safe.wording_mode === 'neural_auto' && normalized) { candidate = null; failure = 'format'; }
        cached = !!result.cached; rub = Number(result.rub) || 0;
      } catch (e) { failure = e && e.неПоФорме ? 'format' : 'transport'; modelError=safeProviderError(e && e.providerError); /* No retry. */ }
    }
    const result = await call(owner, { action: 'finalize', request_id: prepared.request_id,
      revision: prepared.revision, candidate: candidate || {}, model_failure: failure,
      ...(modelError ? {model_error:modelError} : {}) }, Math.min(12000, remaining()));
    remaining();
    return { ...result, model, model_cached: cached, model_rub: rub, model_json_normalized: normalized, auto_enabled: false };
  };
  assistant.geography = (args) => call('territory-registry', { action: 'geography', ...args }, 2000);
  return assistant;
}

module.exports = { createAssistant, parseCandidate, coherentAssistantCandidate, parseJsonObject, jsonNormalizationNeeded, ASSISTANT_FLOW_MS };
