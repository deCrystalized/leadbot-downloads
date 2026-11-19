"""Service decisions from reviewed scoped primary rules, never from examples."""

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import contact_phone
import filials

# Owner added partner624 with the same default review flag as the existing group.
AVITO_PARTNERS = frozenset(('7', '723', '748', '340', '624'))
OFFICE_APPLICATION = (r'\b(?:office|word|ворд(?:а|у|ом)?|excel|exel|эксел[ьяюе]?|эксель)\b|'
                      r'\b(?:пакет\w*|майкрософт|microsoft)\s+офис\w*|'
                      r'\b(?:программ\w*|microsoft)\s+world\b')


def office_fault_request(text):
    """A reported fault in the named applications, without a repair diagnosis."""
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
    for clause in re.split(r'[.!?;\n]+', literal):
        observed=re.sub(r'\bне\s+перестал[аои]?\s+(?:открываться|запускаться|работать|сохранять)\b',' ',clause,flags=re.I)
        if (re.search(OFFICE_APPLICATION,clause,re.I)
                and re.search(r'не\s+(?:работ|открыва|запуска|сохраня)|ошиб|завис|вылета|сбо[йи]|'
                              r'\bперестал[аои]?\s+(?:открываться|запускаться|работать|сохранять)\b',observed,re.I)
                and not re.search(r'\b(?:если|допустим|сказал\w*|говорит|написал\w*|по\s+словам)\b',clause,re.I)):
            return True
    return False


def office_installation_request(text):
    """A literal Office application installation, including bounded typos.

    Keep the source untouched. In particular, ``world`` alone is not Word:
    it needs another Office application or an explicit program context.
    Naming a program's fault is not ordering its installation.
    """
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
    install = r'\b(?:(?:пере)?установ\w*|устанавлива\w*|постав(?:ить|ите|ьте)|ставите)\b'
    clauses = re.split(r'[.!?;\n]+', literal)
    for index, clause in enumerate(clauses):
        if re.search(r'\b(?:если|вдруг|допустим|предположим|сказал\w*|говорит|написал\w*|по\s+словам)\b|'
                     r'\b(?:уже|раньше|вчера)\s+[^.!?\n]{0,15}(?:установ|постав)|'
                     r'\b(?:установили|установлен\w*|поставили)\b', clause, re.I):
            continue
        if re.search(r'\bне\s+(?:(?:нужно|нужна|надо|хочу|требуется)\s+)?' + install + r'|'
                     + install + r'[^.!?\n]{0,70}\bне\s+(?:надо|нужн\w*|требуется)', clause, re.I):
            continue
        names = re.search(OFFICE_APPLICATION, clause, re.I)
        if not names and index and re.fullmatch(
                r'\s*(?:(?:а|вы)\s+)?(?:(?:сможете|можете)\s+)?' + install
                + r'(?:\s+(?:сможете|можете))?\s*(?:,?\s*пожалуйста)?\s*', clause, re.I):
            # A short request may name its object in the immediately preceding
            # absence statement. No other object, past job or future hypothesis
            # may borrow that name; absence alone never orders installation.
            previous = clauses[index - 1]
            if (re.search(r'\b(?:нету?|отсутству\w*)\b', previous, re.I)
                    and not re.search(r'\b(?:если|вдруг|раньше|вчера|когда|сказал\w*|говорит|'
                                      r'написал\w*|по\s+словам|новая\s+заявка|другой\s+заказ)\b', previous, re.I)):
                names = re.search(OFFICE_APPLICATION, previous, re.I)
        if not names or not re.search(install, clause, re.I):
            continue
        if re.search(r'\b(?:вывеск\w*|табличк\w*|телевизор\w*|игр\w*)\b[^.!?\n]{0,30}'
                     + r'(?:office|word|world)\b', clause, re.I):
            continue
        return True
    return False


def ordinary_office_installation(text):
    """Office alone does not establish a hardware-model prerequisite."""
    if not office_installation_request(text):
        return False
    return not re.search(r'\b(?:ремонт\w*|почин\w*|замен\w*|помен\w*|чистк\w*|термопаст\w*|'
                         r'пайк\w*|перепа\w*|сборк\w*|собрать|перегрев\w*|разбит\w*|залит\w*)|'
                         r'не\s+(?:включ|заряж)|нет\s+изображения|'
                         r'\b(?:ssd|hdd|процессор|видеокарт\w*|оперативн\w*|материнск\w*)\b', text, re.I)


def ordinary_office_work(text):
    """Application symptoms alone do not establish hardware prerequisites."""
    if ordinary_office_installation(text):
        return True
    if not office_fault_request(text):
        return False
    computer = r'(?:компьютер|ноутбук|моноблок|пк)\w*'
    hardware = '|'.join([
        r'\b(?:замен\w*|помен\w*|чистк\w*|термопаст\w*|пайк\w*|перепа\w*|'
        r'сборк\w*|собрать|перегрев\w*|разбит\w*|залит\w*|ssd|hdd|процессор|видеокарт\w*)\b',
        r'\b(?:ремонт|почин\w*)\s+' + computer,
        computer + r'\s+(?:(?:совсем|вообще|больше|теперь)\s+){0,2}не\s+(?:работ|включ|заряж)',
        r'не\s+(?:работ|включ|заряж)\w*\s+' + computer,
    ])
    return not re.search(hardware, text, re.I)


def ordinary_windows_installation(text):
    """Literal software installation, with no separately requested hardware work.

    DOC0125 does not require a PC model; DOC0465 belongs to BT. Do not turn
    that appliance requirement into a Windows admission or pricing condition.
    """
    text = re.sub(r'''«[^»]*»|“[^”]*”|"[^"\n]*"|'[^'\n]*'|‘[^’]*’''', ' ', text)
    windows = r'\b(?:windows|винд(?:оус|овс|а|у|ы|е|ой|ою))(?:\s*\d+(?:\.\d+)?)?\b'
    operation = r'(?:(?:пере)?установ\w*|постав(?:ить|ите))'
    clauses = []
    for clause in re.split(r'[.!?;\n]+', text):
        if re.search(r'\b(?:если|вдруг|допустим|предположим)\b|'
                     r'\b(?:мастер|сосед|специалист|продавец)\w*[^,]{0,30}(?:сказал|написал|предложил)', clause, re.I):
            continue
        if re.search(r'\bне\s+(?:(?:нужно|нужна|надо|хочу|требуется)\s+)?' + operation
                     + r'[^.!?\n]{0,35}' + windows, clause, re.I):
            continue
        clauses.append(clause)
    literal = '\n'.join(clauses)
    installation = re.search(operation + r'[^.!?\n]{0,40}' + windows + r'|'
                             + windows + r'[^.!?\n]{0,40}' + operation, literal, re.I)
    if not installation:
        return False
    hardware = re.search(r'\b(?:ремонт\w*|почин\w*|замен\w*|помен\w*|чистк\w*|термопаст\w*|'
                         r'пайк\w*|перепа\w*|сборк\w*|собрать|перегрев\w*|разбит\w*|залит\w*)|'
                         r'нет\s+изображения|'
                         r'(?:ноутбук|компьютер|моноблок|\bпк\b)\w*[^.!?\n]{0,30}не\s+(?:включ|заряж)|'
                         r'не\s+(?:включ|заряж)\w*[^.!?\n]{0,30}(?:ноутбук|компьютер|моноблок|\bпк\b)', literal, re.I)
    component_install = re.search(operation + r'\s+(?:(?!windows|винд)[а-яё-]+\s+){0,2}'
                                 r'(?:ssd|hdd|процессор|видеокарт|оперативн|материнск|ж[её]стк)', literal, re.I)
    return not (hardware or component_install)


def _furniture_object_labels(text):
    return re.sub(r'\b(?:тв|tv)[ -]+тумб\w*|\bтелевизионн\w*\s+тумб\w*|'
                  r'\bтумб\w*\s+(?:под|для)\s+(?:телевизор\w*|тв|tv)\b','мебельная тумба',text,flags=re.I)


def _hanging_without_cabinet_mirrors(text):
    """Mirrored cabinet doors describe the furniture, not a wall-hanging job.

    This view only filters hanging matches. The literal request, furniture
    glass exceptions and independently requested mirror work stay intact.
    """
    return re.sub(
        r'\b(?:двер|дверц|створк)\w*\s+с\s+зеркал\w*|'
        r'\bшкаф\w*(?:-купе)?\s+с\s+зеркал\w*|'
        r'\bзеркальн\w*\s+(?:раздвижн\w*\s+)?(?:двер|дверц|створк)\w*',
        '[FURNITURE_MIRROR]', text, flags=re.I)


def _furniture_without_plumbing_support(text):
    """A fixture's cabinet support does not itself order cabinet work.

    This view is used only for furniture matching/questions. Other service
    families and the literal customer evidence retain the complete source.
    Keep independently requested cabinet work, including work in the same list.
    """
    action = r'(?:собра|собират|сборк|ремонт|отремонтир|почин|замен|помен|установ|повес|навес|закреп|прикрут)\w*'
    parts = r'петл|фасад|дверц|направляющ|полк|ящик|ножк|стенк|боковин'
    support = (r'\b(?:на|к|в|под|над)\s+(?:(?:готов\w*|существующ\w*|имеющ\w*)\s+)?(?:тумб|шкаф)\w*|'
               r'\bк\s+стен[еы]\s*(?:/|или|и)\s*(?:тумб|шкаф)\w*')
    # Split independent operations, retaining the literal source for every
    # retained clause. A colon continues a fixture's mounting description.
    clauses = re.split(r'[.!?;\n]+|,\s*|\s+(?:и|а|также|еще)\s+(?=' + action + r')', text, flags=re.I)
    result = []
    for clause in clauses:
        fixture = re.search(r'\b(?:раковин|умывальник|мойк)\w*', clause, re.I)
        direct_cabinet = re.search(action + r'\s+(?:(?!(?:на|к|в|под|над)\b)[а-яё-]+\s+){0,2}'
                                   r'(?:тумб|шкаф)\w*|(?:тумб[уы]|шкаф)\s+(?:надо\s+|нужно\s+)?' + action,
                                   clause, re.I)
        if (fixture and re.search(support, clause, re.I)
                and not direct_cabinet and not re.search(parts, clause, re.I)):
            result.append('[PLUMBING_SUPPORT]')
        else:
            result.append(clause)
    return '\n'.join(result)


def gpu_software_only(text):
    """A driver request does not establish physical graphics-card repair."""
    card = r'видеокарт\w*'
    work = r'(?:ремонт|почин|пайк|перепа|прогрев|прошив|перепрош|почист|чистк)\w*'
    physical = re.search(work + r'\s+(?:(?:сам\w*|стар\w*|нов\w*|сгоревш\w*|майнинг\w*)\s+){0,3}' + card
                         + r'|' + card + r'[^.!?\n,;]{0,35}(?:слом|сгор|отвал|пайк|перепа|прогрев|прошив|перепрош|ремонт|почин|термопаст|термопроклад|артефакт|биос|bios|не\s+работ)',
                         text, re.I)
    return bool(re.search(card, text, re.I) and re.search(r'драйвер', text, re.I) and not physical)


@lru_cache(maxsize=1)
def data():
    return json.loads(Path(__file__).with_name("reviewed_catalog.json").read_text())


def _furniture_form_categories(text):
    """Remove category alternatives only from recognized Avito task labels.

    Keep the selected operation, every other field and any free comment. The
    generic category 'assemble or disassemble' does not itself request both.
    """
    if (not re.search(r'Вот подробности|Задача составлена по\s+ответам клиента', text, re.I)
            or not re.search(r'^\s*Что сделать с мебелью\s*:', text, re.I | re.M)):
        return text
    category = r'собрать\s+или\s+разобрать\s+мебель'
    text = re.sub(r'\A([ \t]*)' + category + r'(?=[ \t]*·)', r'\1Мебель', text, flags=re.I)
    return re.sub(r'(^[ \t]*Какая услуга нужна:[ \t]*\n[ \t]*)' + category + r'(?=[ \t]*\n)',
                  r'\1Мебель', text, flags=re.I | re.M)


def _assembly_intent_text(text):
    return re.sub(r'не\s+(?:нужна?|надо|нужно)\s+(?:сборк|собира|собрать)\w*|'
                  r'(?:сборк|собира|собрать)\w*\s+не\s+(?:нужна?|надо|нужно)', '',
                  _furniture_form_categories(text), flags=re.I)


# Literal item families used only to check a free model claim against a
# structured category and the customer's later request. They do not choose
# services, prices, quantities or permission to create an order.
_REQUEST_ITEM_PATTERNS = {
    'shelf': r'\b(?:полк(?:а|и|у|е|ой|ою|ам|ами|ах)|полок|полочк\w*)\b',
    'cabinet': r'\bшкаф\w*\b',
    'pedestal': r'\b(?:тумб\w*|консол(?:ь|и|ей|ям|ями|ях|ью))\b',
    'table': r'\b(?:стол(?:а|у|ом|е|ы|ов|ам|ами|ах)?|столик\w*)\b',
    'bed': r'\bкроват\w*\b',
    'mirror': r'\bзеркал\w*\b',
    'curtain_rod': r'\b(?:карниз\w*|гардин\w*)\b',
    'picture': r'\bкартин\w*\b',
    'bracket': r'\bкронштейн\w*\b',
    'tv': r'\bтелевизор\w*\b',
}
_REQUEST_ITEM_OPERATION = re.compile(
    r'\b(?:собрать|соберите|сборк\w*|дособрать|повесить|повесьте|подвесить|'
    r'навесить|навесьте|прикрепить|установить|установите|установк\w*|заменить|замените)\b', re.I)


def _request_item_mentions(text):
    return [(kind, match) for kind, pattern in _REQUEST_ITEM_PATTERNS.items()
            for match in re.finditer(pattern, text, re.I)]


def _request_item_negated(text, match):
    before, after = text[:match.start()], text[match.end():]
    adjectives = r'(?:(?:подвесн|навесн|настенн|нов|стар|друг|отдельн|эт|никак|люб|одн)\w*\s+){0,3}'
    return bool(re.search(r'\b(?:не(?:\s+на)?|без|вместо)\s+' + adjectives + r'$|'
                          r'\bне\s+(?:нуж\w*|надо|требуется|заказ\w*|прос\w*)\s+'
                          r'(?:(?:собрать|повесить|установить|заменить)\s+)?' + adjectives + r'$', before, re.I)
                or re.match(r'\s+(?:(?:уже|больше|совсем)\s+)?не\s+(?:нуж\w*|надо|требуется|заказ\w*)\b', after, re.I))


def questionnaire_item_scope(timeline):
    """Bind a grouped task label to later literal customer work requests.

    Only a recognized, single-line multi-item form label is a category. Free
    prose and separate selected rows are not silently reduced to one item.
    Later explicit requests accumulate; only an explicit correction replaces
    them. Staff, failed delivery, quotes and stock answers cannot add jobs.
    """
    category = None
    requests = []
    other_mentions = []
    for row in timeline:
        if (row.get('speaker_role') != 'client' or row.get('direction') != 'in'
                or row.get('delivery_status') in ('failed', 'pending', 'queued', 'sending')):
            continue
        body = str(row.get('body') or '')
        direct = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        evidence_id = row.get('evidence_id') or row.get('id') or row.get('review_ref', '')
        if not evidence_id:
            continue
        if re.match(r'\s*(?:новая\s+(?:заявка|задача)|(?:новый|другой)\s+(?:заказ|запрос))\s*[:.!-]', direct, re.I):
            category, requests, other_mentions = None, [], []
        if (re.search(r'Вот подробности|Задача составлена по\s+ответам клиента', direct, re.I)
                and re.search(r'Задача составлена|Какие работы нужны', direct, re.I)):
            label = re.search(r'^\s*(?:Что повесить|Какая мебель|Что установить)\s*:[ \t]*\n'
                              r'[ \t]*[-•]?[ \t]*([^\n]+)(?=\n\s*\n|\s*$)', direct, re.I | re.M)
            if label and re.search(r'[,/]|\sили\s', label[1], re.I):
                items = sorted({kind for kind, _ in _request_item_mentions(label[1])})
                if len(items) > 1:
                    category = dict(evidence_id=evidence_id, quote=label[1].strip(),
                                    item_families=items, position=row.get('position'))
                    requests, other_mentions = [], []
            # A category is not a request, but a separately labelled customer
            # comment can contain genuine additional or specific work.
            comment = re.search(r'^\s*(?:Комментарий|Пожелания|Дополнительные пожелания)\s*:\s*\n'
                                r'([\s\S]*?)(?=\n\s*✨?\s*Задача составлена|\Z)', direct, re.I | re.M)
            if not comment:
                continue
            direct = comment[1]
        if not category:
            continue
        for sentence in re.findall(r'[^.!?;\n]+[.!?;\n]*', direct):
            mentions = _request_item_mentions(sentence)
            if not mentions:
                continue
            reported = bool(re.search(r'\b(?:сосед|мастер|продавец|он|она)\w*[^.!?]{0,35}'
                                      r'\b(?:сказал|написал|спросил|просил|советовал)\w*', sentence, re.I))
            conditional = bool(re.search(r'\bесли\b|\bвозможно\b|\bможет\s+быть\b|'
                                         r'\b(?:раньше|ранее|вчера|сам(?:а|и)?)\b|'
                                         r'\bуже\s+(?:собрал|повесил|установил|сделал)\w*\b|'
                                         r'\b(?:нужно|надо)\s+было\b', sentence, re.I))
            operation = _REQUEST_ITEM_OPERATION.search(sentence)
            additive = bool(requests and re.search(r'\b(?:ещ[её]|также|заодно)\b|^\s*и\b.*\bтоже\b', sentence, re.I))
            requested = bool((operation or additive) and not reported and not conditional and '?' not in sentence
                             and (not operation or not re.search(r'\bне\s+(?:(?:нужно|надо|хочу|требуется)\s+)?$',
                                                                 sentence[:operation.start()], re.I)))
            items = sorted({kind for kind, match in mentions
                            if not _request_item_negated(sentence, match)}) if requested else []
            if not reported and not conditional:
                withdrawn = {kind for kind, match in mentions
                             if _request_item_negated(sentence, match)}
                if withdrawn:
                    requests = [dict(r, item_families=[k for k in r['item_families'] if k not in withdrawn])
                                for r in requests]
                    requests = [r for r in requests if r['item_families']]
            if not items:
                other_mentions.append(dict(evidence_id=evidence_id, quote=sentence.strip(),
                                           item_families=sorted({kind for kind, _ in mentions})))
                continue
            item_words = '|'.join(_REQUEST_ITEM_PATTERNS.values())
            if re.search(r'\bтолько\s+(?:(?:подвесн|навесн)\w*\s+)?(?:' + item_words + r')', sentence, re.I):
                requests = []
            requests.append(dict(evidence_id=evidence_id, quote=sentence.strip(),
                                 item_families=items,
                                 operations=[m[0] for m in _REQUEST_ITEM_OPERATION.finditer(sentence)],
                                 operations_are_literal_words_not_item_pairs=True,
                                 position=row.get('position')))
    if not category or not requests:
        return None
    active = sorted({item for row in requests for item in row['item_families']})
    category_only = set(category['item_families']) - set(active)
    # A hanging pedestal can be called a cabinet generically. That synonym
    # alone is not evidence of an extra piece; an additional shelf still is.
    if 'pedestal' in active:
        category_only.discard('cabinet')
    return dict(source='server_literal_request_scope_not_model_understanding',
                category=category, client_requests=requests, active_item_families=active,
                category_only_item_families=sorted(category_only), other_client_mentions=other_mentions,
                does_not_establish=['item_count', 'work_execution', 'materials_or_diagram',
                                    'price_consent', 'visit', 'CRM_creation'])


def unsupported_questionnaire_item(text, context, *, as_client_goal=False):
    """A category is not an additional requested object in free model prose."""
    excluded = set(context.get('category_only_item_families', []))
    for sentence in re.findall(r'[^.!?;\n]+[.!?;\n]*', str(text or '')):
        for kind, match in _request_item_mentions(sentence):
            if kind not in excluded or _request_item_negated(sentence, match):
                continue
            before = sentence[:match.start()]
            history_clause = re.split(r'[,:(]|—', before)[-1]
            if (re.search(r'\b(?:категори\w*\s+анкеты|в\s+анкете|из\s+анкеты)\b[^:;.!?]{0,65}$', history_clause, re.I)
                    and not re.search(r'заказ|хоч|прос|нужн|стоим|монтаж|сборк|повес|установ', history_clause, re.I)):
                continue
            if (re.search(r'\b(?:ли|если)\b[^.!?]{0,45}$', before, re.I)
                    or re.search(r'\b(?:нужна|нужен|нужны)\s+ли\b', before, re.I)):
                continue
            # Literal non-order background can still be described as such.
            reported_elsewhere = any(kind in r['item_families'] for r in context.get('other_client_mentions', []))
            service_claim = re.search(r'заказ|сборк|собра|повес|монтаж|установ|стоим|нужн|требу|прос|работ|запрос', sentence, re.I)
            if reported_elsewhere and not as_client_goal and not service_claim:
                continue
            return True
    return False


def furniture_assembly_request(text):
    normalized = _assembly_intent_text(text)
    assembly = re.search(r'\b(?:собрать|собирать|сборк\w*|установить|установк\w*)\b|приш[её]л|доставлен|куплен', normalized, re.I)
    repair = re.search(r'ремонт|почин|сломан|сломал|перетяж|реставр', normalized, re.I)
    return bool(assembly and not repair)


def swollen_furniture_panels(text):
    return re.search(r'(?:взбух|разбух|набух)\w*[^.!?\n]{0,35}(?:детал|панел|стенк|боковин)|'
                     r'(?:детал|панел|стенк|боковин)\w*[^.!?\n]{0,35}(?:взбух|разбух|набух)', text, re.I)


def furniture_parts_replacement_request(text):
    """Replacing named furniture parts does not request their manufacture."""
    replacement = r'\b(?:замен(?:ить|а|ять)|поменять|сменить)\b'
    return bool(re.search(r'шкаф|мебел|комод|кухн|тумб|кроват|стол', text, re.I)
                and re.search(replacement + r'[^.!?\n]{0,75}(?:детал|панел|стенк|боковин)|'
                              r'(?:детал|панел|стенк|боковин)\w*[^.!?\n]{0,45}' + replacement, text, re.I)
                and not re.search(r'реставр|изготов|перетяж|пружин|ротанг|стекл', text, re.I))


def service_capability_question(text):
    """A customer asks the service, rather than confirming its capabilities."""
    opening = r'^\s*(?:(?:а|здравствуйте|скажите|подскажите|пожалуйста)[,\s]*)*'
    question = (r'(?:вы\s+(?:(?:такое|такую\s+работу|такие\s+работы|этим|таким)\s+)?'
                r'(?:бер[её]те|принимаете|делаете|выполняете|занимаетесь)|'
                r'можно(?:\s+ли)?\s+(?:заменить|поменять|сменить)|'
                r'(?:можете|сможете)(?:\s+ли)?\s+(?:мне\s+)?(?:заменить|поменять|сменить))\b')
    return any(re.search(opening + question, clause, re.I)
               or re.search(r'\b(?:заменить|поменять|сменить)\s+можно\b', clause, re.I)
               for clause in re.split(r'[.!?\n]+', text))


def furniture_fitting_problem(text):
    """A current stated door/drawer action or symptom, not a quoted diagnosis."""
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', text)
    item = r'(?:двер\w*|ящик\w*)'
    adjustment = r'(?:отрегулир|регулиров)\w*'
    symptom = r'(?:заеда(?:ет|ют)|не\s+(?:открыва|закрыва)\w*)'
    for clause in re.split(r'[,.!;\n]+', literal):
        if re.search(r'\b(?:если|допустим|раньше|вчера|сказал\w*|говорит|написал\w*)\b|'
                     r'по\s+словам|\bне\s+(?:нуж\w*|надо|требуется)\b|'
                     r'\bне\s+заеда\w*|регулиров\w*\s+не\s+(?:нуж\w*|надо)', clause, re.I):
            continue
        match = re.search(item + r'[^.!?\n]{0,35}(?:' + adjustment + '|' + symptom + ')|'
                          + adjustment + r'[^.!?\n]{0,35}' + item, clause, re.I)
        if match:
            return match
    return None


def furniture_repair_request(text):
    """The customer's damaged fittings describe repair without that label."""
    return bool(furniture_parts_replacement_request(text) or swollen_furniture_panels(text)
        or furniture_fitting_problem(text) or re.search(
        r'ремонт|почин|слом(?:ан|ал)|отвал|оторва|вырва|расшат|'
        r'(?:(?:отверсти|дырк|креплен|петл|направляющ|двер|ящик)\w*[^.!?\n]{0,45}'
        r'(?:разбит|поврежд|испорч|выпал|не\s+закрыва|не\s+держ))|'
        r'(?:разбит|поврежд|испорч)\w*[^.!?\n]{0,45}(?:отверсти|дырк|креплен|петл)|'
        r'(?:прикрут|закреп)\w*[^.!?\n]{0,25}двер\w*[^.!?\n]{0,20}шкаф|'
        r'(?:отрегулир|регулиров)\w*[^.!?\n]{0,35}(?:фасад|дверц|петл|ящик)|'
        r'(?:фасад|дверц|петл|ящик)\w*[^.!?\n]{0,35}(?:отрегулир|регулиров)',
        text, re.I))


def assembled_kitchen_adjustment(text):
    """A completed assembly plus fitting adjustment is not a new kitchen kit."""
    completed = re.search(r'\b(?:кухн(?:я|ю)|кухонн\w*\s+гарнитур)\s+(?:уже\s+)?(?:собран[а]?|собрали)\b', text, re.I)
    requested = _assembly_intent_text(text)
    new_work = re.search(r'\b(?:собрать|собирать)\b|\bсборк\w*\s+(?:нов\w*\s+)?(?:кухн|гарнитур)', requested, re.I)
    return bool(completed and furniture_repair_request(text) and not new_work)


def canonical_partner(value):
    text = str(value or '').strip()
    return (text.lstrip('0') or '0') if re.fullmatch(r'\d+', text) else text


def source_direction(known: Mapping[str, object]) -> tuple[str, str]:
    """Resolve source metadata without treating customer wording as a route.

    A single-profile Avito advertisement can correct a route inferred from the
    account name. Explicit operator choices and ambiguous ads are preserved.
    Missing routes require an exact partner/source entry in the owner catalogue.
    """
    explicit = str(known.get("direction") or "")
    if explicit and known.get('direction_basis') == 'operator':
        return explicit, 'operator'
    # The installed extension chooses MNC first for a mixed BT/MNC account.
    # Both that account and an explicit repair advertisement establish BT;
    # client wording alone must never change a single-profile channel.
    account = str(known.get("account_name") or "")
    title = _furniture_object_labels(str(known.get("title") or ""))
    account_guess = next((d for label, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in account.upper()), "")
    if explicit and account_guess and known.get('channel') == 'avito' and known.get('direction_basis') != 'operator' and explicit == account_guess:
        profiles = set()
        if re.search(r'компьютер|ноутбук|моноблок|принтер|мфу|телевиз|роутер|\bwi[-\s]?fi\b|\bwindows\b', title, re.IGNORECASE):
            profiles.add('kp')
        if re.search(r'муж\s+на\s+час|мастер\s+на\s+час|сантехник|электрик|сборк\w*\s+мебел', title, re.IGNORECASE):
            profiles.add('mnc')
        appliance_ad = re.search(r'холодиль|стирал|посудомоеч|духов|варочн|бойлер|водонагрев|кофемаш|кофевар', title, re.IGNORECASE)
        if appliance_ad:
            if re.search(r'ремонт|не\s+(?:работ|включ|гре|нагре|мороз|слив|крут)', title, re.IGNORECASE) and not re.search(r'подключ|установ|сборк|электрик|сантехник', title, re.IGNORECASE):
                profiles.add('bt')
            elif re.search(r'подключ|установ', title, re.IGNORECASE):
                profiles.add('mnc')
        if len(profiles) == 1 and explicit not in profiles:
            target = profiles.pop()
            if (explicit == 'mnc' and target == 'bt' and not re.search(r'БТ', account, re.I)
                    and filials.known(known.get('city', ''), 'mnc')
                    and not filials.known(known.get('city', ''), 'bt')):
                # DOC0375 permits BT work on a genuine MNC source in these
                # cities. The appliance in its ad is not a new BT channel.
                return 'mnc', 'mnc_bt_work_without_bt_branch'
            evidence = 'mixed_account_repair_ad' if target == 'bt' and re.search(r'БТ\s*/\s*МНЧ', account, re.IGNORECASE) else 'advert_profile_over_account_guess'
            return target, evidence
    if (known.get("channel") == "avito" and explicit == "mnc"
            and re.search(r"БТ\s*/\s*МНЧ", account, re.IGNORECASE)
            and re.search(r"холодиль|стиральн|посудомоеч|духов|варочн", title, re.IGNORECASE)
            and re.search(r"ремонт|не\s+(?:работ|включ|гре|нагре|мороз|слив|крут)", title, re.IGNORECASE)
            and not re.search(r"подключ|установ|сборк|электрик|сантехник", title, re.IGNORECASE)):
        return "bt", "mixed_account_repair_ad"
    if explicit:
        return explicit, "context"
    if known.get("channel") != "avito":
        return "", ""
    partner = canonical_partner(known.get("partner"))
    origin = str(known.get("origin") or "").strip().upper()
    origin = origin.translate(str.maketrans("ABCM", "АВСМ"))
    match = re.fullmatch(r"([АБВМС]\d+(?:\.\d+)?)(?:\s+(КП|БТ|МНЧ))?", origin)
    if not match:
        return "", ""
    marker = {"КП": "kp", "БТ": "bt", "МНЧ": "mnc"}.get(match[2], "")
    for route in data().get("channel_routes", {}).get("items", []):
        if route["source"] == match[1] and route["partner"] == partner:
            if marker and marker != route["direction"]:
                return "", "source_conflict"
            return route["direction"], "owner_source_list:" + route["source"]
    return "", ""


def clean(text):
    text = _furniture_form_categories(text)
    # A washbasin is a sink. Keep the original customer wording outside this
    # catalog-only alias, including the request/comment and source evidence.
    text = re.sub(r'\bумывальник\w*', 'раковина', text, flags=re.I)
    for phone in reversed(contact_phone.find_all(text)):
        text = text[: phone.start] + "[КОНТАКТ]" + text[phone.end :]
    text = re.sub(
        r"(?:мой\s+)?(?:номер\s+телефона|телефон|номер)(?:\s+для\s+связи)?\s*[:—-]?\s*\[КОНТАКТ\]",
        "[КОНТАКТ]",
        text,
        flags=re.IGNORECASE,
    )
    text = text.lower().replace("ё", "е")
    text = re.sub(r'\bпо\s+телефону\b', '[COMMUNICATION]', text)
    text = re.sub(r'\bне\s+(?:капает|лопнул\w*|треснул\w*|поврежден\w*|разбит\w*)', '', text)
    # Preserve the correction's positive side; do not apply a negated exception.
    return re.sub(
        r"\bне\s+(?:нуж[еннаоы]+\s+)?(?:газов\w*|матриц\w*|чистк\w*|телевизор\w*)",
        "",
        text,
    )


def confirmed_tv_bands(text):
    """Owner 17.10.2026: confirmed screen bands warrant refusal, not a diagnosis."""
    confirmed = False
    for clause in re.split(r"[,.!?;\n]+", text.lower().replace("ё", "е")):
        negative = (
            r"\b(?:нет|без|не было|не появились|не появлялись)\s+(?:(?:никаких|вертикальных|горизонтальных|цветных)\s+)*полос\w*"
            r"|\bполос\w*(?:\s+на\s+(?:экране|дисплее|телевизоре))?\s+(?:нет|не было|не появилось|не появились|не появлялись|не появляются)"
            r"|\bне\s+(?:в\s+)?полоск\w*"
        )
        affirmative = re.sub(negative, '', clause)
        affirmative = re.sub(r'\bполос\w*\s+(?:только\s+)?на\s+(?:корпусе|крышке|рамке)\b', '', affirmative)
        if re.search(r"\b(?:если|вдруг|допустим|возможно|наверно\w*)\b|\bможет\s+(?:быть|появ|возник)|\b(?:появятся|возникнут|будут)\s+(?:(?:цветные|вертикальные|горизонтальные)\s+)?полос", affirmative):
            continue
        if re.search(negative, clause):
            confirmed = False
        if re.search(r"\bполос(?:а|ы|е|у|ой|ами|ах|ка|ки|ку|ке|кой|кам|ками|ках|ок)?\b", affirmative):
            confirmed = True
    return confirmed


def confirmed_tv_matrix(text):
    """DOC-L0217: bands alone do not establish a broken matrix."""
    for clause in re.split(r"[,.!?;\n]+", text.lower().replace("ё", "е")):
        if re.search(
            r"\b(?:возможно|наверно\w*|может|думаю|похоже|если|вдруг|допустим)\b",
            clause,
        ):
            continue
        affirmative = re.sub(
            r"(?:нет|без|не было|не появились|не появлялись)\s+(?:(?:никаких|вертикальных|горизонтальных)\s+)*полос\w*"
            r"|полос\w*\s+(?:нет|не было)"
            r"|не\s+(?:разбит\w*|поврежден\w*|тресну\w*|сломан\w*)"
            r"|не\s+(?:нуж\w*\s+)?(?:замен\w*|ремонт\w*|поменять).{0,20}матриц\w*",
            "",
            clause,
        )
        if re.search(
            r"(?:матриц\w*|экран\w*).{0,45}(?:разбит\w*|поврежден\w*|тресну\w*|сломан\w*)"
            r"|(?:разбит\w*|поврежден\w*|тресну\w*|сломан\w*).{0,45}(?:матриц\w*|экран\w*)"
            r"|(?:замен\w*|ремонт\w*|поменять).{0,20}матриц\w*",
            affirmative,
        ):
            return True
    return False


def coffee_vending_scope(text):
    """Owner19.10: professional portafilters are not paid coffee vendors."""
    if not re.search(r'кофемаш|кофевар|кофейн|\bкофе\b', text, re.I):
        return ''
    vending = r'вендинг\w*|торгов\w*\s+(?:кофейн\w*\s+)?автомат\w*|кофейн\w*\s+(?:торгов\w*\s+)?автомат\w*|автомат\w*\s+(?:по\s+продаже\s+)?кофе'
    negative = re.search(r'не\s+(?:торгов\w*\s+)?автомат\b|не\s+вендинг', text, re.I)
    no_terminal = re.search(r'без\s+(?:(?:встроенн|плат[её]жн)\w*\s+){0,2}терминал|'
                            r'терминал\w*(?:\s+оплаты)?\s+(?:нет|отсутствует|не\s+имеет)|'
                            r'не\s+оборудован\w*\s+(?:плат[её]жн\w*\s+)?терминал',text,re.I)
    vendor = bool(re.search(vending,text,re.I) and not negative)
    if vendor:
        if no_terminal:
            return 'ordinary'
        # A checkout terminal elsewhere in a cafe is not part of the machine.
        for clause in re.split(r'[.!?\n]+',text):
            payment = re.search(r'(?:плат[её]жн\w*\s+терминал|терминал\w*\s+(?:для\s+)?оплат)',clause,re.I)
            unrelated = re.search(r'рядом|касс\w*|отдельн\w*\s+терминал',clause,re.I)
            bound = re.search(vending,clause,re.I) or re.search(r'\b(?:в\s+н[её]м|у\s+него|встроен\w*)\b',clause,re.I)
            if payment and bound and not unrelated:
                return 'vending'
        return 'unclear'
    if negative or no_terminal or re.search(r'рожков|не\s+промышленн', text, re.I):
        return 'ordinary'
    return 'unclear' if re.search(r'промышленн', text, re.I) else ''


def _coffee_without_industrial_label(text):
    # Remove only the coffee-bound adjective. An industrial washer or another
    # appliance requested separately must keep its original acceptance rule.
    subject=r'(?:кофемашин\w*|кофевар\w*|кофейн\w*\s+автомат\w*)'
    descriptors=r'(?:(?:рожков\w*|профессиональн\w*|двухгруппн\w*|торгов\w*)\s+){0,3}'
    text=re.sub(r'\bпромышленн\w*\s+(?='+descriptors+subject+r')','',text,flags=re.I)
    return re.sub(r'('+subject+r'\s+)промышленн\w*\b',r'\1',text,flags=re.I)


def _household_supply_context(text):
    """Reported supply symptoms, never a diagnosis or appliance repair grant."""
    text = str(text or '').casefold().replace('ё', 'е')
    text = re.sub(r'\b(?:другой\s+)?(?:мастер|специалист|сосед)\w*[^.!?\n«“"]{0,30}'
                  r'\b(?:спросил|сказал|написал|ответил)\w*\s*[:,-]?\s*(?:«[^»]*»|“[^”]*”|"[^"\n]*")', ' ', text)
    general = any(not re.search(r'\bне\s*$', text[max(0, m.start()-8):m.start()])
                  for m in re.finditer(r'\b(?:пропал\w*|нет|отключ\w*)\s+(?:электричеств\w*|электропитани\w*)', text))
    common = re.search(r'\b(?:общ\w*|одн\w*)\s+(?:лини\w*(?:\s+питани\w*)?|провод\w*|питани\w*)', text)
    failure = re.search(r'\bне\s+работ\w*|\bперестал\w*[^.!?\n]{0,35}\bработ\w*', text)
    suspected = re.search(r'\bкоротк\w*\s+замыкани\w*|\bподозрен\w*\s+на\s+(?:коротк\w*\s+)?замыкани\w*', text)
    appliance = re.search(r'стирал|посудомо|холодиль|бойлер|водонагрев|телевиз|ноутбук|компьют|духов|\bплит', text)
    return bool(general or common and failure or suspected and not appliance)


def _requested_work_clauses(text, operation):
    """Only new, non-negated operations; quoted offers are not client orders."""
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', text)
    for clause in re.split(r'[,.!;\n]+|\s+(?:а|но|и|также|еще)\s+', text):
        if re.search(r'\b(?:мастер|сосед|специалист)\w*[^,]{0,30}(?:сказал|предложил|советовал)|'
                     r'\bуже\s+(?:сделан|выполнен|установлен|достал|извлек)', clause, re.I):
            continue
        for match in re.finditer(operation, clause, re.I):
            before, after = clause[:match.start()], clause[match.end():]
            tail = re.split(r',|\b(?:а|но|также|еще)\b', after, maxsplit=1, flags=re.I)[0]
            if (re.search(r'\b(?:не\s+(?:(?:нужно|надо|хочу|требуется)\s+)?|без\s+)$', before, re.I)
                    or re.search(r'\bне\s+(?:нуж\w*|надо|требуется)|\bуже\s+(?:сделан|выполнен)', tail, re.I)):
                continue
            yield clause
            break


def _broken_key_extraction_request(text):
    key = r'(?:облом\w*|слом\w*|застря\w*)[^.!?\n]{0,40}ключ|ключ\w*[^.!?\n]{0,40}(?:облом|слом|застря)'
    scope = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', text)
    if not re.search(key, scope, re.I) or not re.search(r'замк|замок|двер', scope, re.I):
        return False
    action = r'\b(?:достать|достанете|достаньте|вытащить|вытащите|вынуть|извлечь|извлечете|извлеките|извлечение)\b'
    return any(re.search(r'ключ|облом', clause, re.I) or re.fullmatch(
        r'\s*(?:а\s+)?(?:просто\s+|только\s+)?' + action + r'\s*(?:никак|можно|получится|сможете)?\s*\??\s*', clause, re.I)
        for clause in _requested_work_clauses(scope, action))


def _without_siphon_fixture_locations(text):
    """A sink locating the requested siphon is not another ordered sink job."""
    operation = r'(?:замен\w*|помен\w*|установ\w*)'
    part = r'\b' + operation + r'\b[^.!?;\n]{0,45}\bсифон\w*\b|\bсифон\w*\b[^.!?;\n]{0,45}\b' + operation + r'\b'

    def clause(match):
        body = match[0]
        if (not re.search(part, body, re.I)
                or re.search(r'\b(?:если|вдруг|возможно|раньше|вчера|самостоятельно)\b|'
                             r'\bне\s+(?:нужно|надо|требуется|замен\w*|установ\w*)\b', body, re.I)):
            return body
        return re.sub(r'\b(?:под|у|в|на)\s+(?:(?:кухонн|ванн)\w*\s+)?(?:раковин|мойк)\w*\b',
                      '[SIPHON_LOCATION]', body, flags=re.I)

    return re.sub(r'[^.!?;\n]+', clause, text)


def _without_contact_lookup_notices(text):
    """A plan to find a contact does not order repair of a telephone."""
    def clause(match):
        body = match[0]
        if re.search(r'ремонт|почин|разбит|экран|аккумулятор|заряж|слом|не\s+работ|не\s+включ', body, re.I):
            return body
        return re.sub(r'\b(?:найду|поищу|уточню|подскажу|запишу)\s+(?:вам\s+)?телефон\b',
                      '[CONTACT_LOOKUP]', body, flags=re.I)
    return re.sub(r'[^.!?;\n]+', clause, text)


def _without_excluded_electrical_context(text):
    """Remove explicit exclusions and a literal panel location, never faults."""
    electrical = r'(?:проводк|кабел|розетк|выключател)\w*'
    patterns = (
        rf'\bбез\s+перенос(?:а|ов)\s+{electrical}',
        rf'\bне\s+(?:нужно|надо|требуется)\s+переносить\s+{electrical}',
        rf'\bперенос(?:ить)?\s+{electrical}(?:\s+или\s+штробить\s+стен\w*)?\s+не\s+(?:нужен|нужно|надо|требуется)\b',
        r'\b(?:щиток|электрощит)\s+(?:находится|расположен|стоит)\s+'
        r'(?:в\s+(?:коридоре|квартире|прихожей)|на\s+(?:площадке|этаже))'
        r'(?:\s+(?:квартиры|дома))?(?=\s*(?:[.!?;\n]|$))',
    )
    for pattern in patterns:
        text = re.sub(pattern, '[ELECTRICAL_CONTEXT]', text, flags=re.I)
    return text


def _without_closed_prior_work(text):
    """Project an explicit closed prior order out of current service selection.

    This is reported historical context, not verification of a CRM state.
    Keep ambiguity, quoted/conditional closure and every new requested job.
    The caller's original messages and source text are never rewritten.
    """
    current = (r'\b(?:сейчас|теперь)\s+(?:мне\s+)?'
               r'(?:нужен|нужна|нужны|нужно|надо|требуется|требуются|хочу|прошу|помогите)\b(?!\s+не\b)')
    if not re.search(current, text, re.IGNORECASE):
        return text, []
    closed = re.compile(
        r'\s*(?:(?:а|но)\s+)?(?:(?:мой|наш|моя|наша)\s+)?'
        r'(?:старый|старая|прошлый|прошлая|предыдущий|предыдущая)\s+(?:заказ|заявка)\b'
        r'[^.!?;\n]{0,200}?\b(?:закрыт[а]?|заверш[её]н[а]?|выполнен[а]?)\s*[.!;]?\s*', re.IGNORECASE)
    uncertain = (r'\b(?:не|нет|если|когда|почему|кажется|вроде|возможно|якобы|будет|будут|'
                 r'должен|должна|снова|повторно|осталось|нужно|надо|нужен|нужна|нужны)\b|[?«»“”"]')
    # A comma can separate the closed-order statement and the current ask.
    # Do not split ordinary lists of jobs or clauses inside the old subject.
    parts = re.split(r'(?<=[.!?;\n])|,\s*(?=' + current + ')', text, flags=re.IGNORECASE)
    if not any(re.match(r'\s*(?:(?:а|но)\s+)?' + current, part, re.IGNORECASE)
               and not re.search(r'\bесли\b|[«»“”"]', part, re.IGNORECASE) for part in parts):
        return text, []
    excluded, kept = [], []
    for part in parts:
        if closed.fullmatch(part) and not re.search(uncertain, part, re.IGNORECASE):
            excluded.append(part.strip())
        else:
            kept.append(part)
    return ('\n'.join(kept), excluded) if excluded else (text, [])


def choose(text, known):
    current, prior = _without_closed_prior_work(text)
    result = _choose_current(current, known)
    if prior:
        result['historical_service_context'] = {
            'reported_closed_prior_quotes': prior,
            'excluded_only_from_service_selection': True,
            'verifies_crm_closure': False,
        }
    return result


def _choose_current(text, known):
    text = _furniture_form_categories(text)
    normalized = clean(text)
    direction = known.get("direction", "")
    if direction == 'mnc':
        normalized = _without_contact_lookup_notices(normalized)
        normalized = _without_excluded_electrical_context(normalized)
    from qualification_state import printer_conversion_request
    if direction == 'kp' and printer_conversion_request(normalized):
        item = dict(next(r for r in data()['rules'] if r['id'] == 'printer-special'),
                    status='agree', primary_refs=['DOC-L0187'])
        return dict(status='agree', reason='Явно заказана переделка из одного типа принтера в другой: требуется согласование',
                    rules=['DOC-L0187'], items=[item])
    vending_scope = coffee_vending_scope(normalized)
    if vending_scope:
        normalized = _coffee_without_industrial_label(normalized)
    normalized = re.sub(r'\bгазов\w*\s+элемент\w*\s+нет\b', '[NO_GAS_ELEMENTS]', normalized, flags=re.I)
    # DOC-L0401/1247 also exclude the electric oven of a combined gas stove.
    # The customer's explicit shorthand establishes this, without re-asking
    # about gas after they already described both parts of the same appliance.
    if re.search(r'\bверх\s*[:—-]?\s*газ\b[^.!?\n]{0,60}\bдуховк\w*\s+электр', normalized, re.I):
        item = dict(id='gas', family='any', profile='any', status='refuse',
                    primary_refs=['DOC-L0401', 'DOC-L1247'], questions=[])
        return dict(status='refuse', reason='Комбинированная плита имеет газовые элементы: ремонт электрической духовки также не принимается',
                    rules=item['primary_refs'], items=[item])
    # A TV stand is a furniture label. Only that label is replaced, so a
    # separately requested television repair or mount remains in the scope.
    normalized=_furniture_object_labels(normalized)
    normalized=re.sub(r'\bпо\s+вешать\b','повешать',normalized,flags=re.I)
    if direction == 'kp' and re.search(r'\bсистемн\w*\s+блок\w*\b', normalized):
        normalized += '\nкомпьютер'
    if (direction == 'mnc' and re.search(r'\b(?:установ|повес|прикрут|закреп)\w*[^.!?\n]{0,30}\bфасад\w*', normalized)
            and (re.search(r'\bпм\b|посудомоеч|кухон|шкаф|мебел', normalized)
                 or re.search(r'мебел', str(known.get('title') or ''), re.I))
            and not re.search(r'фасад\w*\s+(?:дома|здания)|утепл|обшив|наружн', normalized)):
        normalized += '\nустановка мебельного фасада'
    if (direction == 'bt' and re.search(r'стиральн', str(known.get('title') or ''), re.I)
            and re.search(r'\bмашинк\w*\b', normalized) and re.search(r'барабан', normalized)
            and not re.search(r'швейн|кофе|посудомо|сушильн', normalized)):
        normalized += '\nстиральная машина'
    if (direction == 'mnc' and re.search(r'кух[ао]нн\w*\s+гарнитур|шкаф', normalized)
            and re.search(r'дверц\w*[^.!?\n]{0,35}отвалива|ящик[^.!?\n]{0,20}слома', normalized)):
        normalized += '\nремонт мебели'
    if (direction=='bt' and re.search(r'холодильн\w*\s+камер',normalized)
            and re.search(r'полаир|polair',normalized)):
        item=dict(id='industrial-cold-chamber',family='fridge',profile='bt',status='agree',primary_refs=['DOC-L0466'],questions=['model'])
        return dict(status='agree',reason='Промышленная холодильная камера принимается строго по согласованию с филиалом',rules=['DOC-L0466'],items=[item])
    manufacture = re.search(r'изготов', normalized) or (
        re.search(r'сделать[^.!?\n]{0,15}нов\w*\s+(?:створк|двер)', normalized)
        and re.search(r'из\s+стар\w*', normalized))
    if (direction == 'mnc' and manufacture
            and re.search(r'шкаф|мебел|комод|кухн|тумб|стол', normalized)
            and not re.search(r'не\s+изготов', normalized)):
        return dict(status='unknown',operator_scope='furniture_manufacture',
                    reason='Подтверждено изготовление мебели, не сборка готовой: работу согласует оператор с филиалом',
                    rules=['DOC-L0452','DOC-L0453'],items=[])
    if (direction == 'mnc' and re.search(r'восстанов\w*[^.!?\n]{0,35}замочн\w*\s+скважин', normalized)):
        return dict(status='unknown', operator_scope='door_cutout_restoration',
                    reason='Восстановление повреждённой выборки под замок не подтверждено как обычная установка фурнитуры: состав работ согласует оператор',
                    rules=['DOC-L0452','DOC-L0453'], items=[])
    if (direction == 'bt' and re.search(r'кофемаш|кофевар', str(known.get('title') or ''), re.IGNORECASE)
            and re.search(r'капучинатор|молок|кофе', normalized)
            and not re.search(r'холодиль|стирал|посудомо|бойлер|духов|телевиз|ноутбук', normalized)):
        normalized += '\nкофемашина'
    # A client may immediately correct the initial word ('Кран ...' ->
    # 'Экран'). Keep original evidence, and do not remove an independent tap
    # job or treat an old correction as applying to a later request.
    if (direction == 'kp' and re.search(r'телевиз|\bтв\b', normalized)
            and re.search(r'(?:^|\n)\s*экран[.!\s]*$', normalized)):
        normalized = re.sub(r'\bкран(?=\s+полос)', 'экран', normalized)
    if direction == 'kp' and re.search(r'в\s+реальн\w*\s+времен', normalized) and re.search(r'оплат|счет|бухгалтер', normalized) and re.search(r'телевиз|\bтв\b', normalized):
        return dict(status='unknown', operator_scope='custom_integration', reason='Нестандартная программная интеграция вне подтверждённого перечня: оператор уточняет проект', rules=['DOC-L0250', 'DOC-L0251'], items=[])
    if direction == 'mnc' and re.search(r'общепит|лар[её]к|павильон', normalized) and re.search(r'полностью\s+подготовить\s+точку|весь\s+проект|координиров', normalized):
        return dict(status='unknown', operator_scope='custom_project', reason='Комплексная подготовка коммерческой точки вне перечня мелких работ: оператор согласует проект', rules=['DOC-L0452', 'DOC-L0453'], items=[])
    procurement=re.search(r'\bкуп(?:ить|ите)\b[^.!?\n]{0,100}\b(?:повес|повеш|провест|установ|собра|замен)\w*',normalized)
    if (direction=='mnc' and procurement
            and not re.search(r'\b(?:я|хочу|хотим)\b[^.!?\n]{0,35}$',normalized[:procurement.start()])):
        return dict(status='unknown',operator_scope='procurement',
                    reason='В составе работ клиент поручает закупку: оператор уточняет материалы, исполнителя закупки и весь объём; покупку и выполнение всего за один визит не обещаем',
                    rules=['DOC-L0452','DOC-L0453','DOC-L0459','DOC-L0463'],items=[])
    if direction == 'mnc' and re.search(r'(?:установ|подключ|замен)\w*.{0,35}(?:светодиодн|светящ)\w*\s+лент', normalized):
        return dict(status='unknown', operator_scope='unreviewed_lighting', reason='Монтаж светодиодной ленты требует проверки условий: не пропускаем отдельную работу в составе заказа', rules=['DOC-L0452', 'DOC-L0463'], items=[])
    housing = re.search(r'(?:замен|ремонт)\w*.{0,25}корпус|корпус\w*.{0,20}(?:лопнул|поврежден|разбит|треснул)|(?:лопнул|поврежден|разбит|треснул)\w*.{0,20}корпус', normalized)
    technical = direction == 'bt' or re.search(r'компьют|ноутбук|телевиз|принтер|машинк|стирал|холодиль|бойлер', normalized)
    if housing and technical and not re.search(r'корпус\w*\s+(?:шкаф|комод|мебел)', normalized):
        item = dict(id='housing', family='any', profile='shared', status='agree', primary_refs=['DOC-L0467'], questions=[])
        return dict(status='agree', reason='Ремонт или повреждение корпуса техники требует согласования с филиалом', rules=['DOC-L0467'], items=[item])
    if (re.search(r'телевиз', str(known.get('title') or ''), re.IGNORECASE)
            and (re.search(r'экран|полоск|алиса\s+отвечает', normalized)
                 or re.search(r'подсветк',normalized) and not re.search(r'лент|шкаф|кухон|мебел|кроват',normalized))
            and not re.search(r'телевиз|\bтв\b|телефон|смартфон|монитор|ноутбук|планшет|компьют|клавиатур|\bпк\b', normalized)):
        normalized += '\nтелевизор'
    if (direction == 'bt' and re.search(r'духов|плит', str(known.get('title') or ''), re.I)
            and re.search(r'поджиг', normalized, re.I)
            and not re.search(r'плит|духов|вароч|кот[её]л|колонк|бойлер|зажигалк|каменк|саун|горелк|камин', normalized, re.I)):
        normalized += '\nдуховка'
    matches = [
        r
        for r in data()["rules"]
        if re.search(r["match"], normalized, re.IGNORECASE | re.DOTALL)
        and not (
            r.get("exclude")
            and re.search(r["exclude"], text, re.IGNORECASE | re.DOTALL)
        )
    ]
    if (office_installation_request(normalized) or office_fault_request(normalized)) and not any(r['id'] == 'pc' for r in matches):
        matches.append(next(r for r in data()['rules'] if r['id'] == 'pc'))
    if direction == 'mnc' and not any(r['id'] == 'mnc-connect' for r in matches):
        # A requested connection is not appliance repair. Keep this alias
        # local to the operation/device clause; a past connection is no order.
        appliance = r'(?:стиральн\w*|стиралк\w*|стир\.?\s*машин\w*|посудомо\w*|сушильн\w*|бойлер\w*|водонагрев\w*|электроплит\w*|варочн\w*)'
        for clause in re.split(r'[,!?;\n]+', re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', normalized)):
            operation = re.search(r'\bподсоедин(?:ить|ите|ени[ея])\b', clause)
            if (operation and re.search(appliance, clause)
                    and not re.search(r'\bне\s+(?:(?:надо|нужно|требуется|хочу)\s+)?$', clause[:operation.start()])
                    and not re.search(r'\b(?:мастер|сосед)\w*[^.!?\n]{0,25}(?:сказал|предложил)', clause)):
                matches.append(next(r for r in data()['rules'] if r['id'] == 'mnc-connect'))
                break
    if direction == 'mnc' and _household_supply_context(normalized):
        if not any(r['id'] == 'electric' for r in matches):
            matches.append(next(r for r in data()['rules'] if r['id'] == 'electric'))
        # Past/passive connection describes the existing supply. An explicit
        # new connection/installation job remains a separate requested work.
        connection_words = r'\b(?:подключить|подключите|подключать|подключение|подсоединить|установить|установите|установка|установку)\b'
        connection_request = any(
            not re.search(r'\bне\s+(?:(?:нужно|надо|хочу|требуется)\s+)?$', normalized[max(0, m.start()-30):m.start()])
            and not re.match(r'\s+(?:ничего\s+)?не\s+(?:нужно|надо|требуется)', normalized[m.end():])
            for m in re.finditer(connection_words, normalized))
        if not connection_request:
            repair_clauses = [c for c in re.split(r'[.!?\n;]+|\b(?:также|еще|отдельно)\b', normalized)
                              if re.search(r'\b(?:ремонт\w*|почин\w*|отремонтир\w*)', c)]
            matches = [r for r in matches if r['id'] not in ('mnc-connect', 'washer-connect')
                       and (r['family'] not in ('washer', 'dishwasher')
                            or any(re.search(r['match'], c, re.I) for c in repair_clauses))]
    if any(r['id'] == 'lighting-symptom' for r in matches):
        household = bool(direction == 'mnc' and (
            re.search(r'электрик|электромонтаж', str(known.get('title') or ''), re.I)
            or re.search(r'ванн|комнат|кухн|прихож|квартир|коридор|спальн', normalized, re.I)))
        explicit_device = re.search(r'телевиз|индикатор|ноутбук|монитор|машин|стирал|посудомо|духов|холодил|\bплит', normalized, re.I)
        named_electrics = any(r['id'] in ('light', 'electric', 'sockets') for r in matches)
        if not household or explicit_device or named_electrics:
            matches = [r for r in matches if r['id'] != 'lighting-symptom']
    if vending_scope:
        # Coffee vendors are not circuit breakers merely because both can be
        # called "автомат". Re-test the remainder for independent wiring work.
        non_vendor = re.sub(r'\b(?:кофейн\w*\s+(?:торгов\w*\s+)?|торгов\w*\s+(?:кофейн\w*\s+)?)автомат\w*|'
                            r'\bавтомат\w*\s+(?:по\s+продаже\s+)?кофе\b','[COFFEE_MACHINE]',normalized,flags=re.I)
        matches=[r for r in matches if r['id']!='electric' or re.search(r['match'],non_vendor,re.I|re.S)]
        if vending_scope=='vending':
            matches=[r for r in matches if r['id']!='coffee']
            matches.append(dict(id='coffee-vending',family='coffee',profile='bt',status='agree',
                                primary_refs=['DOC-L0466','OWNER-COFFEE-VENDING-20261019'],questions=[]))
        else:
            if not any(r['id']=='coffee' for r in matches):
                matches.append(next(r for r in data()['rules'] if r['id']=='coffee'))
            matches=[dict(r,primary_refs=list(dict.fromkeys(r['primary_refs']+['OWNER-COFFEE-VENDING-20261019'])))
                     if r['id']=='coffee' else r for r in matches]
        if vending_scope=='unclear':
            matches=[dict(r,questions=['coffee_vending']+r['questions'],
                          primary_refs=r['primary_refs']+['OWNER-COFFEE-VENDING-20261019'])
                     if r['id']=='coffee' else r for r in matches]
    if any(r['family']=='tv' for r in matches):
        server_clauses=[]
        for clause in re.split(r'[.!?\n]+',normalized):
            if re.search(r'телевиз|\bтв\b|\btv\b',clause,re.I):
                clause=re.sub(r'не\s+(?:может\s+)?(?:найти|находит|видит|подключ\w*)(?:\s+к)?\s+сервер\w*|'
                              r'сервер\w*\s+(?:недоступен|не\s+найден|не\s+отвечает)','[REMOTE_SERVICE_ERROR]',clause,flags=re.I)
            server_clauses.append(clause)
        server_scope='\n'.join(server_clauses)
        matches=[r for r in matches if r['id']!='pc-server' or re.search(r['match'],server_scope,re.I)]
    if direction == 'kp' and any(r['id'] in ('pc', 'tv', 'printer', 'monitor') for r in matches):
        # Device use does not establish a second household task. Retest the
        # remainder so genuinely requested furniture/socket work survives.
        household = re.sub(r'\b(?:запускается|загружается|появляется|открывается)\s+рабочий\s+стол\b',
                           '[DESKTOP_UI]', normalized, flags=re.I)
        unplug = r'(?:вытаскивал|вытащил|вынимал|вынул|выдернул|отключал)\w*'
        household = re.sub(r'\bиз\s+розетк\w*\s+(?:(?:я|его|е[её])\s+)?' + unplug,
                           '[DEVICE_POWER_TEST]', household, flags=re.I)
        household = re.sub(r'\b' + unplug + r'[^.!?\n;,]{0,35}\bиз\s+розетк\w*',
                           '[DEVICE_POWER_TEST]', household, flags=re.I)
        matches = [r for r in matches if r['id'] not in ('furniture', 'sockets')
                   or re.search(r['match'], household, re.I | re.S)]
    if (direction == 'mnc' and any(r['id'] == 'towel' for r in matches)
            and re.search(r'(?:демонт\w*|снять|замен\w*|установ\w*)[^.!?\n]{0,35}полотенце\s*сушител', normalized)):
        work = r'(?:замен|помен|установ|демонт|снять|ремонт|почин)\w*'
        tap = r'(?:кран|смесител|сифон)\w*'
        pipe = r'труб\w*'
        explicit = lambda noun: re.search(work + r'[^.!?\n]{0,30}\b' + noun + r'|\b' + noun +
                                          r'[^.!?\n]{0,30}(?:замен|помен|ремонт|теч[её]т|лопнул|сломан|текущ)', normalized, re.I)
        matches = [r for r in matches if r['id'] not in ('plumbing-tap', 'pipes')
                   or explicit(tap if r['id'] == 'plumbing-tap' else pipe)]
    if (direction == 'mnc' and re.search(r'\bвыбило\s+свет\b|\bв\s+половин\w*\s+дома\s+(?:нет\s+света|свет\s+есть)', normalized)
            and not any(r['id'] == 'electric' for r in matches)):
        matches.append(next(r for r in data()['rules'] if r['id'] == 'electric'))
    kitchen_object = re.sub(r'\b(?:на|в)\s+кухне\b', '[ROOM]', normalized)
    matches = [r for r in matches if r['id'] != 'kitchen' or re.search(r['match'], kitchen_object, re.I | re.S)]
    if direction == 'mnc' and any(r['id'] == 'sink' for r in matches):
        sink_work = _without_siphon_fixture_locations(normalized)
        matches = [r for r in matches if r['id'] != 'sink' or re.search(r['match'], sink_work, re.I | re.S)]
    if direction == 'mnc' and any(r['id'] == 'window' for r in matches):
        window_handle_free = re.sub(r'\bручк\w*\s+(?:окна|окон|окошк\w*)|\b(?:окна|окон)\s+ручк\w*', '[WINDOW_HANDLE]', normalized)
        matches = [r for r in matches if r['id'] != 'body-handles' or re.search(r['match'], window_handle_free, re.I | re.S)]
    if (direction == 'mnc' and re.search(r'\bкухню\b|кухонн\w*\s+гарнитур|\bкухня\b[^.!?\n]{0,30}не\s+собрана', normalized)
            and re.search(r'\b(?:разобрать|собрать|сборк\w*|демонтаж)\b', normalized)
            and not any(r['id'] == 'kitchen' for r in matches)):
        # Free word order can describe a kitchen as the actual object, while
        # "на кухне собрать стол" describes only the room.
        matches.append(next(r for r in data()['rules'] if r['id'] == 'kitchen'))
    if direction == 'mnc' and assembled_kitchen_adjustment(normalized):
        matches = [r for r in matches if r['id'] != 'kitchen']
        if not any(r['id'] == 'furniture' for r in matches):
            matches.append(next(r for r in data()['rules'] if r['id'] == 'furniture'))
    if any(r['id'] == 'monitor' for r in matches):
        compared = re.sub(r'\bкак\s+в\s+компьютерн\w*\s+блок\w*\s+питани\w*',
                          '[DEVICE_COMPARISON]', normalized, flags=re.I)
        matches = [r for r in matches if r['id'] != 'pc' or re.search(r['match'], compared, re.I | re.S)]
    if (direction == 'kp' and any(r['id'] == 'pc' for r in matches)
            and re.search(r'power\s+saving\s+mode|no\s+signal|нет\s+сигнала', normalized, re.I)
            and not re.search(r'(?:ремонт|почин|замен)\w*[^.!?\n]{0,20}монитор|'
                              r'монитор[^.!?\n]{0,35}(?:сломан|разбит|гнезд|разъ[её]м|матриц|плат|подсвет)', normalized, re.I)):
        # An observed display message in an explicit PC request is evidence
        # of one signal-path problem, not a diagnosis or a second repair.
        matches = [r for r in matches if r['id'] != 'monitor']
    if any(r['family'] in ('washer', 'dishwasher') and r['profile'] == 'bt' for r in matches):
        # A machine's replaceable hose is an appliance part. Re-test the
        # remainder so another tap/filter/hose request is not erased.
        appliance_hose_free = re.sub(r'\b(?:(?:сливн|заливн|наливн)\w*\s+)?шланг\w*\s+(?:у\s+)?(?:стиральн\w*|посудомоечн\w*)\s+машин\w*|'
                                    r'\b(?:стиральн\w*|посудомоечн\w*)\s+машин\w*\s+(?:(?:сливн|заливн|наливн)\w*\s+)?шланг\w*',
                                    '[APPLIANCE_PART]', normalized, flags=re.I)
        matches = [r for r in matches if r['id'] != 'plumbing-small' or re.search(r['match'], appliance_hose_free, re.I | re.S)]
    if (direction == 'mnc' and any(r['id'] == 'electric' for r in matches)
            and re.search(r'\bкот[её]л\s+электрическ\w*|электрическ\w*\s+кот[её]л', normalized)
            and re.search(r'\bвыбило\s+свет\b|\b(?:нет|пропал\w*)\s+(?:свет\w*|электричеств\w*)|\bполовин\w*\s+дома\s+свет', normalized)
            and not re.search(r'(?:ремонт|почин|замен|установ|подключ)\w*[^.!?\n]{0,25}\bкот[её]л|\bкот[её]л[^.!?\n]{0,25}(?:ремонт|почин|замен|установ|подключ)|газов', normalized)):
        # Loss of house power can affect the electric boiler. This qualifies
        # the electrical request; it does not diagnose or admit boiler repair.
        matches = [r for r in matches if r['family'] != 'boiler']
    intercom_install = r'(?:установ(?:ить|ите|ка|ку|ки)|устанавливать|монтаж(?:а)?|смонтир(?:овать|уйте)|постав(?:ить|ьте))\b'
    intercom_task = r'(?:' + intercom_install + r'|замен(?:ить|ите|а|у|ы)|подключ(?:ить|ите|ение|ения)|ремонт(?:ировать|а)?|почин(?:ить|ите))\b'
    intercom_clauses = [clause for clause in _requested_work_clauses(normalized, intercom_task)
                        if re.search(intercom_task + r'[^,.!?\n]{0,30}видео\s*домофон|'
                                     r'видео\s*домофон\w*[^,.!?\n]{0,30}' + intercom_task, clause, re.I)]
    if direction == 'mnc' and intercom_clauses:
        # A separate unlisted job cannot disappear behind an accepted TV
        # bracket. An access landmark/code alone never requests this work.
        film_scope = re.sub(r'видео\s*домофон\w*', '[INTERCOM]', normalized, flags=re.I)
        matches = [r for r in matches if r['id'] != 'pc-creation'
                   or re.search(r['match'], film_scope, re.I | re.S)]
        install = any(re.search(intercom_install + r'[^,.!?\n]{0,30}видео\s*домофон|'
                                r'видео\s*домофон\w*[^,.!?\n]{0,30}' + intercom_install, clause, re.I)
                      for clause in intercom_clauses)
        refs = ['DOC-L0453'] + (['OWNER-MNC-VIDEO-INTERCOM-20261022'] if install else [])
        matches.append(dict(id='video-intercom', family='intercom', profile='mnc', status='agree',
                            primary_refs=refs, questions=[]))
    if direction == 'mnc' and _broken_key_extraction_request(normalized):
        opening = r'\b(?:вскры\w*)\b'
        positive_opening = any(re.search(r'замк|замок|двер', clause, re.I)
                               for clause in _requested_work_clauses(normalized, opening))
        if not positive_opening:
            # Removing a fragment without opening/replacing is its own job.
            # A real opening request still retains the documented refusal.
            replacement = r'\b(?:заменить|замена|замену|поменять|установить|установка|установку|починить|ремонт)\b'
            separate_lock_work = any(re.search(r'замок|замк', clause, re.I)
                                     for clause in _requested_work_clauses(normalized, replacement))
            matches = [r for r in matches if r['id'] != 'lock-open'
                       and (r['id'] != 'lock' or separate_lock_work)]
            matches.append(dict(id='key-fragment', family='key_fragment', profile='mnc', status='agree',
                                primary_refs=['OWNER-MNC-KEY-FRAGMENT-20261022'], questions=[]))
    if direction == 'mnc' and any(r['id'] in ('lock', 'lock-cut') for r in matches):
        # A door fitting is not an appliance handle. Preserve separately
        # named appliance work, and strip only explicit negations of cutting.
        appliance_remainder = re.sub(
            r'[^.!?\n]*(?:межкомнатн|входн|двер)[^.!?\n]*', '', normalized)
        appliance_named = re.search(r'холодильник|стиральн|посудомо|духов|микроволн|бойлер', normalized)
        matches = [r for r in matches if r['id'] != 'body-handles' or appliance_named
                   or re.search(r['match'], appliance_remainder, re.I | re.S)]
        positive_cutting = re.sub(
            r'\bбез\s+врезк\w*|\bврезк\w*\s+не\s+(?:нужна|требуется)|'
            r'\bне\s+(?:нужна\s+)?врезк\w*', '', normalized)
        matches = [r for r in matches if r['id'] != 'lock-cut'
                   or re.search(r['match'], positive_cutting, re.I | re.S)]
    if (direction == 'kp' and re.search(r'материнск\w*\s+плат|сокет\w*\s+процессор', normalized)
            and not re.search(r'телевиз|\bтв\b|телефон|смартфон|планшет', normalized)
            and not any(r['id'] == 'pc' for r in matches)):
        # DOC-L0124 includes PC components even when the customer names only
        # the board/socket. A marked pin is not proof of repairability.
        matches.append(next(r for r in data()['rules'] if r['id'] == 'pc'))
    if direction == 'kp' and re.search(r'сканер|сканирован', normalized):
        household = r'электропровод|проводк|щиток|люстр|светиль|коридор|потол|комнат|на\s+кухн'
        remainder = '\n'.join(c for c in re.split(r'[.!?\n;]+|\b(?:также|еще|отдельно)\b', normalized)
                              if not re.search(r'скан|usb|каретк|scangear|macbook|windows|драйвер', c)
                              or re.search(household, c))
        # The scanner lamp and tested USB lead belong to the scanner repair;
        # independently requested house lighting/wiring stays in the remainder.
        matches = [r for r in matches if r['family'] not in ('electric', 'bulb')
                   or re.search(r['match'], remainder, re.I | re.S)]
    if (direction=='mnc' and re.search(r'(?:прикле|накле)\w*[^.!?\n]{0,25}уголк\w*[^.!?\n]{0,25}окн|уголк\w*[^.!?\n]{0,25}окн\w*[^.!?\n]{0,25}(?:прикле|накле)|уголк\w*[^.!?\n]{0,25}(?:прикле|накле)\w*[^.!?\n]{0,25}окн',normalized,re.I)):
        matches.append(dict(id='window-trim',family='windows',profile='mnc',status='agree',primary_refs=['DOC-L0372','DOC-L0453'],questions=[]))
    if any(r['id'] in ('printer', 'tv') for r in matches):
        # A device indicator is a symptom, not an independent
        # household lamp request. Retain any separately named lighting work.
        lamp_symptom = (r'\b(?:индикаторн\w*\s+)?(?:лампочк|ламп)\w*(?:\s+индикатора)?\s+(?:морга\w*|мига\w*|загора\w*|тухн\w*|гасн\w*)|'
                        r'\b(?:морга\w*|мига\w*|загора\w*|тухн\w*|гасн\w*)\s+(?:индикаторн\w*\s+)?(?:лампочк|ламп)\w*(?:\s+индикатора)?')
        household = r'коридор|комнат|потол|кухн|ванн|люстр|светильник|подъезд'
        lamp_job = r'(?:замен|помен|установ|повес)\w*[^.!?\n]{0,25}(?:лампочк|ламп)'
        lamp_free = '\n'.join(
            clause if re.search(household + '|' + lamp_job, clause, re.I) else re.sub(lamp_symptom, '[DEVICE_INDICATOR]', clause, flags=re.I)
            for clause in re.split(r'[.!?\n;]+', normalized))
        matches = [r for r in matches if r['id'] != 'bulb' or re.search(r['match'], lamp_free, re.I | re.S)]
    if any(r['id']=='printer' for r in matches):
        from qualification_state import printer_problem_match
        stated_printer_problem = printer_problem_match(normalized)
        setup_text = re.sub(r'\bне\s+(?:(?:нужно|надо|хочу|требуется)\s+)?(?:подключ\w*|настро\w*)|'
                            r'\b(?:подключ\w*|настройк\w*)\s+не\s+(?:надо|нужно|нужна|требуется)',
                            '', normalized, flags=re.I)
        separate_setup = re.search(r'подключ|настро|установ\w*[^.!?\n]{0,25}драйвер', setup_text, re.I)
        # Paper jams request physical printer work. DOC-L0189's host routing
        # applies only if connection/setup is independently requested as well.
        if (stated_printer_problem and (stated_printer_problem.lastgroup != 'paper_feed' or not separate_setup)):
            matches = [dict(r, questions=[q for q in r['questions'] if q != 'printer_connection'])
                       if r['id'] == 'printer' else r for r in matches]
        if (re.search(r'не\s+печата|ремонт|слом|полом|ролик\w*\s+(?:захват\w*|подач\w*)\s+бумаг', normalized)
                and not re.search(r'подключ|настро|установ\w*[^.!?\n]{0,25}драйвер', normalized)):
            matches = [dict(r, questions=[q for q in r['questions'] if q != 'printer_connection'])
                       if r['id'] == 'printer' else r for r in matches]
        ink_free=re.sub(r'\bтрубк\w*(?=[^.!?\n]{0,65}(?:чернил|краск))','[INK_PATH]',normalized,flags=re.I)
        matches=[r for r in matches if r['family']!='pipes' or re.search(r['match'],ink_free,re.I|re.S)]
        cartridge_scope=re.sub(r'\bпосле\s+(?:переза|за)правк\w*\s+(?:черн\w*\s+)?картридж\w*','[PAST_CARTRIDGE_SERVICE]',normalized,flags=re.I)
        cartridge_task=re.search(r'(?:заправ|замен|ремонт|почин|прошив)\w*(?:(?!принтер)[^.!?\n]){0,20}(?:картридж|тонер)|(?:картридж|тонер)\w*[^.!?\n]{0,20}(?:заправ|замен|ремонт|почин|прошив)',cartridge_scope,re.I)
        cartridge_task=cartridge_task or (re.search(r'картридж|тонер',cartridge_scope,re.I) and re.search(r'\b(?:переза|за)прав(?:ить|ьте|ка)\b|\bпрош(?:ить|ивка)\b',cartridge_scope,re.I))
        if not cartridge_task:
            matches=[r for r in matches if r['id']!='printer-cartridge']
    if any(r['id']=='furniture' for r in matches):
        pc_free=re.sub(r'\b(?:компьютерн\w*\s+(?:стол|кресл)\w*|(?:стол|кресл)\w*\s+компьютерн\w*)\b','[FURNITURE_TYPE]',normalized,flags=re.I)
        matches=[r for r in matches if r['family']!='pc' or re.search(r['match'],pc_free,re.I|re.S)]
    if direction == 'bt' and any(r['id'] == 'boiler' for r in matches):
        power_context_free = re.sub(
            r'(?:при|после)\s+включени\w*\s+в\s+розет\w*|'
            r'включ(?:ил|али|аем|аю)\w*\s+(?:его\s+)?в\s+розет\w*|'
            r'подключен\w*\s+к\s+розет\w*', '[POWER_CONNECTION]', normalized)
        wiring_context_free = power_context_free
        if power_context_free != normalized:
            wiring_context_free = re.sub(r'\bзамкну\w*\s+провод(?:а|ы|ов)\b',
                                         '[APPLIANCE_SYMPTOM]', power_context_free)
        lock_context_free = re.sub(r'\bзамкну\w*\b|\bзамыка\w*\b', '[SHORT_CIRCUIT]', normalized)
        for family, remainder in [('sockets', power_context_free), ('electric', wiring_context_free),
                                  ('lock', lock_context_free)]:
            matches = [r for r in matches if r['family'] != family or re.search(r['match'], remainder, re.I | re.S)]
    if (direction == 'mnc' and any(r['id']=='mnc-connect' for r in matches)
            and re.search(r'электроплит|варочн|духов',normalized)
            and not re.search(r'стиральн|посудомо|бойлер|водонагрев|сушильн',normalized)):
        matches = [dict(r,questions=['electrics_ready']) if r['id']=='mnc-connect' else r for r in matches]
        socket_free = re.sub(r'\bрозетк\w*\s+(?:уже\s+)?(?:есть|готов\w*)\b','[READY_SOCKET]',normalized)
        matches = [r for r in matches if r['id']!='sockets' or re.search(r['match'],socket_free,re.I)]
    if direction == 'kp' and gpu_software_only(normalized):
        matches = [r for r in matches if r['family'] != 'gpu']
        if not any(r['family'] == 'pc' for r in matches):
            matches.append(next(r for r in data()['rules'] if r['id'] == 'pc'))
    # A desktop iCloud context is not a second, independently requested phone
    # service. Keep independently named phones/tablets and their own actions.
    if (direction == 'kp' and re.search(r'моноблок|макбук|macbook', normalized)
            and re.search(r'icloud|айклауд|айклад', normalized)
            and not re.search(r'смартфон|айфон|iphone|ipad|планшет', normalized)):
        matches = [r for r in matches if r['id'] not in ('phone-access', 'pc')]
        if not any(r['id'] == 'pc-icloud' for r in matches):
            matches.append(next(r for r in data()['rules'] if r['id'] == 'pc-icloud'))
    furniture_text = _furniture_without_plumbing_support(re.sub(r'духов\w*\s+шкаф\w*', '[OVEN]', normalized))
    matches = [r for r in matches if r['id'] != 'furniture'
               or re.search(r['match'], furniture_text, re.I | re.S)
               or direction == 'mnc' and assembled_kitchen_adjustment(furniture_text)]
    if any(r['id'] == 'furniture' for r in matches):
        hanging_text = _hanging_without_cabinet_mirrors(normalized)
        matches = [r for r in matches if r['id'] != 'hanging'
                   or re.search(r['match'], hanging_text, re.I | re.S)]
    if (furniture_assembly_request(normalized) and re.search(r'шкаф', normalized)
            and not re.search(r'повес|навес|закреп|настенн|подвесн|прикрут\w*[^.!?\n]{0,20}стен', normalized)):
        # Shelves inside the described cabinet do not request a second job.
        without_shelves = re.sub(r'\bполк\w*\b', '[FURNITURE_PART]', normalized)
        matches = [r for r in matches if r['id'] != 'hanging' or re.search(r['match'], without_shelves, re.I | re.S)]
    light_text = re.sub(r'\bв\s+(?:люстр|светильник)\w*', '[FIXTURE]', normalized)
    if any(r['id'] == 'bulb' for r in matches):
        matches = [r for r in matches if r['id'] != 'light' or re.search(r['match'], light_text, re.I | re.S)]
    # DOC-L0350 covers brackets for more than televisions. A curtain bracket
    # without a TV does not add a second TV service requiring approval.
    tv_mount_requested=any(re.search(
        r'(?:повес|повеш|навес|креплен|закреп|установ|кронштейн)\w*.{0,40}(?:телевиз|\bтв\b|\bтелек\b)|'
        r'(?:телевиз|\bтв\b|\bтелек\b).{0,40}(?:повес|повеш|навес|креплен|закреп|установ|кронштейн)', clause)
        for clause in re.split(r'[,.;\n]+',normalized))
    # Avito's hanging questionnaire names the TV and bracket as one option.
    tv_mount_requested = tv_mount_requested or bool(re.search(
        r'^\s*(?:-\s*)?(?:телевизор|тв|телек)\s*,\s*кронштейн\s*$', normalized, re.M))
    if tv_mount_requested and not any(r['id'] == 'tv-mount' for r in matches):
        matches.insert(0, next(r for r in data()['rules'] if r['id'] == 'tv-mount'))
    if direction == 'mnc' and not tv_mount_requested:
        matches = [dict(r, id='hanging', family='hanging', profile='mnc', status='accept',
                        primary_refs=['DOC-L0350', 'DOC-L0352', 'DOC-L0353'], questions=['wall'])
                   if r['id'] == 'tv-mount' else r for r in matches]
    if re.search(r'корпус\w*\s+(?:шкаф|комод|мебел)', normalized):
        matches = [r for r in matches if r['id'] != 'body-handles']
    if any(r['id'] == 'countertop-cut' for r in matches) and not re.search(r'(?:подключ|ремонт|замен)\w*.{0,30}газов|газов\w*.{0,30}(?:подключ|ремонт|замен)', normalized):
        matches = [r for r in matches if r['id'] != 'gas']
    # Assembly of shelf furniture is not its installation on a wall.
    shelf_assembly = re.search(r'(?:собра|сборк)\w*.{0,25}пол(?:к|ок)|полк\w*.{0,25}(?:собра|сборк)', normalized)
    if direction == 'mnc' and shelf_assembly and not re.search(r'повес|навес|на\s+стен|к\s+стене|крепить', normalized):
        matches = [r for r in matches if r['family'] != 'hang']
        matches.append(next(r for r in data()['rules'] if r['id'] == 'furniture'))
    if any(r['id'] == 'drain' for r in matches) and not re.search(r'(?:замен|установ|ремонт|почин|креплен|сместил|гофр|бачок|кнопк)\w*.{0,30}унитаз|унитаз\w*.{0,30}(?:замен|установ|ремонт|почин|креплен|сместил|гофр|бачок|кнопк)', normalized):
        matches = [r for r in matches if r['id'] != 'toilet']
    # A room or a nearby fixture describes location, not a second job.
    # Re-run only the affected rule after removing those exact locatives;
    # an independently requested bath/radiator job still survives.
    location_free = re.sub(r"\bв\s+ванн(?:ой(?:\s+комнате)?|ую(?:\s+комнату)?)\b", "[ROOM]", normalized)
    radiator_free = re.sub(r"\b(?:над|под|около|возле|за)\s+радиатор(?:ом|ами)\b", "[LOCATION]", normalized)
    location_free = re.sub(r'\bдвер\w*\s+(?:туалет\w*\s+)?ванн\w*\b', '[ROOM_DOOR]', location_free)
    washer_free = re.sub(r'\b(?:над|под|около|возле|за)\s+стиральн\w*\s+машин\w*\b', '[LOCATION]', normalized, flags=re.I)
    matches = [r for r in matches if not (
        r['id'] == 'bath' and not re.search(r['match'], location_free, re.IGNORECASE | re.DOTALL)
        or r['id'] == 'pipes-riser' and not re.search(r['match'], radiator_free, re.IGNORECASE | re.DOTALL)
        or r['family'] == 'washer' and not re.search(r['match'], washer_free, re.IGNORECASE | re.DOTALL)
    )]
    # An antenna/cable-TV lead is not automatically a separate electrician
    # order. Preserve actual power wiring, sockets and independent cable work.
    cable_tv = re.search(r"подключен\w*\s+кабельное|кабельн\w*\s+(?:тв|телевид\w*)|антенн", normalized)
    if direction == 'kp' and any(r['family'] == 'printer' for r in matches):
        cord_context = r'повис\w*\s+на\s+кабел|(?:новый|другой)\s+кабел\w*\s+подключили'
        current_work = r'розетк|электропровод|проводк|\bщит\w*|силов|220|пролож|штроб|замен|помен|нужн|требу|подключить|подключите'
        remaining = '\n'.join(c for c in re.split(r'[.!?\n;,]+', normalized)
                              if not re.search(cord_context, c, re.I) or re.search(current_work, c, re.I))
        matches = [r for r in matches if r['id'] != 'electric' or re.search(r['match'], remaining, re.I)]
    electric_text = normalized
    if any(r['id'] == 'monitor' for r in matches):
        electric_text = '\n'.join(
            clause if re.search(r'розетк|электропровод|проводк|\bщит\w*|автомат|силов|220|пролож|проклад|штроб', clause, re.I)
            else re.sub(r'\b(?:провод|кабел)\w*\s+питани\w*|\b(?:вход|блок|район\w*)\s+питани\w*', '[DEVICE_POWER]', clause, flags=re.I)
            for clause in re.split(r'[.!?\n;]+', compared))
    independent_electric = re.search(r"розетк|электропровод|проводк|\bщит\w*|автомат|силов|питан|220|пролож|проклад|штроб|поменять.{0,20}кабел|замен.{0,20}кабел", electric_text)
    if (direction == 'mnc' and re.search(r'выключател|розетк|электропровод|силов|220', normalized)
            and not re.search(r'интернет|оптоволок|вит\w*\s+пар|rj.?45|патч.?корд|сетев\w*\s+кабел', normalized)):
        # DOC0166/0311 concern Internet leads. A mains switch wire does not
        # establish one; retain separate unqualified cable clauses for review.
        separate = re.search(r'\b(?:еще|отдельно|также)\b[^.!?\n]{0,100}(?:кабел|провод)', normalized)
        if not separate:
            matches = [r for r in matches if r['id'] == 'electric' or r['family'] != 'cable']
    if (direction == 'kp' and any(r['family'] in ('router','monitor') for r in matches)
            and not independent_electric):
        # Tested/existing technical leads are context, not household wiring.
        matches = [r for r in matches if r['id'] != 'electric']
    toilet_work = re.sub(r'\b(?:слив\w*\s+|с\s+)унитаз\w*', '[PIPE_CONNECTION]', normalized)
    if any(r['id'] == 'pipes' for r in matches) and not re.search(
            r'(?:замен|установ|помен|почин|ремонт|демонт|врез)\w*.{0,25}(?:раковин|мойк)|'
            r'(?:раковин|мойк)\w*.{0,25}(?:замен|установ|помен|почин|ремонт|демонт|врез)', normalized):
        # Not using the sink because its drain leaks requests pipe work only.
        matches = [r for r in matches if r['id'] != 'sink']
    if any(r['id'] == 'pipes' for r in matches) and not re.search(
            r'(?:замен|установ|помен|ремонт|почин|демонт)\w*[^.!?\n]{0,20}унитаз|'
            r'унитаз\w*[^.!?\n]{0,20}(?:замен|установ|помен|ремонт|почин|демонт)|'
            r'бачок|кнопк|арматур|инсталляц', toilet_work):
        matches = [r for r in matches if r['id'] != 'toilet']
    if any(r['id'] == 'drain' for r in matches) and not re.search(
            r'(?:замен|установ|помен|ремонт|демонт)\w*[^.!?\n]{0,25}(?:раковин|мойк)|'
            r'(?:раковин|мойк)\w*[^.!?\n]{0,25}(?:замен|установ|помен|ремонт|демонт)', normalized):
        matches = [r for r in matches if r['id'] != 'sink']
    if direction == 'kp' and cable_tv and not independent_electric and any(r['family'] == 'tv' and r['profile'] in (direction, 'shared') for r in matches):
        matches = [r for r in matches if r['id'] != 'electric']
    # Existing network wiring is a router prerequisite, not new electrical
    # work. Remove only the completed clause, then re-test the electric rule.
    if direction == 'kp' and any(r['family'] == 'router' for r in matches):
        anaphoric_firmware = re.search(r'(?:роутер|router)[^.!?\n]{0,120}\bего\s+(?:прошивк|ремонт)', normalized, re.I)
        if anaphoric_firmware and not re.search(r'телевиз|компьютер|\bпк\b|\bps[345]?\b', anaphoric_firmware[0], re.I):
            matches = [r for r in matches if r['family'] != 'router']
            matches.append(next(r for r in data()['rules'] if r['id'] == 'router-repair'))
        ready_free = re.sub(r"(?:^|(?<=[.!?\n,;]))\s*проводка\s+(?:вся\s+)?(?:уже\s+)?(?:проведена|готова)\s*(?=[.!?\n;]|$|,\s*провайдер\b)", "[NETWORK_READY]", normalized)
        ready_free = re.sub(r'\b(?:да\s+есть\s*[,;]?\s*)?кабельный\b', '[NETWORK_TYPE]', ready_free)
        matches = [r for r in matches if r['id'] != 'electric' or re.search(r['match'], ready_free, re.IGNORECASE | re.DOTALL)]
        console = r'(?:playstation|\bps[345]?\b|\bпс\s*[345]\b|nintendo|switch|steam.?deck|xbox)'
        operation = r'(?:почист|чистк|термопаст|ремонт|почин|разобра|прошив|настро|замен)\w*'
        candidates = re.finditer(r'(?=(' + operation + r'[^.!?\n;]{0,45}' + console
                                 + r'|' + console + r'[^.!?\n;]{0,45}' + operation + r'))', normalized, re.I)
        independent_console = any(not re.search(r'роутер|router', m[1], re.I) for m in candidates)
        if not independent_console:
            matches = [r for r in matches if r['family'] != 'console']
        if not re.search(r'телевиз|\bтв\b|ресивер|тюнер|кинотеатр', normalized, re.I):
            setup_text = re.sub(r'приставк\w*\s*' + console, '[CONSOLE_CONTEXT]', normalized, flags=re.I)
            matches = [r for r in matches if r['id'] != 'tv-setup' or re.search(r['match'], setup_text, re.I | re.S)]
    if direction == 'kp' and any(r['family'] == 'cable' and r['profile'] == 'kp' for r in matches) and not independent_electric:
        matches = [r for r in matches if not (r['family'] == 'electric' and r['profile'] == 'mnc')]
    if direction == 'kp' and re.search(r'\bhdmi\b|материнк|материнск\w*\s+плат', normalized):
        # A video lead inside a PC complaint is not household electrical
        # wiring. Re-test the remainder to preserve an independent power job.
        remainder = '\n'.join(c for c in re.split(r'[.!?\n;,]+|\b(?:также|еще|отдельно)\b', normalized)
                              if not re.search(r'\bhdmi\b|материнк|материнск\w*\s+плат', c)
                              or re.search(r'розетк|электропровод|проводк|щиток|автомат|силов|220|пролож|штроб|светиль|люстр', c))
        matches = [r for r in matches if r['id'] != 'electric' or re.search(r['match'], remainder, re.IGNORECASE)]
    if re.search(r'монитор', normalized) and not re.search(r'матриц|разбит', normalized):
        # DOC0156 covers a matrix repair, not a diagnosis inferred from bands.
        matches = [r for r in matches if r['id'] != 'monitor-matrix']
    # A washing-machine latch is not a second order for a door locksmith.
    # Keep genuinely separate or ambiguous lock work in the mixed-service path.
    if any(r['family'] == 'washer' for r in matches):
        lock_clauses = [c for c in re.split(r'[.!?\n]+', normalized) if re.search(r'замок|замк', c)]
        if lock_clauses and not re.search(r'входн|межкомнатн|дверн|личинк|(?:также|еще).{0,30}замок', normalized):
            matches = [r for r in matches if r['id'] != 'lock']
    if any(
        r["id"] in ("washer-connect", "oven-connect", "boiler-install")
        for r in matches
        if r["profile"] == direction
    ):
        matches = [r for r in matches if r["id"] != "mnc-connect"]
    if any(r['id']=='drain' for r in matches):
        structural = re.search(r'(?:перенос|перенест|врез|замен|помен|демонт|установ)\w*[^.!?\n]{0,45}(?:стояк|труб)|'
                               r'(?:стояк|труб)\w*[^.!?\n]{0,45}(?:перенос|перенест|врез|замен|помен|демонт|установ)|'
                               r'(?:теч|протек|капает)\w*[^.!?\n]{0,35}труб|труб\w*[^.!?\n]{0,35}(?:теч|протек|капает)',normalized,re.I)
        if not structural and not re.search(r'отоплен|радиатор|батаре',normalized,re.I):
            # DOC0284 covers structural work, not a clog in an iron riser.
            matches=[r for r in matches if r['family']!='pipes']
    # Mandatory global exclusions do not depend on the advertised direction.
    globals_ = [r for r in matches if r["family"] == "any" or r["id"] == "gas"]
    own = [
        r
        for r in matches
        if r["profile"] in (direction, "shared") and r["family"] != "any"
    ]
    if any(r["id"] == "gas" for r in matches):
        own = [r for r in own if r["family"] not in ("oven", "boiler")]
    foreign = [r for r in matches if r["profile"] not in (direction, "shared", "any")]
    # Recovery, printer-to-PC and TV-to-PC connections have one primary service.
    if any(r["id"] == "data" for r in own):
        own = [r for r in own if r["family"] == "data"]
    if any(r["family"] == "printer" for r in own):
        own = [r for r in own if r["family"] != "pc"]
    if any(r["family"] == "console" for r in own):
        own = [r for r in own if r["family"] != "tv"]
    separately_requested_repair = re.search(
        r'\b(?:ремонт|починить|отремонтировать)\s+(?:(?:мою|моей|старую|новую)\s+)?(?:стиральн\w*|стиралк\w*|посудомо\w*|сушильн\w*|бойлер\w*|духов\w*)', normalized)
    if any(r["id"] == "mnc-connect" for r in own) and not separately_requested_repair:
        foreign = [
            r
            for r in foreign
            if r["family"] not in ("washer", "dishwasher", "boiler", "oven")
        ]
    if any(r["family"] == "printer" for r in own):
        own = [r for r in own if r["family"] != "phone"]
    if own and foreign:
        own_families = {r["family"] for r in own}
        foreign = [r for r in foreign if r["family"] not in own_families]
        if any(r["family"] == "tv" for r in own) and re.search(r"подключ", normalized):
            foreign = [r for r in foreign if r["family"] != "pc"]
        own += [dict(r, status="route") for r in foreign]
    chosen = []
    families = set()
    for r in globals_ + own:
        if r["family"] in families:
            continue
        families.add(r["family"])
        chosen.append(
            dict(r, primary_refs=list(r["primary_refs"]), questions=list(r["questions"]))
        )
    if not own and foreign:
        if direction == "mnc" and all(r["profile"] == "bt" for r in foreign):
            city = known.get("city", "")
            if filials.known(city, "bt"):
                return {
                    "status": "route",
                    "reason": "Для бытовой техники есть филиал БТ: оператор проверяет передачу",
                    "rules": ["DOC-L0375", "DOC-L1300", "DOC-L1301"],
                    "items": [],
                    "target_direction": "bt",
                }
            if not filials.known(city, 'mnc'):
                return dict(status='unknown',
                            reason='Не подтверждён город МНЧ без филиала БТ: оператор проверяет перечень филиалов',
                            rules=['DOC-L0375'], items=[])
            for r in foreign:
                if r["family"] not in families:
                    families.add(r["family"])
                    chosen.append(
                        dict(r, primary_refs=list(r["primary_refs"]) + ['DOC-L0375'], questions=list(r["questions"]))
                    )
            for r in chosen:
                if r["family"] == "fridge":
                    r["status"] = "agree"
        else:
            refs = (
                ["DOC-L0252", "DOC-L0253"]
                if direction == "kp"
                else ["DOC-L0702", "DOC-L0704", "DOC-L0705"]
            )
            return {
                "status": "route",
                "reason": "Вид работ относится к другому направлению; оператор проверяет профильный маршрут",
                "rules": refs,
                "items": [],
                "target_direction": foreign[0]["profile"],
            }
    if not chosen:
        return {
            "status": "unknown",
            "reason": "Вид работ вне подтверждённого перечня: нужно согласование с филиалом",
            "rules": ["DOC-L0250", "DOC-L0251"]
            if direction == "kp"
            else ["DOC-L0452", "DOC-L0453"],
            "items": [],
        }
    if (direction == 'kp' and len(chosen) == 1 and chosen[0]['id'] == 'pc'
            and ordinary_windows_installation(normalized)):
        chosen[0]['questions'] = [q for q in chosen[0]['questions'] if q not in ('model', 'keep_data')]
        chosen[0]['primary_refs'] = list(dict.fromkeys(chosen[0]['primary_refs'] + ['DOC-L0125', 'DOC-L0540']))
    if (direction == 'kp' and len(chosen) == 1 and chosen[0]['id'] == 'pc'
            and ordinary_office_work(normalized)):
        chosen[0]['questions'] = [q for q in chosen[0]['questions'] if q not in ('model', 'keep_data')]
        if office_fault_request(normalized):
            chosen[0]['questions'].insert(0, 'office_symptom')
        refs = ['DOC-L0125'] + (['DOC-L0541'] if office_installation_request(normalized) else [])
        chosen[0]['primary_refs'] = list(dict.fromkeys(chosen[0]['primary_refs'] + refs))
    for r in chosen:
        if (direction == 'kp' and r['family'] == 'tv'
                and re.search(r'экран|изображ|картинк|подсветк|полос', normalized)):
            r['questions'] = list(dict.fromkeys([*r['questions'], 'screen_damage']))
            r['primary_refs'] = list(dict.fromkeys([*r['primary_refs'], 'DOC-L0223']))
        if r['id'] == 'kitchen' and re.search(r'врез|выпил|пропил|вырез|отрез', normalized):
            r['questions'] = ['countertop_material'] + r['questions']
        if r['id'] == 'window' and re.search(r'ремонт|почин|устран\w*[^.!?\n]{0,20}неполад|'
                                            r'(?:замок|фурнитур)\w*[^.!?\n]{0,30}не\s+(?:открыва|закрыва)|'
                                            r'не\s+(?:открыва|закрыва)\w*[^.!?\n]{0,30}(?:замок|фурнитур)', normalized):
            r.update(status='agree', primary_refs=r['primary_refs'] + ['DOC-L0372'])
        if (r['id'] == 'furniture' and furniture_repair_request(furniture_text)
                and not re.search(r'\b(?:собрать|собирать|сборк\w*)\b', _assembly_intent_text(furniture_text))):
            r.update(questions=['furniture_problem'], repair_only=True)
        if r['id'] == 'furniture' and re.search(r'повес|повеш|вешать|навес|закреп\w*.{0,20}(?:стен|шкаф)|'
                                               r'прикрут\w*\s+(?:(?:один|\d+|навесн\w*|настенн\w*|кухонн\w*)\s+)?шкаф', furniture_text):
            assembly_scope = re.sub(r'не\s+(?:нужно|надо)\s+собира\w*|собирать\s+не\s+(?:нужно|надо)', '', furniture_text)
            if not re.search(r'собрать|сборк|собира', assembly_scope):
                r.update(questions=['wall'], wall_mount_only=True)
                r['primary_refs'] += ['DOC-L0350','DOC-L0352']
            elif any(not re.search(r'\bуже\s+(?:повес|повеш|навес|закреп|прикрут)', clause, re.I)
                     for clause in _requested_work_clauses(
                         furniture_text, r'\b(?:повес|повеш|вешать|навес|закреп|прикрут)\w*')):
                r['questions'] = list(dict.fromkeys(r['questions'] + ['wall']))
                r['primary_refs'] += ['DOC-L0350', 'DOC-L0352']
        if r['id'] == 'sport' and re.search(r'ремонт|почин|слом', normalized):
            r.update(status='agree', primary_refs=r['primary_refs'] + ['DOC-L0357'])
        if r['family'] == 'tv' and confirmed_tv_bands(text):
            r.update(id='tv-bands', status='refuse', questions=[],
                     primary_refs=['OWNER-TV-BANDS-20261017'])
            continue
        if r["status"] == "conditional_mount":
            # Owner18.10 explicitly includes the television itself on MNC.
            if direction == 'mnc':
                r.update(status='accept',profile='mnc')
                r['primary_refs'].append('OWNER-MNC-TV-MOUNT-20261018')
            else:
                r['status']='agree'
        if r["status"] == "matrix" or r['family'] == 'tv' and confirmed_tv_matrix(text):
            if not confirmed_tv_matrix(text):
                r.update(
                    id="tv",
                    status="qualify",
                    questions=["tv_type", "model", "screen_damage"],
                    primary_refs=["DOC-L0217", "DOC-L0442", "DOC-L0445"],
                )
            elif re.search(r"кинескоп|проекцион|плазм", normalized):
                r["status"] = "agree"
            elif re.search(r'\bжк\b|\bled\b|\boled\b|\bqled\b|\blcd\b', re.sub(r'\bне\s+(?:жк|led|oled|qled|lcd)', '', normalized)):
                r["status"] = "refuse"
                r["primary_refs"] += ["TG1-566", "USER-20261015-TV"]
            else:
                r['status'] = 'agree'
                r['primary_refs'] += ['DOC-L0213', 'DOC-L0214']
        if r["id"] == "printer-cartridge":
            r["primary_refs"] += ["TG1-589"]
        if r["id"] == "tv-satellite":
            r["primary_refs"] += ["TG1-612"]
    refs = list(dict.fromkeys(ref for r in chosen for ref in r["primary_refs"]))
    statuses = {r["status"] for r in chosen}
    if len(chosen) > 1 and not (direction == "mnc" and statuses == {"accept"} and all(r["profile"] == "mnc" for r in chosen)):
        status = "mixed"
        reason = "Несколько работ: сохранить профильную часть, остальные отдельно согласовать; нужен оператор"
        refs += ["DOC-L0463"]
    elif "refuse" in statuses:
        status = "refuse"
        reason = "Прямое исключение по подтверждённому правилу"
    elif "conflict" in statuses:
        status = "conflict"
        reason = (
            "Первичный документ и отдельное объявление расходятся: решение оператора"
        )
    elif "agree" in statuses:
        status = "agree"
        reason = "Услуга требует согласования с филиалом"
    else:
        status = "supported"
        reason = "Условия приёма проверяются по конкретной услуге"
    return {
        "status": status,
        "reason": reason,
        "rules": list(dict.fromkeys(refs)),
        "items": chosen,
    }


def mixed_optional_scope(messages, known, scope_text):
    """Separate ordinary MNC work from an offered, unapproved extra look.

    This does not change catalogue admission, approve an extra service or
    establish client consent. Unknown work outside the owner's concrete
    inspection examples, exclusions and mandatory combined orders stay put.
    All source quotes survive; only the primary-service selection view changes.
    """
    if known.get('direction') != 'mnc' or str(known.get('channel', '')).startswith('max'):
        return None
    from assistant_prices import current_enquiry_messages
    rows = current_enquiry_messages(messages)
    clients = [m for m in rows if m.get('direction') == 'in'
               and m.get('sender_type') not in ('system', 'avito', 'bot', 'operator', 'assistant', 'employee', 'human')
               and m.get('role') not in ('assistant', 'system')]
    # These are inspection boundaries, never execution permissions. General
    # unknown services cannot enter intake through an optional-looking phrase.
    subjects = (
        ('heating', r'отоплен\w*|батаре\w*|радиатор\w*', 'отопление', 'отоплению'),
        ('led_strip', r'(?:светодиодн\w*|светящ\w*)\s+лент\w*', 'светодиодную ленту', 'светодиодной ленте'),
        ('partition', r'(?:реечн\w*\s+)?перегородк\w*', 'перегородку', 'перегородке'),
    )
    literal = str(scope_text or '')
    # Keep compound ordinary services together, but do not consume a second
    # job simply because it shares a sentence with the optional extra.
    operation = r'(?:установ|замен|помен|повес|навес|собра|почин|отремонт|постро|посмотр|подключ)\w*'
    split = (r'[;\n]+|(?<=[.!?])\s+|,\s*(?=' + operation + ')|'
             r'\s+(?:и|а|также|ещ[её])\s+(?=' + operation + ')')
    clauses = re.split(split, literal, flags=re.I)
    withdrawn = set()
    for key, pattern, _, _ in subjects:
        relevant = [str(m.get('body') or m.get('text') or '') for m in clients
                    if re.search(pattern, str(m.get('body') or m.get('text') or ''), re.I)]
        if relevant and not re.search(r'\b(?:без|если)\b', relevant[-1], re.I):
            view = r'(?:смотреть|посмотреть|осматривать|трогать)'
            cancel = (r'(?:' + pattern + r')\s+(?:' + view + r'\s+)?не\s+(?:надо|нужно|требуется)|'
                      r'не\s+(?:надо|нужно)\s+' + view + r'\s+(?:' + pattern + r')|'
                      r'отмен\w*\s+(?:осмотр\s+)?(?:' + pattern + r')')
            if re.search(cancel, relevant[-1], re.I):
                withdrawn.add(key)
    extras, primary = [], []
    for clause in clauses:
        found = next((s for s in subjects if re.search(s[1], clause, re.I)), None)
        if not found:
            primary.append(clause)
            continue
        key, pattern, label, topic = found
        if key in withdrawn:
            continue
        if key == 'heating' and re.search(r'аккумулятор|ноутбук|телефон|батарейк', clause, re.I):
            return None
        if key == 'partition' and not re.search(r'реечн\w*\s+перегород', literal, re.I):
            return None
        # The owner's heating example asks to look at it. An explicit riser
        # replacement cannot silently become an optional inspection instead.
        if key == 'heating' and not re.search(r'посмотр|осмотр|оценить', clause, re.I):
            return None
        # Quoted, historical, hypothetical and withdrawn requests cannot
        # supply an optional task or erase an unrelated current main job.
        obligation_text = re.sub(r'\bне\s*обязательн(?:о|ы|а|ое|ая|ый|ые|ен)\b', ' ', clause, flags=re.I)
        if re.search(r'[«»“”"]|\b(?:вчера|раньше|сосед|сказал|написал|если\s+когда)\b|'
                     r'не\s+(?:надо|нужно|нужна|требуется|смотреть|трогать)|'
                     r'(?:больше|уже)\s+не\s+нуж|отмен\w*|обязательн|только\s+если|'
                     r'без\s+(?:этого|ремонта|замены).{0,35}(?:не\s+надо|не\s+нуж|не\s+при)', obligation_text, re.I):
            return None
        source = next((m for m in clients if clause.strip() in str(m.get('body') or m.get('text') or '')), None)
        if source is None:
            return None
        # Named extra work remains source-bound even when the service offers
        # only inspection instead of the requested execution.
        if not re.search(operation + r'|ремонт|диагностик|теч[её]т|текла', clause, re.I):
            return None
        if re.search(r'газ|вскрыти|несущ|демонтаж\w*\s+стен', clause, re.I):
            return None
        # Additional source fragments about the same extra must not remain
        # in the primary selection, accidentally converting it to approval.
        if not any(x['subject'] == key for x in extras):
            extras.append(dict(subject=key, subject_pattern=pattern, label=label, topic=topic,
                message_id=str(source.get('id') or ''), quote=clause.strip(),
                client_requested_look=bool(re.search(r'посмотр|осмотр|оценить', clause, re.I)),
                source='client_message', execution_rules=choose(clause, known)['rules'], execution_approved=False))
    if not (extras or withdrawn) or not all(x['message_id'] for x in extras):
        return None
    # A later withdrawal, demand or independent new scope cannot be ignored.
    for extra in extras:
        pattern = next(s[1] for s in subjects if s[0] == extra['subject'])
        for m in clients:
            for body in re.split(r'[.!?;\n]+', str(m.get('body') or m.get('text') or '')):
                obligation_text = re.sub(r'\bне\s*обязательн(?:о|ы|а|ое|ая|ый|ые|ен)\b', ' ', body, flags=re.I)
                if re.search(pattern, body, re.I) and re.search(
                        r'не\s+(?:надо|нужно|нужна|требуется|смотреть|трогать)|отмен\w*|обязательн|только\s+если', obligation_text, re.I):
                    return None
    primary_text = '\n'.join(primary).strip()
    service = choose(primary_text, known)
    if (service['status'] != 'supported' or not service['items']
            or any(i['status'] != 'accept' or i['profile'] != 'mnc' for i in service['items'])):
        return None
    # A recognized tap must not conceal another explicitly ordered unknown
    # operation in a separate clause. Mere contact/price details are not jobs.
    for clause in primary:
        if (any(i['id'] in ('toilet', 'sink', 'bath') for i in service['items'])
                and re.fullmatch(r'\s*подключить\s+к\s+воде\s+и\s+канализации[).\s]*', clause, re.I)):
            continue  # A named fixture's hook-up detail, not another unknown job.
        if re.search(operation, clause, re.I) and choose(clause, known)['status'] not in ('supported',):
            return None
    disclosure = ' '.join('По ' + x['topic'] + ' смогу сориентировать только на месте.' for x in extras)
    comment = ('Дополнительно — по возможности посмотреть ' + ', '.join(x['label'] for x in extras)
               + '; выполнение работ не подтверждено.') if extras else ''
    return dict(rule_id='OWNER-MIXED-OPTIONAL-LOOK-20261023', source='server_source_bound_scope',
                primary_text=primary_text, primary_service=service, extras=extras,
                withdrawn_subjects=sorted(withdrawn),
                disclosure=disclosure, comment=comment, extra_execution_approved=False,
                client_consent_to_extra_execution=False)


def optional_execution_claim(text, scope):
    """Reject positive extra-execution promises; quotes and questions are data."""
    for clause in re.split(r'[.!?;\n]+|\b(?:но|зато)\b', str(text or ''), flags=re.I):
        if not any(re.search(x['subject_pattern'], clause, re.I) for x in scope.get('extras', [])):
            continue
        if re.search(r'не\s+(?:обещаю|подтвержден\w*|согласован\w*|гарантиру\w*)|только\s+(?:осмотр|посмотр)', clause, re.I):
            continue
        if re.search(r'сделаю|выполню|отремонтирую|заменю|установлю|согласован\w*|'
                     r'гарантирован\w*|подтвержд[её]н\w*\s+ремонт|'
                     r'(?:мастер|специалист)[^.!?;]{0,35}(?:сделает|заменит|отремонтирует|установит)', clause, re.I):
            return True
    return False


def condition_issue(service, state, text):
    """Resolve typed conditional acceptance only when its required fact is present."""
    if (any(item['id']=='lock' for item in service.get('items',[]))
            and state.get('lock_work',{}).get('value') == 'repair'):
        return 'Ремонт замка/ручки требует согласования с филиалом; остальные заявленные работы сохраняются', ['DOC-L0364','DOC-L0452','DOC-L0453']

    def no(key):
        v = state[key]["value"]
        return v == "no" or bool(re.search(r"\bнет\b|\bне\b", v, re.IGNORECASE))

    # DOC-L0459 requires asking and preserving inventory information. A
    # negative answer does not establish that the item is unpurchased or
    # introduce branch agreement for an otherwise ordinary MNC repair.
    # Actual service prerequisites below remain independent of that answer.

    if (
        any(item.get('family') in ('boiler', 'oven') or item.get('id') == 'gas' for item in service.get('items', []))
        and
        state["gas_type"]["status"] == "answered"
        and re.search(r"газов", state["gas_type"]["value"], re.IGNORECASE)
        and not no("gas_type")
    ):
        return "Подтверждены газовые элементы: работа исключена, решение оператора", [
            "DOC-L0389",
            "DOC-L0401",
        ]
    for item in service.get("items", []):
        key = item["id"]
        if (key == 'pc-assembly' and state['pc_parts']['status'] == 'answered' and no('pc_parts')
                and state['pc_purchase']['status'] == 'answered' and no('pc_purchase')):
            return 'Нет комплектующих и готовности купить их в день приезда: условие приёма сборки ПК не выполнено', ['DOC-L0130']
        if (key=='coffee' and 'coffee_vending' in item.get('questions',[])
                and state['coffee_vending']['status']=='answered' and state['coffee_vending']['value']=='yes'):
            return 'Кофейный торговый автомат с терминалом оплаты принимается по согласованию', ['DOC-L0466','OWNER-COFFEE-VENDING-20261019']
        if 'wall' in item.get('questions',[]) and state['wall']['status']=='unavailable':
            return 'Клиент не знает материал стены: оператор проверяет обязательное условие крепления, повторно тот же вопрос не задаём', ['DOC-L0352']
        if key == 'cable-crimp' and re.search(r'\bсрастить\b|\bсоединить\b.{0,30}(?:поврежд[её]н|оборван|концы|конца|провода)', text, re.IGNORECASE):
            return 'Соединение повреждённого провода не подтверждено как обжим коннектора: оператор проверяет условия приёма', ['DOC-L0160', 'DOC-L0162', 'DOC-L0166']
        if key in ("washer-connect", "boiler-install", "oven-connect", "mnc-connect"):
            ready_fields = [field for field in item.get('questions',[]) if field in ('electrics_ready','plumbing_ready')]
            if any(state[field]['status']=='uncertain' for field in ready_fields):
                return "Готовность подключения подтверждена неуверенно: оператор проверяет обязательное условие", item.get("primary_refs", [])
            if key=='mnc-connect' and any(state[field]['status']=='answered' and no(field) for field in ready_fields):
                return 'Подключение не подготовлено: оператор согласует работу с филиалом',item.get('primary_refs',[])
        if (key=='pipes' and state['pipe_material']['status']=='answered'
                and re.search(r'медн|медь|металл|чугун|сталь|латун|алюмин',state['pipe_material']['value'],re.I)
                and re.search(r'просверл|пробил|пробит|дыр|теч|ремонт|почин|поврежд',text,re.I)
                and not re.search(r'замен\w*[^.!?\n]{0,30}пластик',text,re.I)):
            return 'Ремонт повреждённой металлической трубы не подтверждён как замена на пластиковую: нужно согласование с филиалом',['DOC-L0282','DOC-L0283','DOC-L0285','DOC-L0453']
        if any(state[field]["status"] == "uncertain" and (field != 'countertop_material' or state[field]['asked'] >= 2) for field in item.get("questions", []) if field in ("pipe_material", "countertop_material", "cable_type")):
            return "Материал назван предположительно: оператор проверяет обязательное условие приёма", item.get("primary_refs", [])
        if key == 'pc-peripheral' and state['has_pc']['status'] == 'answered' and no('has_pc'):
            return 'Нет ПК, ноутбука или моноблока: обязательное условие ремонта периферии не выполнено', ['DOC-L0129']
        if (
            key == "router"
            and state["internet"]["status"] == "answered"
            and no("internet")
        ):
            return "Интернет не проведён: требуется согласование", ["DOC-L0175"]
        if key == "pc-special-software":
            if re.search(r"настро|обучи", text, re.IGNORECASE):
                return (
                    "Настройка/обучение узкопрофильной программе требует согласования",
                    ["DOC-L0138"],
                )
            if state["license"]["status"] == "answered" and no("license"):
                return "Нет лицензионного ключа: требуется согласование", ["DOC-L0137"]
        if (
            key in ("pc-icloud", "phone-access")
            and state["owner_access"]["status"] == "answered"
            and no("owner_access")
        ):
            return (
                "Нет доступа владельца: требуется согласование; пароли не запрашивать в чате",
                ["DOC-L0146", "DOC-L0238"],
            )
        if key == "coffee" and re.search(r"капсульн", state["coffee_type"]["value"], re.IGNORECASE):
            return "Капсульная кофемашина требует согласования", [
                "DOC-L0406"
            ]
        if key == "coffee" and re.search(r"автоматическ", state["coffee_type"]["value"], re.IGNORECASE):
            return "Тип автоматической кофемашины не уточнён: оператор проверяет тип и условия, не приравнивая её к капсульной", ["DOC-L0405"]
        if (
            key == "oven-portable"
            and state["induction"]["status"] == "answered"
            and no("induction")
        ):
            return "Компактная неиндукционная плита требует согласования", ["DOC-L0398"]
        if (
            key in ("washer-connect", "boiler-install")
            and state["plumbing_ready"]["status"] == "answered"
            and no("plumbing_ready")
        ):
            return (
                "Подвод/отвод воды не подготовлен: оператор согласует условия подключения",
                ["DOC-L0413", "DOC-L0420"],
            )
        if (
            key == "oven-connect"
            and state["electrics_ready"]["status"] == "answered"
            and no("electrics_ready")
        ):
            return "Электрика не подготовлена: оператор согласует подключение", [
                "DOC-L0402"
            ]
        if (
            key == "floor"
            and state["floor_ready"]["status"] == "answered"
            and (
                no("floor_ready")
                or re.search(
                    r"нужн.{0,15}выравнив", state["floor_ready"]["value"], re.IGNORECASE
                )
            )
        ):
            return "Пол не подготовлен: требуется согласование", ["DOC-L0335"]
        if key == "drying" and re.search(
            r"снаружи|наружн", state["drying_location"]["value"], re.IGNORECASE
        ):
            return "Наружная сушилка требует согласования", ["DOC-L0361"]
        if key == "data" and re.search(
            r"сгор|поврежд|разбит|не включ|не загружа|icloud|whatsapp|telegram",
            text,
            re.IGNORECASE,
        ):
            return (
                "Восстановление с повреждённого устройства/облака требует согласования",
                ["DOC-L0114", "DOC-L0115", "DOC-L0116"],
            )
        if key == "printer-special":
            if re.search(r"снпч|переделан|ремонт|прошив", text, re.IGNORECASE):
                return "Специальный принтер/СНПЧ: требуется согласование", [
                    "DOC-L0184",
                    "DOC-L0185",
                    "DOC-L0187",
                    "DOC-L0188",
                ]
            if state["printer_pc"]["status"] == "answered" and no("printer_pc"):
                return (
                    "Настройка специального принтера не через ПК требует согласования",
                    ["DOC-L0182"],
                )
        if key == "console" and re.search(
            r"xbox.{0,30}настро|настро.{0,30}xbox", text, re.IGNORECASE
        ):
            return "Настройка Xbox требует согласования", ["DOC-L0246"]
        if key == "tv":
            if re.search(
                r"кинескоп|плазмен|проекцион", state["tv_type"]["value"], re.IGNORECASE
            ):
                return "Ремонт данного типа ТВ требует согласования", [
                    "DOC-L0207",
                    "DOC-L0432",
                ]
        if (item.get('family') == 'tv' and 'screen_damage' in item.get('questions', [])
                and (state['screen_damage'].get('reviewed_screen_cracks')
                     or state['screen_damage']['status'] == 'answered' and not no('screen_damage'))):
            return ('Физическое повреждение/влага на экране: оператор проверяет матрицу и отказ/согласование',
                    ['DOC-L0223', 'DOC-L0445'])
        if key == "tv-channels" and re.search(
            r"наружн|спутников|триколор", state["antenna"]["value"], re.IGNORECASE
        ):
            return "Наружная/спутниковая антенна требует решения оператора", [
                "DOC-L0205",
                "DOC-L0208",
            ]
    if state["decision_maker"]["status"] == "answered" and no("decision_maker"):
        return (
            "Лицо, принимающее решение и оплату, отсутствует: подтверждать выезд нельзя",
            ["DOC-L0797", "DOC-L0798"],
        )
    return None
