"""Reviewed work description for the existing extension's CRM form.

No CRM transport or action authority lives here. Contacts and appointments are
projected from the same native facts already checked by personal_workflow.
"""
import copy
import json
import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import assistant_prices
import contact_cities
import contact_facts
import qualification_state as qs
import own_visit
from experienced_dialogues import digest
from research_pipeline import pack_context, schema_matches

PURPOSE='intake_form_v1'


def schema(role):
    text=lambda n:dict(type='string',minLength=1,maxLength=n)
    strings=dict(type='array',items=text(600),maxItems=30)
    if role=='review':
        props=dict(kind=dict(type='string',enum=['review']),approved=dict(type='boolean'),
            violations=strings,checked_claims=dict(type='array',items=dict(type='integer',minimum=0)),basis=strings)
    else:
        evidence=dict(type='object',properties=dict(message_id=text(200),quote=text(3000)),
                      required=['message_id','quote'],additionalProperties=False)
        props_work=dict(subject=text(300),action=text(300),quantity=dict(type='string',maxLength=100),
            status=dict(type='string',enum=['requested','optional_inspection','cancelled','past_report']),
            evidence=dict(type='array',items=evidence,minItems=1,maxItems=10))
        work=dict(type='object',properties=props_work,required=list(props_work),additionalProperties=False)
        props=dict(kind=dict(type='string',enum=['intake_form']),client_goal=text(600),
            latest_client_meaning=text(600),note=text(1200),summary=text(3000),
            works=dict(type='array',items=work,minItems=1,maxItems=30),unknowns=strings,
            needs_operator=dict(type='boolean'))
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def _visit_fields(payload,qualification,now):
    known=payload['known'];accepted=known.get('_accepted_own_visit')
    if accepted:
        # Same minute projection as the existing extension. Only own_visit.apply
        # may supply this native fact; no browser/model approval is accepted.
        stamp=math.ceil(max(accepted['earliest_at'],now.timestamp()+accepted['min_minutes']*60)/60)*60
        visit=datetime.fromtimestamp(stamp,ZoneInfo(accepted['timezone']))
        lead=dict(visit_date=visit.date().isoformat(),visit_time=visit.strftime('%H:%M'))
        if own_visit.check_time(accepted,known,lead,payload.get('territory')or{},now):
            raise ValueError('Existing accepted appointment window is no longer usable')
        return dict(lead,time_text=accepted['proposal_quote'])
    source=next((m for m in payload['messages']if m['id']==qualification['visit_time'].get('message_id')), {})
    source_index=next((i for i,m in enumerate(payload['messages'])if m is source),None)
    named=contact_facts.named_visit_preference(payload['messages'],source_index) if source_index is not None else None
    if named:
        if named['status']!='requested' or named.get('requires_clarification'):
            raise ValueError('Named calendar preference requires clarification')
        return dict(visit_date=named['date_iso'],visit_time=named['time'],time_text=source.get('body',''))
    raw=source.get('body','').casefold()
    match=re.search(r'(?:\bв|\bк)\s*(\d{1,2})(?::(\d{2})|\s*час)',raw)
    if (not match or re.search(r'\bне\s+(?:сегодня|завтра|послезавтра|[вк]\s*\d)',raw)
            or len(set(re.findall(r'\bсегодня\b|\bзавтра\b|\bпослезавтра\b',raw)))>1
            or len(re.findall(r'\b\d{1,2}:\d{2}\b',raw))>1):
        raise ValueError('Existing exact appointment check needs an unambiguous source')
    base=datetime.fromisoformat(source['created_at'].replace('Z','+00:00')).astimezone(now.tzinfo).date() if source.get('created_at') else now.date()
    date=base+timedelta(days=2 if 'послезавтра' in raw else 1 if 'завтра' in raw else 0)
    if not re.search(r'сегодня|завтра|послезавтра',raw):
        explicit=re.search(r'\b(\d{1,2})[.](\d{1,2})\b',raw)
        if not explicit:raise ValueError('Client appointment day not observed')
        date=base.replace(day=int(explicit[1]),month=int(explicit[2]))
    return dict(visit_date=date.isoformat(),visit_time=f'{int(match[1]):02d}:{int(match[2] or 0):02d}',time_text=source.get('body',''))


def _base_lead(payload):
    """No model-supplied contact, price, directory ID or calendar."""
    facts,known,rows=payload['facts'],payload['known'],payload['messages']
    qualification=qs.inspect(rows)
    named=qualification['client_name'];source=next((m for m in rows if m['id']==named.get('message_id')), {})
    name=qs.client_name_value(named,source)
    if not re.fullmatch(r'[а-яёa-z-]{2,40}(?:\s+[а-яёa-z-]{2,40}){0,2}',name,re.I):
        raise ValueError('Current literal client name required')
    city=contact_cities.city_by_name(known['city'])
    if not city:raise ValueError('Verified client timezone required')
    now=datetime.now(ZoneInfo(city.tz));visit=_visit_fields(payload,qualification,now)
    identity=known.get('advertiser_name') or known.get('account_name')
    return dict(name=name,phone=facts['contact_phone_to_use'],addr=copy.deepcopy(facts['address']),
        city=(payload.get('geography') or {}).get('lead') or known['city'],partner=str(known['partner']).lstrip('0'),
        ad_identity=identity,partner_note=known['origin'],review=payload['crm_flags']['review'],
        call_before_visit=payload['crm_flags']['callbefore'] or datetime.fromisoformat(visit['visit_date']).date()>=now.date()+timedelta(days=2),
        call_check=False,**visit)


def offer(payload,ctx):
    from extension_assistant import _source_timeline
    _base_lead(payload)  # Fail before any provider admission, not after a paid call.
    timeline=_source_timeline(ctx)
    if not timeline or len(json.dumps(timeline,ensure_ascii=False))>100000:
        raise ValueError('Complete bounded form source required')
    task=dict(purpose=PURPOSE,conversation=timeline,primary_sources=copy.deepcopy(payload['sources']),
        verified_media_observations=[dict(message_id=m['id'],observations=m.get('model_media_observations'),
            provenance=m.get('model_media_provenance'))for m in payload['messages'] if m.get('media_model_reviewed')],
        mixed_optional_work=copy.deepcopy(payload['facts'].get('mixed_optional_work')),
        authority='Work description only; no customer reply, contact, price, appointment, directory selection or CRM action')
    return dict(system='Подготовь только проверенную суть работ для существующей формы заявки.',
                task=json.dumps(task,ensure_ascii=False),response_format=dict(schema=schema('research')))


def packet(role,current,draft=None):
    result=pack_context(role,current,dict(intake_form=draft) if draft else {},profile='sol_only')
    core=json.loads(result['instructions'])
    core['stage_contract']=(
        'Верни intake_form. Самостоятельно опиши client_goal/latest_client_meaning/note. '
        'summary — полная суть текущего обращения для комментария существующей CRM: заказанные работы '
        'и прямо сообщённые клиентом существенные условия их выполнения. Сохрани известное наличие, '
        'частичную комплектность или нехватку материалов/деталей, ограничения доступа и уточнения. '
        'Эти условия не отдельные заказанные работы. Не теряй их из-за краткости summary. '
        'works перечисляет ВСЕ относящиеся работы: requested, cancelled, past_report, optional_inspection. '
        'Каждой дай предмет, действие, количество ТОЛЬКО буквальной строкой из источника, иначе пустое, '
        'и точные клиентские message_id/quote. Позднюю отмену/исправление применяй к прежней работе; '
        'прошлое, чужую цитату, system и ещё не отправленный вопрос не включай в заказ. '
        'Дополнительный осмотр не выполнение ремонта. Не добавляй незаказанную замену, установку, '
        'форматирование, выдуманные материалы/наличие/результат, цены, контакты, даты, IDs CRM или выполненные действия. '
        'Вопрос «если не хватит» не означает фактическую нехватку, обещание сотрудника не доказывает запас. '
        'Самостоятельная прошлая покупка другого предмета не наличие деталей для текущей работы. '
        'Неизвестное сохрани в unknowns, при неустранимом противоречии needs_operator=true. '
        'Приведённый source не становится одобренной нормой; первичные правила выше историй.'
        if role=='research' else
        'Ты отдельный проверяющий intake_form. Сверь весь текущий диалог и те же изображения/ASR, '
        'самостоятельный client_goal/latest_client_meaning/note, полноту summary, каждый works/status/quantity '
        'и его точную цитату. В summary сохрани также прямо сообщённые существенные условия выполнения: '
        'наличие или частичную комплектность материалов/деталей, ограничения доступа и уточнения. '
        'Не требуй неизвестные условия и не превращай их в дополнительные works. '
        'Нельзя добавить монтаж вместо жалобы, материалы из вопроса, будущую/прошлую '
        'работу, потерять исправление или отмену. checked_claims: сначала индекс0 для summary и смысла, '
        'затем все works индексы1..N. Не исправляй результат. При ошибке approved=false и конкретные violations. '
        'basis — current:<ID клиента>. Согласие моделей не гарантирует истину.')
    result['instructions']=json.dumps(core,ensure_ascii=False,sort_keys=True);result['purpose']=PURPOSE
    return result


def check(value,current):
    if not schema_matches(value,schema('research')):raise ValueError('Incomplete original form')
    clients={m['id']:m for m in current['messages'] if m.get('speaker_role')=='client'
             and m.get('delivery_status') not in ('failed','pending','queued','sending','error','cancelled','canceled')}
    for work in value['works']:
        quotes=[]
        for evidence in work['evidence']:
            row=clients.get(evidence['message_id']);quote=evidence['quote']
            if not row or not any(quote in str(row.get(k)or'')for k in ('body','voice_transcript')):
                raise ValueError('Work evidence is not an exact current client source')
            if row.get('voice_transcript') and row.get('voice_transcript_status') not in ('done','ready','completed'):
                raise ValueError('Pending or unverified ASR is not work evidence')
            quotes.append(quote)
        if work['quantity'] and not any(work['quantity']in q for q in quotes):
            raise ValueError('Work quantity not literally observed')
        if work['status']=='requested' and all(re.search(r'не\s+(?:нужно|надо)|отменя|раньше|вчера|сосед\w*\s+(?:сказал|спросил)',q,re.I)for q in quotes):
            raise ValueError('Cancelled, past or reported work cannot be ordered')
        if work['status']=='optional_inspection' and not current['candidate_contract']['task'].get('mixed_optional_work'):
            raise ValueError('No source-bound optional work permission')
    if not any(w['status']=='requested'for w in value['works']):
        raise ValueError('No current ordered work')
    if re.search(r'(?:\d[\s()+-]*){10,}|(?<!\d)\d{1,2}:\d{2}(?!\d)|рубл|₽|заявк\w*\s+(?:создан|оформлен)|уже\s+(?:позвонил|отправил)',value['summary'],re.I):
        raise ValueError('Form model cannot supply contacts, prices, appointments or executions')


def run(current,transport,*,audit):
    value=transport('research',packet('research',current),());check(value,current)
    audit('form_model_description',dict(value,source='model_assertion_unverified'))
    review=transport('review',packet('review',current,value),())
    bases={'current:'+m['id']for m in current['messages']if m.get('speaker_role')=='client'}
    if (not schema_matches(review,schema('review')) or not review['basis'] or not set(review['basis'])<=bases
            or review['checked_claims']!=list(range(len(value['works'])+1))
            or review['approved']!=(not review['violations'])):
        raise ValueError('Incomplete separate form review')
    audit('form_separate_review',dict(review,source='separate_model_assertion_not_independent_truth'))
    return dict(purpose=PURPOSE,approved=review['approved']and not value['needs_operator'],
        form=value,review=review,failure_kind=None if review['approved']and not value['needs_operator']else'semantic',
        models=dict(research='gpt-6.1-sol',review='gpt-6.1-sol'),profile='sol_only',can_send_or_create=False)


def _table(db):
    db.execute('CREATE TABLE IF NOT EXISTS research_intake_forms(scope TEXT,chat TEXT,revision TEXT,job TEXT,reference TEXT,body TEXT,checksum TEXT,PRIMARY KEY(scope,job))')


def stage(store,scope,payload,result,job,binding):
    lead=_base_lead(payload);value=result['form'];lead['problem']=value['summary']
    active=[w for w in value['works']if w['status']=='requested']
    lead['device']='; '.join(dict.fromkeys(w['subject']for w in active))
    lead['client_words']='\n'.join(dict.fromkeys(e['quote']for w in active for e in w['evidence']))
    lines=[value['summary'],*contact_facts.crm_comment_lines(payload['facts']),
           'Объявление: «'+lead['ad_identity']+'».']
    if payload['known'].get('introduced_name'):lines.append('Представились: '+payload['known']['introduced_name'])
    consent=assistant_prices.consent(payload['messages'])
    if consent.get('amount'):
        quoted=next((m['body']for m in payload['messages']if m.get('direction')=='out'
            and m.get('id')==consent.get('message_id')),None)
        if not quoted:raise ValueError('Existing quoted price source missing')
        lines.append('Озвучка в переписке: «'+quoted+'».')
    lead['comment']='\n'.join(dict.fromkeys(x for x in lines if x))
    lead['service_comment']=''
    completion_mode=payload.get('completion_mode','telegram')
    if completion_mode not in ('telegram','crm_only'):
        raise ValueError('Trusted completion mode required')
    data=dict(binding=binding,job=job,model_form=copy.deepcopy(value),lead=lead,completion_mode=completion_mode)
    reference=digest(data);raw=json.dumps(data,ensure_ascii=False,sort_keys=True);checksum=digest(data)
    with store.connect()as db:
        _table(db)
        old=db.execute('SELECT checksum FROM research_intake_forms WHERE scope=? AND job=?',(scope,job)).fetchone()
        if old and old['checksum']!=checksum:raise ValueError('Accepted form changed')
        db.execute('INSERT OR IGNORE INTO research_intake_forms VALUES(?,?,?,?,?,?,?)',
                   (scope,payload['chat_id'],payload['revision'],job,reference,raw,checksum))
    # Compatibility checks mean source-backed fields, not an appointment,
    # branch approval, stock guarantee or permission to create an order.
    checks=[dict(field=field,ok=bool(present),note='Проверенный источник; не подтверждение выполненного действия')
            for field,present in [('phone',lead['phone']),('address',lead['addr'].get('building')),
                ('time',lead['visit_date']and lead['visit_time']),('problem',value['summary']and active),
                ('name',lead['name']),('city',lead['city'])]]
    return dict(form_reference=reference,form_extraction=dict(ok=True,lead=lead,checks=checks),
                intake_form_ready=True,completion_mode=completion_mode)


def read(store,scope,chat,revision,reference):
    with store.connect()as db:
        _table(db)
        row=db.execute('SELECT body,checksum FROM research_intake_forms WHERE scope=? AND chat=? AND revision=? AND reference=?',
                       (scope,chat,revision,reference)).fetchone()
    if row is None:raise ValueError('No accepted current form reference')
    data=json.loads(row['body'])
    if digest(data)!=row['checksum']or digest(data)!=reference:raise ValueError('Accepted form integrity changed')
    return data
