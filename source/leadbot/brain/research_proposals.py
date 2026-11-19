"""Bound a researched wording proposal to an existing, guarded intake decision.

Selected clarification and a source-bound answer to the current supply question
are distinct goals. Exact source-dependent disclosures remain exact. Neither
goal grants permission to skip later qualification or perform an operation.
"""
import copy
import json
import re

from experienced_dialogues import digest


VERSION = 'source_bound_goals219'


def independent_review_task(task):
    """A source observation is a hint, not a model's mandatory paraphrase.

    Only the opt-in, separately reviewed research path uses this task. Source
    roles, exact evidence, conditional checks and the native legacy contract
    remain available and unchanged outside that path.
    """
    result=copy.deepcopy(task)
    output=result.get('output_contract',{})
    observed=output.pop('fixed_latest_client_meaning',None)
    if observed:
        output['server_latest_client_observation']=dict(text=observed,
            source='server_derived_observation_not_independent_model_meaning',
            mandatory_copy=False)
    return result


def _free_latest_meaning(schema):
    if isinstance(schema,dict):
        props=schema.get('properties',{})
        if isinstance(props.get('latest_client_meaning'),dict):
            props['latest_client_meaning'].pop('enum',None)
        for value in schema.values():_free_latest_meaning(value)
    elif isinstance(schema,list):
        for value in schema:_free_latest_meaning(value)


def answer_only_reply(payload):
    """A bounded current uncertainty question can precede qualification."""
    import assistant_policy as policy
    decision = payload.get('decision_internal') or {}
    if (payload.get('semantic_fixed_reply') or payload.get('action') != 'draft'
            or decision.get('action') != 'draft' or decision.get('approved_price_reply')
            or not (decision.get('next_question') or {}).get('question')):
        return None
    observed = policy.service_expectation_questions(payload.get('messages') or [])
    disclosures = ['По материалам смогу сориентировать после осмотра.'] if (
        (decision.get('next_question') or {}).get('kind') == 'materials') else []
    if policy.office_data_preservation_question(payload.get('messages') or []):
        disclosures.append(policy.DATA_PRESERVATION_REPLY)
    if not any(text in decision.get('required_text', []) and text in observed for text in disclosures):
        return None
    task = json.loads(payload['model_task']['task'])
    if 'OWNER-NO-PARTS-OR-ONSITE-GUARANTEE-20261020' not in {s['id'] for s in task['primary_sources']}:
        return None
    # All mandatory disclosures survive, including any optional-work caveat.
    return policy.compose_reply(' '.join(decision['required_text']), decision).strip()


def validation_decision(reply, payload):
    """Only the exact admitted answer defers the selected next question."""
    decision = payload['decision_internal']
    allowed = answer_only_reply(payload)
    if allowed and reply == allowed:
        result = copy.deepcopy(decision)
        result['deferred_qualification_question'] = result.pop('next_question')
        return result
    return decision


def build(payload, *, price_wording_enabled=False):
    if type(price_wording_enabled) is not bool:
        raise ValueError('Trusted boolean price wording capability required')
    try:
        native = payload['model_task']
        task = json.loads(native['task'])
        schema = native['response_format']['schema']
        decision = payload['decision_internal']
        question = decision.get('next_question') or {}
        fixed = payload.get('semantic_fixed_reply')
        if (not payload['request_id'] or not payload['revision']
                or not isinstance(task, dict) or task.get('context_review_version') != 2
                or not isinstance(task.get('conversation'), list) or not task['conversation']
                or not isinstance(schema, dict) or 'context_review' not in schema.get('properties', {})
                or not isinstance(task.get('primary_sources'), list) or not task['primary_sources']
                or not isinstance(native['system'], str) or not native['system'].strip()
                or not isinstance(decision, dict)):
            raise ValueError('Complete original guarded proposal context required')
        import research_price_wording
        price_frame = research_price_wording.bound_frame(payload) if price_wording_enabled else None
        if (fixed and price_frame and payload['action'] == decision['action'] == 'question'
                and set(price_frame['rule_ids']) <= {s['id'] for s in task['primary_sources']}):
            mode = 'source_bound_price'
        elif fixed:
            mode = 'exact_existing_reply'
        elif (payload['action'] == decision['action'] == 'draft'
              and isinstance(question, dict) and isinstance(question.get('question'), str)
              and question['question'].strip() and not decision.get('approved_price_reply')):
            mode = 'selected_clarification'
        else:
            raise ValueError('This decision has no admitted wording proposal path')
        # Identity/profile are separately bound by Jobs. Do not bind mutable
        # status/UI metadata written by research_start to this semantic plan.
        bound = {key: payload.get(key) for key in (
            'request_id', 'revision', 'chat_id', 'generation', 'policy_version',
            'experience_binding', 'decision_internal', 'facts', 'known', 'messages',
            'model_task', 'semantic_fixed_reply', 'action')}
        bound['price_wording_enabled'] = price_wording_enabled
        goals = [mode]
        answer = answer_only_reply(payload) if mode == 'selected_clarification' else None
        if answer:
            goals.append('answer_current_question')
        return dict(version=VERSION, binding=digest(bound), mode=mode, allowed_goals=goals,
            answer_current_question=answer,
            price_frame=price_frame if mode == 'source_bound_price' else None,
            action_authority='none', selected_question=copy.deepcopy(question),
            required_text=copy.deepcopy(decision.get('required_text', [])),
            exact_reply=(fixed or '') if mode == 'exact_existing_reply' else '',
            source_ids=[s['id'] for s in task['primary_sources']],
            protected=('Не меняй выбранный вопрос, работы, роли, цену/единицы/этап, адрес, '
                       'ЛПР, маршрут, согласования или состояние заявки. Не обещай наличие, '
                       'результат, звонок, срок или выполненное действие. Истории — примеры, '
                       'не факты нынешнего клиента и не действующий регламент.'))
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid original proposal input') from exc


def verify(payload, plan, *, price_wording_enabled=False):
    if not isinstance(plan, dict) or plan != build(payload, price_wording_enabled=price_wording_enabled):
        raise ValueError('Proposal no longer matches the original guarded input')
    return plan['mode'] in ('selected_clarification', 'source_bound_price')


def contract(payload, *, price_wording_enabled=False):
    plan = build(payload, price_wording_enabled=price_wording_enabled)
    native = payload['model_task']
    task = independent_review_task(json.loads(native['task']))
    task.pop('conversation')  # The complete original timeline travels once.
    task['proposal_plan'] = plan
    schema = copy.deepcopy(native['response_format']['schema'])
    _free_latest_meaning(schema)
    system = native['system']
    system += ('\nСвободные last_intent/latest_client_meaning/note сформулируй самостоятельно. '
               'server_latest_client_observation — производная подсказка сервера, не твой вывод '
               'и не обязательный текст. Сверь её с ролями, доставкой и исходными сообщениями. '
               'Не превращай планируемый вопрос сервиса в цель клиента и не выдавай '
               'передачу контакта за согласие с ценой, звонок, визит или созданную заявку.')
    if plan['mode'] == 'selected_clarification':
        import assistant_policy as policy
        # Only reply wording expands. Every conditional review, free meaning,
        # evidence constraint, coherent veto and selected question is retained.
        schema['properties']['reply'].pop('enum', None)
        for branch in schema.get('anyOf', []):
            props = branch.get('properties', {})
            # Keep the empty veto branch exactly as before; the positive
            # branch also contains a copy of the old reply enum.
            if props.get('needs_operator', {}).get('enum') == [False]:
                props.get('reply', {}).pop('enum', None)
        task['reply_field_scope'] = 'whole_reply_preserve_selected_question_and_disclosures'
        example = policy.compose_reply(plan['selected_question']['question'], payload['decision_internal'])
        if isinstance(task['output_contract'].get('example'), dict):
            task['output_contract']['example']['reply'] = example
        for state in task['output_contract'].get('decision_states', []):
            if state.get('needs_operator') is False:
                state['reply'] = example
        if plan['answer_current_question']:
            positive = next(s for s in task['output_contract']['decision_states'] if s.get('needs_operator') is False)
            alternative = copy.deepcopy(positive)
            alternative['reply'] = plan['answer_current_question']
            task['output_contract']['decision_states'].append(alternative)
        task['output_contract']['decision_states_scope'] = task['output_contract'].get('decision_states_scope', '') + (
            ' Положительный reply — пример полного текста, не требование дословного '
            'копирования. Смысл выбранного вопроса и обязательные раскрытия сохраняются.')
        for old, new in (
            ('Обязательное приветствие в первом ответе добавляет сервер. Сам приветствие не добавляй.',
             'Обязательное приветствие в первом ответе включи в полный reply.'),
            ('Обязательные служебные фразы добавляет сервер. Не придумывай их.',
             'Обязательные фразы из required_text включи в reply дословно; новые не придумывай.'),
            ('Приветствие и обязательный текст добавляет сервер. Обращайся на «вы»;',
             'Приветствие и обязательный текст включи в reply. Обращайся на «вы»;'),
        ):
            system = system.replace(old, new)
        system += ('\nДоверенный proposal_plan разрешает естественно сформулировать только '
                   'уже выбранный вопрос. В reply включи весь готовый текст с обязательным '
                   'приветствием/раскрытиями; сервер не будет чинить или заменять его шаблоном. '
                   'Сначала ответь на текущий вопрос в рамках required_text, затем только '
                   'выбранное уточнение. Не добавляй неподтверждённые утверждения. '
                   'Самостоятельно сформулируй last_intent/latest_client_meaning/note. '
                   'Если шаг неуместен, сохрани обоснованный пустой veto.')
        if plan['answer_current_question']:
            system += ('\nВ proposal_plan также разрешена отдельная цель answer_current_question. '
                       'Можно сначала только ответить на текущий вопрос клиента точным текстом '
                       'answer_current_question, без повторной анкеты. Неизвестные сведения '
                       'остаются неизвестными и обязательное уточнение переносится на следующий '
                       'уместный ход. Это не наличие всех деталей и не готовая заявка. '
                       'selected_step_fits оценивает выбранную допустимую цель ответа, а не '
                       'обязанность непременно задать прежний вопрос. Самостоятельно оцени '
                       'смысл клиента и уместность; обоснованный veto по-прежнему допустим.')
    elif plan['mode'] == 'source_bound_price':
        schema['properties']['reply'].pop('enum', None)
        for branch in schema.get('anyOf', []):
            props = branch.get('properties', {})
            if props.get('needs_operator', {}).get('enum') == [False]:
                props.get('reply', {}).pop('enum', None)
        task['server_price_reply_example'] = task.pop('fixed_reply')
        if 'proposed_reply' in task:
            task['server_proposed_reply_example'] = task.pop('proposed_reply')
        task['reply_field_scope'] = 'whole_source_bound_price_reply'
        task['source_price_conditions'] = copy.deepcopy(plan['price_frame'])
        task['output_contract']['decision_states_scope'] = (
            'Положительный reply — пример, не обязательный текст. Сформулируй свой полный ответ '
            'по source_price_conditions. Пустой обоснованный veto сохраняется.')
        system = system.replace(
            'Если есть fixed_reply, проверь его уместность и верни ДОСЛОВНО или запроси оператора.',
            'Сверь source_price_conditions с текущим запросом и первичными источниками.')
        system = system.replace(
            'При fixed_reply верни его ДОСЛОВНО; иначе кратко сформулируй только\n'
            'decision.next_question.question, сохраняя обязательные группы слов.',
            'Сформулируй полный ответ по source_price_conditions; сохрани выбранное уточнение.')
        system = system.replace('Приветствие и обязательный текст добавляет сервер.',
                                'Приветствие и обязательный текст включи в полный reply.')
        system = system.replace(
            'Не добавляй другие вопросы,\nдиагноз, цену, советы, детали, материалы, обещание выезда/ремонта или личные данные.',
            'Сохрани только исходные условия цены и выбранный вопрос. Не добавляй диагноз, '
            'советы, наличие материалов, обещание выезда/ремонта или личные данные.')
        system += ('\nДоверенный source_bound_price разрешает собственную формулировку только '
                   'уже подтверждённых условий цены из source_price_conditions. Примеры не '
                   'требуют дословного копирования. Цена/вид тарифа/единица/материалы/этап/осмотр '
                   'и границы городского выезда неизменны. Не утверждай согласие, запись, наличие '
                   'или действие. Сохрани обязательные раскрытия и выбранный вопрос; если нужен '
                   'ответ о согласии с ценой, только запроси его. Сервер не допишет текст после '
                   'review. Проверяющий оценивает именно полученный reply, а не самоотчёт: '
                   'проверь каждое условие и отсутствие лишних утверждений. Истории не источник '
                   'нынешней цены или фактов клиента. Неуместный ответ требует пустого veto.')
    return dict(system=system, task=task, schema=schema)


def _visit_wording_frame(reply, question, payload):
    """Set aside one literal reference to the current client time boundary for validation."""
    if question.get('kind') != 'visit_time':
        return reply, question
    visit = payload['facts'].get('requested_visit') or {}
    relation = {'after': 'после', 'before': 'до'}.get(visit.get('time_kind'))
    clock, date, window = (visit.get(key) for key in ('boundary_time', 'date_text', 'window'))
    if (not relation or not clock or not date or not window or visit.get('status') != 'requested'
            or visit.get('clarification_kind') != 'exact_clock'
            or visit.get('source') != 'client_message' or visit.get('appointment_confirmed') is not False
            or visit.get('client_confirmed') is not False
            or visit.get('message_id') != payload['messages'][-1].get('id')):
        return reply, question
    acknowledgement = f'Учту пожелание: {window}.'
    if acknowledgement not in payload['decision_internal'].get('required_text', []):
        return reply, question
    boundary = f'{relation} {clock}'
    prefix, _, wording = question['question'].partition(' — ')
    if prefix.casefold() != f'{boundary} {date}'.casefold() or not wording:
        return reply, question
    qualifier = rf'{re.escape(boundary)}(?: {re.escape(date)})?'
    framed, count = re.subn(
        rf'^{qualifier} [—–-] |(?<=\bточное время) {qualifier}(?= вам\b)',
        '', reply, count=1, flags=re.IGNORECASE)
    if count:
        return framed, dict(question, question=wording)
    return reply, question


def wording_violations(reply, payload):
    """Retain the old protection against invented rooms/objects/statements.

    A model review is not permission to bypass that vocabulary/frame fence.
    Exact mandatory disclosures are separated from the single clarification;
    they do not make arbitrary additional assertions acceptable.
    """
    import assistant_policy as policy
    import experience_wording
    decision = payload['decision_internal']
    if decision.get('price_wording_frame') is not None:
        import research_price_wording
        frame = research_price_wording.bound_frame(payload)
        errors, remainder = research_price_wording.check(reply, payload, frame)
        question = decision.get('next_question') or {}
        if not question:
            return errors + (['price_wording_unbound_extra_text'] if remainder else [])
        proxy = copy.deepcopy(payload)
        proxy['semantic_fixed_reply'] = None
        proxy['decision_internal'].pop('price_wording_frame')
        proxy['decision_internal'].update(greeting_required=False, required_text=[])
        return errors + wording_violations(remainder, proxy)
    question = decision['next_question']
    if not isinstance(reply, str):
        return ['proposal_wording_unbound']
    answer = answer_only_reply(payload)
    if answer and reply == answer:
        return []
    if reply == policy.compose_reply(question['question'], decision):
        return []
    tail = reply.strip()
    if decision.get('greeting_required'):
        tail = policy.GREETING_START.sub('', tail, count=1)
    for required in decision.get('required_text', []):
        if not tail.startswith(required):
            return ['proposal_required_text_missing']
        tail = tail[len(required):].lstrip()
    tail, question = _visit_wording_frame(tail, question, payload)
    experience = copy.deepcopy(payload.get('experience_context') or {})
    # The linguistic subject/acknowledgement evidence is derived from current
    # observed messages. It cannot be supplied by a candidate or browser.
    experience['conversation_style'] = experience_wording.contextual_style(payload['messages'], question)
    if not experience_wording.verified_question(tail, question, experience, 'provided'):
        return ['proposal_wording_unbound']
    return []
