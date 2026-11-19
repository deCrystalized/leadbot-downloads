"""Conservative wording boundary, additional to policy and context validation."""
import re
from experienced_dialogues import terms

POLITE = ('подскажите пожалуйста уточните скажите ли у вас по для к вам ваш ваша ваше ваши '
          'сохранилась сохранился сохранились имеется имеются есть эта этот это эти все уже')


def contextual_style(messages, question):
    """Linguistic options from current evidence, never inferred customer facts."""
    import assistant_prices
    import qualification_state
    from contact_facts import preceding_staff_speech
    current = assistant_prices.current_enquiry_messages(messages)
    style = dict(acknowledgement_allowed=False, subject_words=[], evidence_ids=[],
                 source='server_bound_linguistic_options_not_model_understanding')
    if not current:
        return style
    latest = current[-1]
    client_roles = ('client', 'customer', 'user', 'contact', 'lead', '')
    if latest.get('direction') == 'in' and latest.get('sender_type', 'client') in client_roles:
        previous = preceding_staff_speech(current, len(current) - 1)
        if (previous and '?' in previous[1].get('body', '') and '?' not in latest.get('body', '')
                and any(row['status'] == 'answered' and row.get('message_id') == latest.get('id')
                        for row in qualification_state.inspect(current).values())):
            style['acknowledgement_allowed'] = True
            style['evidence_ids'] = [previous[1].get('id', ''), latest.get('id', '')]
    if question.get('kind') not in ('instructions', 'materials', 'volume'):
        return style
    for message in current:
        if message.get('direction') != 'in' or message.get('sender_type', 'client') not in client_roles:
            continue
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', message.get('body', ''))
        if re.search(r'\bнов(?:ая|ый|ое)\s+(?:заявка|заказ|обращение)\b', text, re.I):
            style['subject_words'] = []
        for clause in re.split(r'[.!?;\n,]+', text):
            if re.search(r'\b(?:не|нет|если|вдруг|сказал\w*|говорит|написал\w*)\b', clause, re.I):
                continue
            match = re.search(
                r'\b(?:собрать|дособрать|сборк\w*)\s+'
                r'(?:(?:один|одну|новый|новую|мой|мою|небольшой|небольшую)\s+){0,3}'
                r'(?P<object>шкаф(?:а|у|ом|ы|ов)?(?:-купе)?|комод(?:а|у|ом|ы|ов)?|'
                r'кроват[ьиь]|тумб[ауы]|стол(?:а|у|ом|ы|ов)?)\b', clause, re.I)
            if match:
                style['subject_words'].extend(re.findall(r'[а-яё]+', match['object'].casefold()))
                style['evidence_ids'].append(message.get('id', ''))
    style['subject_words'] = list(dict.fromkeys(style['subject_words']))
    style['evidence_ids'] = list(dict.fromkeys(style['evidence_ids']))
    return style


def verified_question(reply, question, experience, review_status):
    if not isinstance(reply, str) or not experience or review_status != 'provided':
        return False
    style = experience.get('conversation_style') or {}
    # A bare acknowledgement contains no new assertion. All remaining text
    # still has to be one bounded, selected question with checked vocabulary.
    prefix = re.match(r'^\s*(?:Спасибо|Хорошо)[,.!]\s+', reply, re.I)
    if prefix:
        if style.get('acknowledgement_allowed') is not True:
            return False
        reply = reply[prefix.end():]
    contact_request = (question.get('kind') == 'phone' and '?' not in reply
                       and re.search(r'\b(?:напишите|оставьте|сообщите|подскажите|скажите)\b', reply, re.I))
    if contact_request:
        reply = reply.rstrip().removesuffix('.')
    if (not question.get('question')
            or not contact_request and (reply.count('?') != 1 or not reply.rstrip().endswith('?'))
            or reply.count(':') > question['question'].count(':')
            or re.search(r'[\d.!;\n"«»]|\b(?:не|нет|без|наш|наша|наше|нас|я|мы|мастер)\b', reply, re.I)):
        return False
    sources = [question['question']] + [row['staff_question'] for row in experience.get('examples', [])]
    from qualification_state import question_group_variants, question_matches
    sources += [' '.join(word for group in groups for word in group)
                for groups in question_group_variants(question)]
    if question.get('kind') == 'phone':
        sources.append('напишите оставьте сообщите можете можно контактный подсказать подскажете')
    subjects = ' '.join(style.get('subject_words', []))
    # Search stems leave short case forms such as «доме» untouched. A case
    # ending may refer only to a root literally in the trusted selected
    # question, never to a new subject or one found only in an old example.
    selected_roots = {word for word in terms(question['question'], limit=None) if len(word) == 3}
    def wording_terms(text):
        return {word[:-1] if len(word) == 4 and word[-1] in 'аеуыи'
                and word[:-1] in selected_roots else word for word in terms(text, limit=None)}
    allowed = wording_terms(' '.join(sources) + ' ' + POLITE + ' ' + subjects)
    actual = wording_terms(reply)
    # terms() deliberately omits common words for search. Check pronouns and
    # statement markers above before applying its bounded lexical vocabulary.
    if not actual or not actual.issubset(allowed):
        return False
    return question_matches(reply, question)
