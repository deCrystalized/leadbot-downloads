"""Shared, evidence-backed contact facts. Pure parsing: no network or CRM writes."""
import re
from datetime import datetime
from dataclasses import replace
from typing import Any

import contact_address
import contact_phone


_PRINTER_ITEM_NOUNS = {
    'printer': r'принтер(?:а|у|ом|е|ы|ов|ам|ами|ах)?|мфу',
    'cartridge': r'картридж(?:а|у|ем|е|и|ей|ам|ами|ах)?',
    'ink': r'чернил(?:а|ам|ами|ах)?',
    'paint': r'краск(?:а|и|е|у|ой|ою|ам|ами|ах)|красок',
    'toner': r'тонер(?:а|у|ом|е|ы|ов|ам|ами|ах)?',
    'printhead': r'головк(?:а|и|е|у|ой|ою|ам|ами|ах)|головок',
    'drum': r'барабан(?:а|у|ом|е|ы|ов|ам|ами|ах)?',
}


def printer_newness_mentions(text):
    """Bind an explicit age adjective to its noun, without diagnosing a device.

    Modes preserve questions, quotations and uncertainty instead of turning
    them into client assertions. Offsets and literals refer to the input.
    """
    source = str(text or '')
    body = re.sub(r'[«»“”"]', ' ', source)
    noun = '(?:' + '|'.join(_PRINTER_ITEM_NOUNS.values()) + ')'
    adjective = r'(?:нов|стар)(?:ый|ого|ому|ым|ом|ая|ую|ой|ое|ые|ых|ыми)'
    modifiers = r'(?:цветн\w*|ч[её]рн\w*|оригинальн\w*|лазерн\w*|струйн\w*)'
    links = (r'(?:(?:совсем|совершенно|абсолютно|теперь|сейчас|ещ[её]|уже|тоже|вроде|кажется|наверное|не)\s+|'
             r'по\s+(?:(?:его|е[её]|их)\s+словам|словам\s+(?:клиента|продавца|мастера|соседа|специалиста))\s+){0,3}')
    patterns = [r'\b(?P<object>' + noun + r')\s*(?:[—:-]\s*)?' + links + r'(?P<attribute>' + adjective + r')\b',
                r'\b(?P<attribute>' + adjective + r')\s+(?:' + modifiers + r'\s+){0,2}'
                r'(?P<object>' + noun + r')\b']
    quoted = [(m.start(), m.end()) for m in re.finditer(r'«[^»]*»|“[^”]*”|"[^"\n]*"', source)]
    found = [dict(object_span=m.span('object'), attribute_span=m.span('attribute'), span=m.span())
             for pattern in patterns for m in re.finditer(pattern, body, re.I)]
    # A plural adjective may qualify each explicitly conjoined item. Different
    # adjectives between nouns end the group; they are not shared properties.
    group = noun + r'(?:\s*(?:,\s*|\s+и\s+)' + noun + r'){1,3}'
    plural = r'(?:нов|стар)(?:ые|ых|ыми)'
    for pattern in [r'\b(?P<attribute>' + plural + r')\s+(?P<objects>' + group + r')\b',
                    r'\b(?P<objects>' + group + r')\s+' + links + r'(?P<attribute>' + plural + r')\b']:
        for match in re.finditer(pattern, body, re.I):
            for obj in re.finditer(r'\b' + noun + r'\b', match['objects'], re.I):
                found.append(dict(object_span=(match.start('objects') + obj.start(),
                                                match.start('objects') + obj.end()),
                                  attribute_span=match.span('attribute'), span=match.span(), shared=True))
    found.sort(key=lambda entry: entry['span'][0])
    result = []
    seen = set()
    for match in found:
        start, end = match['span']
        obj_start, obj_end = match['object_span']
        attr_start, attr_end = match['attribute_span']
        if (not match.get('shared') and obj_start < attr_start
                and re.match(r'\s+(?:' + modifiers + r'\s+){0,2}' + noun + r'\b', body[end:], re.I)):
            # "У принтера новый картридж" and "картридж нового принтера"
            # attach the adjective to the following noun, not the prior one.
            continue
        identity = (match['object_span'], match['attribute_span'])
        if identity in seen:
            continue
        seen.add(identity)
        prefix = re.split(r'[.!?;\n]', body[:start])[-1]
        local = prefix.rsplit(',', 1)[-1]
        tail = body[end:]
        before_attribute = body[:attr_start]
        value = 'new' if body[attr_start:attr_end].lower().startswith('нов') else 'old'
        if re.search(r'\bне\s*$', before_attribute, re.I):
            value = 'not_' + value
        mode = 'asserted'
        if re.search(r'\bне\s+(?:говор\w*|сказ\w*|утвержд\w*|сообщ\w*|подтвержд\w*)[^.!?;]{0,35}$|'
                     r'неизвестно\s*,?\s*(?:что\s+)?$', prefix, re.I):
            mode = 'not_asserted'
        elif re.match(r'\s*\?', tail):
            mode = 'question'
        elif re.search(r'\b(?:если|допустим|предположим)\b', local, re.I):
            mode = 'hypothetical'
        elif (re.search(r'\b(?:не\s+уверен\w*|не\s+знаю|сомнева\w*)\b', prefix, re.I)
              or re.search(r'\b(?:возможно|может|похоже|кажется|вроде|наверно\w*)\s*,?\s*$', prefix, re.I)
              or re.search(r'\b(?:вроде|кажется|наверное)\b', body[start:end], re.I)
              or re.match(r'\s*,?\s*(?:наверно\w*|если\s+не\s+ошибаюсь)\b', tail, re.I)):
            mode = 'uncertain'
        elif (re.search(r'\b(?:продавец|мастер|сосед|специалист)\w*[^.!?;\n]{0,35}'
                        r'(?:сказ\w*|напис\w*|говор\w*|утвержд\w*)[^.!?;\n]{0,50}$', prefix, re.I)
              or re.search(r'по\s+словам\s+(?:продавца|мастера|соседа|специалиста)', body[start:end], re.I)):
            mode = 'attributed'
        elif any(a < end and b > start for a, b in quoted):
            mode = 'quoted'
        elif re.search(r'\b(?:хочу|нужно|нужен|нужна|купить|куплю|ищу)\b[^.!?;\n]{0,25}$', local, re.I):
            mode = 'requested'
        subject = next(key for key, pattern in _PRINTER_ITEM_NOUNS.items()
                       if re.fullmatch(pattern, body[obj_start:obj_end], re.I))
        result.append(dict(object=subject, value=value, mode=mode, literal=source[start:end],
                           start=start, end=end))
    return result


def _printing_medium(text, verb, obj):
    """A printing symptom or a cartridge's purpose does not name its medium."""
    left, right = sorted((verb, obj), key=lambda match: match.start())
    between = text[left.end():right.start()]
    if re.search(r'\b(?:для|без|вместо|после|про|об)\b', between, re.I):
        return False
    word = obj[0].lower()
    cartridge = word.startswith('картридж')
    # Here the cartridge is a printed surface, not the material/device used
    # to print. An ordinary label printed ON a printer still uses that printer.
    surface = r'\b(?:этикетк\w*|наклейк\w*|маркировк\w*|надпис\w*|поверхност\w*|корпус\w*)\b'
    if cartridge and word in ('картридже', 'картриджах') and re.search(surface, text[:max(verb.end(), obj.end())], re.I):
        return False
    if word in ('картриджем', 'картриджами', 'принтером', 'принтерами'):
        return True
    modifier = r'(?:нов\w*|стар\w*|цветн\w*|ч[её]рн\w*|перв\w*|втор\w*|друг\w*|эт\w*|данн\w*|мо[еёий]\w*|ваш\w*|наш\w*)'
    prefix = text[:obj.start()]
    if re.search(r'\bс\s+помощью\s+(?:' + modifier + r'\s+){0,4}$', prefix, re.I):
        return word in ('картриджа', 'картриджей', 'принтера', 'принтеров', 'мфу')
    return (word in ('принтере', 'принтерах', 'мфу', 'картридже', 'картриджах')
            and bool(re.search(r'\bна\s+(?:' + modifier + r'\s+){0,4}$', prefix, re.I)))


def _printer_event_qualifiers(text, obj):
    """Keep literal distinctions local to the event's noun, not another item."""
    adjective = (r'(?:нов|стар|цветн|ч[её]рн|перв|втор|друг|оригинальн|лазерн|струйн|совместим)'
                 r'(?:ый|ого|ому|ым|ом|ая|ую|ой|ое|ые|ых|ыми)')
    before = re.search(r'(?:(?:не\s+)?' + adjective + r'\s+){1,4}$',
                       text[:obj.start()], re.I)
    after = re.match(r'\s*(?:\(\s*((?:' + adjective + r'\s*){1,3})\)|'
                     r'((?:' + adjective + r'\s*){1,3})(?!\w))', text[obj.end():], re.I)
    parts = [before[0]] if before else []
    if after:
        # "Картридж нового принтера" describes the printer, not the cartridge.
        tail = text[obj.end() + after.end():]
        if not re.match(r'\s*(?:принтер\w*|картридж\w*|мфу)\b', tail, re.I):
            parts.append(after[1] or after[2])
    result = {}
    for match in re.finditer(adjective, ' '.join(parts), re.I):
        word = match[0].lower().replace('ё', 'е')
        if word.startswith(('нов', 'стар')):
            value = 'new' if word.startswith('нов') else 'old'
            if re.search(r'\bне\s*$', ' '.join(parts)[:match.start()], re.I):
                value = 'not_' + value
            result['newness'] = value
        elif word.startswith(('цветн', 'черн')):
            result['colour'] = 'colour' if word.startswith('цветн') else 'black'
        elif word.startswith(('перв', 'втор')):
            result['ordinal'] = 'first' if word.startswith('перв') else 'second'
        elif word.startswith('друг'):
            result['reference'] = 'other'
    return result


def printer_fitment_mentions(text, *, model_prose=False):
    """Literal physical-item events, not an inference from a new consumable.

    Software installation and an action on a neighbouring noun are separate.
    Non-assertive speech is retained with its mode, never promoted to a fact.
    Use is separate from installation/replacement; past use is not current use.
    This deliberately does not resolve implicit actors or missing pronouns.
    """
    source = str(text or '')
    noun = r'\b(?:картридж(?:а|у|ем|е|и|ей|ам|ами|ах)?|принтер(?:а|у|ом|е|ы|ов|ам|ами|ах)?|мфу)\b'
    action = (r'\b(?:установ(?:ил[аи]?|или|лен\w*)|встав(?:ил[аи]?|или|лен\w*)|'
              r'постав(?:ил[аи]?|или|лен\w*)|стоит|стоят|поменял[аи]?|поменяли|'
              r'замен(?:ил[аи]?|или|[её]н\w*)|установить|вставить|поставить|ставить|поменять|заменить)\b|'
              r'\b(?:после\s+(?:установки|замены)|(?:выполнена|произведена)\s+(?:установка|замена))\b')
    usage = (r'\b(?:использ(?:у(?:ю|ешь|ет|ем|ете|ют)(?:ся)?|уем\w*|овал[аи]?|овали|'
             r'ован\w*|ующ\w*|овать)|польз(?:у(?:юсь|ешься|ется|емся|етесь|ются)|'
             r'овал(?:ся|ась|ись)|оваться))\b')
    printing = (r'\b(?:печата(?:ю|ешь|ет|ем|ете|ют|л[аи]?|ли|ть|я)|'
                r'печат(?:ь(?:ю)?|и)|(?:от|на|рас)печатан(?:[оаы]?|н\w*))\b')
    quoted = [(m.start(), m.end()) for m in re.finditer(r'«[^»]*»|“[^”]*”|"[^"\n]*"', source)]
    rows = []
    for sentence in re.finditer(r'[^.!?;\n]+[.!?]?', source):
        text = sentence[0]
        objects = list(re.finditer(noun, text, re.I))
        other_objects = list(re.finditer(r'\b(?:драйвер\w*|программ\w*|головк\w*|барабан\w*)\b', text, re.I))
        # A comma separates two independently reported actions/objects. A
        # modal introduction ("возможно,") still qualifies the whole sentence.
        for verb in re.finditer('(?:' + action + ')|(?:' + usage + ')|(?:' + printing + ')', text, re.I):
            print_with = bool(re.fullmatch(printing, verb[0], re.I))
            is_usage = print_with or bool(re.fullmatch(usage, verb[0], re.I))
            options = []
            for obj in objects:
                # "Принтер печатает с картриджем" explicitly names the
                # cartridge being used, not a second use of the printer.
                if print_with and not _printing_medium(text, verb, obj):
                    continue
                left, right = sorted((verb, obj), key=lambda m: m.start())
                between = text[left.end():right.start()]
                if re.search(r'[,;:]|\b(?:драйвер\w*|программ\w*|головк\w*|барабан\w*)\b', between, re.I):
                    continue
                if len(re.findall(r'\w+', between)) > 5 or any(
                        other is not obj and left.end() <= other.start() < right.start() for other in objects):
                    continue
                # "Картридж установленного принтера" describes the printer.
                if obj.end() <= verb.start() and re.match(r'\s+(?:нов\w*\s+)?' + noun, text[verb.end():], re.I):
                    continue
                options.append((len(between), obj))
            if not options:
                continue
            distance, obj = min(options, key=lambda item: item[0])
            if any(not re.search(r'[,;:]', text[min(other.end(), verb.end()):max(other.start(), verb.start())])
                   and min(abs(other.end() - verb.start()), abs(other.start() - verb.end())) <= distance
                   for other in other_objects):
                continue
            start, end = min(verb.start(), obj.start()), max(verb.end(), obj.end())
            prefix = text[:verb.start()]
            clause = re.split(r'[,;:]', text[:start])[-1] + re.split(r'[,;:]', text[start:])[0]
            nonfinite = bool(re.search(r'(?:ить|овать|оваться|печатать)$', verb[0], re.I))
            print_nominal = print_with and bool(re.fullmatch(r'печат(?:ь(?:ю)?|и)', verb[0], re.I))
            modal_action = nonfinite or print_nominal
            presupposed_usage = is_usage and bool(re.search(
                r'(?:используем|(?:от|на|рас)печатанн)(?:ый|ого|ому|ым|ом|ая|ую|ой|ое|ые|ых|ыми)$',
                verb[0], re.I))
            mode = 'asserted'
            if (re.search(r'\bне\s+(?:говор\w*|сказ\w*|сообщ\w*|утвержд\w*|подтвержд\w*)\b', text[:start], re.I)
                    or is_usage and re.search(r'\bне\s+подтвержден\w*|\bне\s+сообщал\w*', text[end:], re.I)):
                mode = 'not_asserted'
            elif re.search(r'\b(?:если|допустим|предположим)\b', text[:end], re.I):
                mode = 'hypothetical'
            elif (text.rstrip().endswith('?') and not presupposed_usage
                  or re.match(r'\s+ли\b', text[verb.end():], re.I)):
                mode = 'question'
            elif re.search(r'\b(?:возможно|вроде|кажется|наверно\w*|не\s+знаю|неизвестно)\b', text, re.I):
                mode = 'uncertain'
            elif modal_action and re.search(r'\b(?:пробовал\w*|пытал\w*|попытк\w*)\b', prefix, re.I):
                mode = 'attempted'
            elif modal_action and re.search(r'\b(?:хочу|нужн[оаы]?|надо|прошу|попросил\w*|требуется)\b', prefix, re.I):
                mode = 'requested'
            elif (re.search(r'\b(?:буду|будем|будет|будут)\s*$', prefix, re.I)
                  or modal_action and re.search(r'\b(?:собира\w*|планир\w*)\b', prefix, re.I)):
                mode = 'future'
            elif (re.search(r'\bне\s+(?:(?:был\w*|ещ[её]|пока)\s+){0,2}$', prefix, re.I)
                  or print_nominal and re.search(r'\bне\s+был[оаи]?\b', text[end:], re.I)):
                mode = 'negated'
            elif any(a < sentence.start() + end and b > sentence.start() + start for a, b in quoted):
                mode = 'quoted'
            elif re.search(r'\b(?:сказ\w*|говор\w*|напис\w*|по\s+словам)\b', text[:start], re.I):
                mode = 'attributed'
            elif nonfinite:
                mode = 'requested'
            actor = 'unspecified'
            local = clause
            if is_usage:
                # A client reporting an unnamed user's action is the speaker,
                # not necessarily the person who used the physical item.
                local = re.sub(r'\b(?:клиент(?:ка)?|я|мы)\s+'
                               r'(?:сообщ\w*|опис\w*|рассказ\w*|говор\w*)\s+(?:о|об|про)\s+',
                               '', local, flags=re.I)
            if re.search(r'\b(?:клиент(?:ом|ка)?|сам(?:а|и)?|мной|я)\b', local, re.I):
                actor = 'client'
            elif re.search(r'\b(?:вы|вами|наш\w*\s+мастер|наша\s+команда)\b', local, re.I):
                actor = 'service'
            elif re.search(r'\b(?:мы|нами)\b', local, re.I):
                actor = 'service' if model_prose else 'client'
            elif re.search(r'\b(?:мастер\w*|продавец|сосед\w*|специалист\w*)\b', local, re.I):
                actor = 'third_party'
            timing = re.search(r'\b(?:с\s+сегодняшнего\s+дня|со\s+вчерашнего\s+дня|'
                               r'совсем\s+недавно|недавно|только\s+что|на\s+днях|вчера|сегодня|давно|'
                               r'\d+\s+(?:дн\w*|недел\w*|месяц\w*|лет|год\w*)\s+назад)\b', clause, re.I)
            timing = timing[0].lower() if timing else ''
            if timing in ('совсем недавно', 'на днях'):
                timing = 'недавно'
            event = 'replacement' if re.search(r'замен|помен', verb[0], re.I) else 'fitment'
            if is_usage:
                event = 'use'
                if re.search(r'использовал|пользовал|печатал|(?:от|на|рас)печатан', verb[0], re.I):
                    event = 'past_use'
                elif re.search(r'использу|пользу|печата(?:ю|ет|ют|ем|я)', verb[0], re.I):
                    event = 'current_use'
            rows.append(dict(object='cartridge' if obj[0].lower().startswith('картридж') else 'printer',
                event=event,
                mode=mode, actor=actor, timing=timing,
                object_qualifiers=_printer_event_qualifiers(text, obj),
                literal=source[sentence.start() + start:sentence.start() + end],
                start=sentence.start() + start, end=sentence.start() + end))
    return rows


def printer_item_fitment(messages):
    """Source-linked reported actions in the current enquiry, never proof of work."""
    evidence = []
    for message in messages:
        if (message.get('direction') != 'in'
                or message.get('sender_type', 'client') not in ('client', 'customer', 'user', 'contact', 'lead', '')):
            continue
        source = str(message.get('body') or message.get('text') or '')
        boundary_text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', source)
        boundary = re.search(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|принтер|техника)', boundary_text, re.I)
        if boundary and not re.search(r'\b(?:не|если)\b[^.!?;,\n]{0,20}$', boundary_text[:boundary.start()], re.I):
            evidence = []
        for mention in printer_fitment_mentions(source):
            evidence.append(dict(mention, message_id=message.get('id', ''), quote=source))
    return evidence


def unsupported_printer_fitment(text, evidence):
    """Check each free claim; a source-derived receipt cannot license invention."""
    for claim in printer_fitment_mentions(text, model_prose=True):
        if claim['mode'] in ('not_asserted', 'question', 'requested', 'future', 'hypothetical', 'attempted'):
            continue
        if claim['event'] in ('use', 'current_use', 'past_use') and claim['mode'] == 'uncertain':
            continue
        # A non-temporal nominal "использование" may summarize an actual
        # report, but neither that nominal nor yesterday's use proves now.
        events = ('use', 'current_use', 'past_use') if claim['event'] == 'use' else (claim['event'],)
        qualifiers = claim.get('object_qualifiers', {})
        matching = [row for row in evidence if row['object'] == claim['object'] and row['event'] in events
                    and all(row.get('object_qualifiers', {}).get(key) == value
                            for key, value in qualifiers.items())]
        # A denial about the new/second cartridge must not erase an explicitly
        # reported use of the old/first cartridge. An unqualified denial can.
        matching = [row for index, row in enumerate(matching)
                    if row['mode'] != 'asserted' or not any(
                        later['mode'] == 'negated'
                        and not any(key in later.get('object_qualifiers', {})
                                    and value != later['object_qualifiers'][key]
                                    for key, value in row.get('object_qualifiers', {}).items())
                        for later in matching[index + 1:])]
        if not any(row['mode'] == claim['mode']
                   and (claim['actor'] == 'unspecified' or claim['actor'] == row['actor'])
                   and (not claim['timing'] or claim['timing'] == row['timing']) for row in matching):
            return True
    return False


def printer_item_newness(messages):
    """Literal client reports only; a new cartridge says nothing about printer age."""
    evidence = []
    states = dict(printer='not_stated', cartridge='not_stated')
    for message in messages:
        if (message.get('direction') != 'in'
                or message.get('sender_type', 'client') not in ('client', 'customer', 'user', 'contact', 'lead', '')):
            continue
        source = str(message.get('body') or message.get('text') or '')
        boundary_text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', source)
        boundary = re.search(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|принтер|техника)', boundary_text, re.I)
        if boundary and not re.search(r'\b(?:не|если)\b[^.!?;,\n]{0,20}$', boundary_text[:boundary.start()], re.I):
            evidence = []
            states = dict(printer='not_stated', cartridge='not_stated')
        for mention in printer_newness_mentions(source):
            if mention['mode'] == 'not_asserted':
                continue
            evidence.append(dict(mention, message_id=message.get('id', ''), quote=source))
            states[mention['object']] = mention['value'] if mention['mode'] == 'asserted' else 'not_stated'
    return dict(states=states, evidence=evidence) if evidence else None


BACKGROUND_WORK = {
    'wallpaper': dict(object=r'\bобо(?:и|ев|ям|ями|ях)\b',
                      performed=r'клею|клеим|поклею|поклеим|поклеил[аи]?|поклеили|наклеил[аи]?|наклеили|(?:буду|будем)\s+клеить',
                      requested=r'поклейте|наклейте|оклейте|поклеить|оклеить|поклейк\w*|оклейк\w*',
                      claim=r'(?:поклейк\w*|оклейк\w*|клеени\w*|поклеить|наклеить|клеить)[^.!?;,]{0,25}обо\w*',
                      label='поклейка обоев'),
    'flooring': dict(object=r'\bламинат\w*\b',
                     performed=r'кладу|клад[её]м|положу|положим|положил[аи]?|положили|(?:буду|будем)\s+класть',
                     requested=r'положите|уложите|положить|уложить|укладк\w*',
                     claim=r'(?:укладк\w*|уложить|положить)[^.!?;,]{0,25}ламинат\w*',
                     label='укладка ламината'),
    'painting': dict(object=r'\bстен\w*\b',
                     performed=r'крашу|красим|покрашу|покрасим|покрасил[аи]?|покрасили|(?:буду|будем)\s+красить',
                     requested=r'покрасьте|покрасить|покраск\w*|покрасить|окраск\w*',
                     claim=r'(?:покраск\w*|окраск\w*|покрасить|красить)[^.!?;,]{0,25}стен\w*',
                     label='покраска стен'),
}


def client_background_work(messages):
    """Explicit client-performed preparation, not every narrated work noun.

    Keep all original speech. Exclude a quote from service selection only when
    a separate, explicitly requested object remains. A later order wins.
    """
    active = {}
    for message in messages:
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('system', 'avito', 'operator', 'bot', 'assistant')):
            continue
        body = str(message.get('body') or message.get('text') or '')
        for key, spec in BACKGROUND_WORK.items():
            ordered = re.search(r'(?:' + spec['requested'] + r')[^.!?;\n]{0,35}' + spec['object']
                                + r'|' + spec['object'] + r'[^.!?;\n]{0,25}(?:' + spec['requested'] + r')', body, re.I)
            # An infinitive alone may be a stated self-plan; only an imperative
            # or request modality makes it an order to the service.
            request = ordered and (re.search(r'поклейте|наклейте|оклейте|положите|уложите|покрасьте', ordered[0], re.I)
                                   or re.search(r'нужн\w*|надо|прошу|сможете|можете|хочу\s+заказать', body, re.I))
            if request:
                active.pop(key, None)
                continue
            for found in re.finditer(r'[^.!?;\n,]+', body):
                clause = found[0].strip()
                clause = re.split(r'\s+(?:и|а|но)\s+(?=(?:нужно|надо|нужен|нужна|прошу|требуется)\b)', clause, maxsplit=1, flags=re.I)[0]
                match = re.match(r'(?:(?:я|мы)\s+)?(?:(?:сам|сама|сами|уже|сейчас)\s+){0,3}'
                                 r'(?P<verb>' + spec['performed'] + r')\b', clause, re.I)
                if not match or not re.search(spec['object'], clause, re.I):
                    continue
                if (re.search(r'л[аи]?$', match['verb'], re.I)
                        and not re.match(r'(?:я|мы|сам|сама|сами)\b', clause, re.I)):
                    continue
                if re.search(r'\b(?:не|если|возможно|может|не\s+знаю)\b', clause[:match.end()], re.I):
                    continue
                active[key] = dict(operation=key, actor='client', ordered_from_service=False,
                                   message_id=message.get('id', ''), quote=clause,
                                   label=spec['label'], source='explicit_client_speech')
                break
    all_text = '\n'.join(str(m.get('body') or m.get('text') or '') for m in messages if m.get('direction') == 'in')
    rows = list(active.values())
    remainder = all_text
    for row in rows:
        remainder = remainder.replace(row['quote'], '', 1)
    separate_order = bool(re.search(r'нужн\w*|надо|прошу|установите|сделайте|повесьте|почините', remainder, re.I)
                          and re.search(r'розетк|проводк|люстр|светиль|карниз|смесител|шкаф|кроват|компьютер|ноутбук|принтер|холодильник', remainder, re.I))
    return [dict(row, exclude_from_service_selection=separate_order) for row in rows]


def standalone_diagnostic(messages):
    """Client-requested diagnosis without ordering repair, across directions."""
    active = {}
    for message in messages:
        if (not _client_intent_message(message)
                or message.get('role') in ('system', 'assistant')
                or message.get('speaker_role', 'client') != 'client'
                or message.get('out_pending')
                or str(message.get('delivery_status') or message.get('delivery') or '').lower()
                in ('failed', 'pending', 'queued', 'sending', 'error', 'cancelled', 'canceled')):
            continue
        original = str(message.get('body') or message.get('text') or '')
        text = original
        if re.search(r'\b(?:вы|мастер\w*|сотрудник\w*|оператор\w*|сосед\w*)\s+(?:мне\s+)?(?:сказ|писа|ответ|предлаг)',text,re.I):
            text = re.sub(r'«[^»]*»|"[^"\n]*"','',text)
        printer = standalone_printer_diagnostic([dict(message,body=text)])
        only = re.search(r'\bтолько\s+(?:на\s+)?диагностик|'
                         r'\bтолько\s+(?:первичный|внешний)\s+осмотр\b|'
                         r'диагностик\w*[^.!?\n]{0,55}\bбез\s+ремонта|'
                         r'\bбез\s+ремонта[^.!?\n]{0,55}диагностик', text, re.I)
        if (only and re.match(r'только\s+(?:первичный|внешний)\s+осмотр\b',only[0],re.I)
                and re.search(r'\b(?:если|допустим|вдруг)\b',
                              re.split(r'[.!?;\n]',text[:only.start()])[-1],re.I)):
            only = None
        negative_repair = (re.search(r'диагностик', text, re.I)
                           and re.search(r'\bремонт\s+не\s+нужен|\bне\s+нужен\s+ремонт|\bне\s+хочу\s+(?:его\s+)?ремонт|'
                                         r'\bремонтировать\s+(?:пока\s+)?не\s+(?:хочу|буду)', text, re.I))
        request = only or negative_repair
        request_clause = re.split(r'[.!?\n]',text[:request.start()])[-1] + text[request.start():].split('.')[0] if request else text
        other_actor = (re.search(r'\b(?:вы|мастер|специалист|сервис)\w*[^.!?\n]{0,45}(?:сказ|писа|предлож|рекоменд|может|будет)',request_clause,re.I)
                       and not re.search(r'\b(?:мне\s+нужна|я\s+хочу|вы\s+(?:можете|сможете)|прошу)\b',request_clause,re.I))
        not_only = only and re.search(r'\bне\s*(?:(?:хочу|нужен|заказываю)\s*)?$',text[:only.start()],re.I)
        if not_only:
            only = None
        diagnostic_declined = re.search(r'\bне\s+(?:(?:нужна|хочу|заказываю)\s+)?(?:только\s+)?диагностик|'
                                        r'диагностик\w*\s+(?:мне\s+)?не\s+(?:нужна|требуется)|'
                                        r'(?:первичный|внешний)\s+осмотр\s+(?:мне\s+)?не\s+(?:нужен|требуется)',text,re.I)
        if (printer or (only or negative_repair) and not other_actor) and not diagnostic_declined:
            active = dict(message_id=message.get('id',''), quote=original, source='client_message',
                          service='diagnostic_only', repair_requested=False)
        subject = re.sub(r'\bбез\s+ремонта\b|\bремонт\s+не\s+нужен\b|\bне\s+нужен\s+ремонт\b|'
                         r'\bне\s+хочу\s+(?:его\s+)?ремонт\w*', '',text,flags=re.I)
        if (re.search(r'\b(?:нужен|нужна|нужно|хочу|хотел[аи]?\s+бы|также|ещ[её]|теперь)\s+'
                     r'(?:и\s+)?(?:(?:его|принтер|полноценный|обычный)\s+)?(?:ремонт|починить|настроить|подключить|заправить)|'
                     r'\bремонт\s+(?:мне\s+)?(?:нужен|требуется)|\bбез\s+ремонта\s+не\s+обойтись|'
                     r'диагностик\w*[^.!?\n]{0,45}\b(?:и|потом)\s+(?:ремонт|замен\w*)\b|'
                     r'\b(?:замените|почините|установите|настройте|подключите|отремонтируйте)\b',subject,re.I)
                or diagnostic_declined or not_only or re.search(r'\bбез\s+ремонта\s+не\s+обойтись',text,re.I)):
            active = {}
    return active


def standalone_printer_diagnostic(messages):
    """A requested service, not a diagnosis inferred from symptoms or staff."""
    active = {}
    for message in messages:
        if message.get('direction') != 'in' or message.get('sender_type') in ('avito', 'system', 'operator', 'bot'):
            continue
        text = str(message.get('body') or message.get('text') or '')
        requested = re.search(r'\b(?:провести|проведите|сделать|сделайте|нужна|нужна\s+только)\s+'
                              r'(?:только\s+)?диагностик\w*\s+(?:моего\s+|нашего\s+)?(?:принтер|мфу)', text, re.I)
        if requested:
            prefix = re.split(r'[.!?;\n]', text[:requested.start()])[-1]
            if (re.search(r'\b(?:мастер|специалист|сервис)\w*[^.!?\n]{0,35}'
                          r'(?:сказал|предложил|рекомендовал|может|хочет|будет)', prefix, re.I)
                    and not re.search(r'\b(?:я\s+(?:хочу|хотел)|(?:вы\s+)?(?:можете|сможете)|прошу)\b', prefix, re.I)):
                requested = None
        if requested and not re.search(r'\bне\s+(?:нужна|нужно|хочу)|\b(?:другой\s+)?мастер\w*\s+(?:может|хочет|будет)', text, re.I):
            active = dict(message_id=message.get('id', ''), quote=text, source='client_message',
                          service='printer_diagnostic', repair_requested=False,
                          full_operability_confirmed=False, contractor_cartridges_confirmed=False)
        # A later explicit service change must not inherit the diagnostic fee.
        subject = re.sub(r'\bбез\s+ремонта\b|\bне\s+нужен\s+ремонт\b', '', text, flags=re.I)
        if re.search(r'\b(?:нужен|нужна|нужно|хочу|хотел[аи]?\s+бы|также|ещ[её]|теперь)\s+'
                     r'(?:его\s+|принтер\s+)?(?:ремонт|починить|настроить|подключить|заправить)|'
                     r'\bне\s+(?:нужна\s+)?диагностик', subject, re.I):
            active = {}
    return active

_ADDRESS_QUESTION = re.compile(r"адрес|улиц|номер дома|где.*находит|квартир", re.IGNORECASE)
_CALL = re.compile(r"звон[иы]|связ[ьи]|для связи|связыва|контактн", re.IGNORECASE)
_CORRECTION = re.compile(r"исправ|ошиб|неверн|правильн|на самом деле|другой адрес|вместо", re.IGNORECASE)
_PHONE_MIXUP = re.compile(r'\b(?:(?:цифру|цыфру|номер|телефон)\s+перепутал[аи]?|перепутал[аи]?\s+(?:цифру|цыфру|номер|телефон))\b', re.IGNORECASE)
_PRIVATE_HOUSE = re.compile(r"\bчастн\w*\s+(?:дом|сектор)\b|\bдом\s+частн\w*\b|\bч\.?\s*д\.?\b", re.IGNORECASE)
_PAST_ADDRESS = re.compile(r'\b(?:прежний|старый)\s+адрес\b', re.I)
_CURRENT_ADDRESS = re.compile(r'\b(?:новый|актуальный|текущий)\s+адрес\b|\bадрес\s+(?:выполнения\s+)?работ\b', re.I)
_STREET_WITH_CITY_WORD = re.compile(r"\b(?:ул\.?|улица)\s*(?P<street>город\s+[а-яё-]+(?:\s+[а-яё-]+){0,2})\s+(?:д(?:ом)?\.?\s*)?(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])", re.IGNORECASE)
_TASK_QUANTITY = re.compile(r"\b(?:сделать|просверлить|высверлить|установить|заменить|снять|демонтировать)\s+(?:обычн\w*\s+)?\d+\s+(?:(?:двойн\w*|одинарн\w*)\s+)?(?:штроб\w*|отверсти\w*|розет\w*|подрозет\w*|люстр\w*|выключател\w*)", re.IGNORECASE)
_KITCHEN_QUANTITY = re.compile(r"\bстандартн\w*\s+\d+\s+шкаф\w*", re.IGNORECASE)
_FURNITURE_QUANTITY = re.compile(r'\b(?:такие|эти|вот\s+эти|нужно\s+собрать|собрать|сборка|навесить|повесить)\s+\d+\s+(?:кухонн\w*\s+)?(?:шкаф\w*|тумб\w*|комод\w*|стул\w*)', re.IGNORECASE)
_OS_VERSION = re.compile(r"\b(?:троян|вирус\w*)\s*[, ]+\d+\s+(?:виндоус|виндовс|windows)\b", re.IGNORECASE)
_VENUE = re.compile(r"\b(?:жд\s+|ж[./]д\s+|железнодорожн\w*\s+)?вокзал\w*\b", re.IGNORECASE)
_VENUE_LOCATION = re.compile(r"\b(?:мы\s+)?(?:находимся|нахожусь)\b", re.IGNORECASE)
_ENTRANCE_LANDMARK = re.compile(r"\b(?:вход\w*|подъезд(?:\s+(?:один|\d{1,2}|первый|второй|третий))?)\s*[-–—]?\s*(?:со\s+стороны|сбоку|со\s+двора)|\bкалитка\b.{0,35}(?:вход|со\s+стороны)", re.IGNORECASE)
_APPROACH_LANDMARK = re.compile(r"\b(?:не\s+)?доезжая\s+до\b", re.IGNORECASE)
_ACCESS_NOTE = re.compile(r"\bдомофон\s+не\s+(?:работает|подключен)|\b(?:гараж\w*|калитк\w*|ворот\w*).{0,60}(?:встреч|позвон)|(?:подожд\w*|встреч\w*).{0,30}(?:калитк\w*|ворот\w*)", re.IGNORECASE)
_DOOR_CODE = re.compile(r"\bкод\s+(?:на\s+двери|от\s+двери|двери)\s*[:№\-–—]?\s*(\d{1,6}(?:\s*[#*]\s*\d{1,6})*[#*]*)(?![\dа-яёa-z#*])(?!\s*(?:руб|₽|р\b))", re.IGNORECASE)
_EDGE_ENTRANCE = re.compile(r"\bподъезд\s+крайн\w*(?:[^.\n]{0,50})", re.IGNORECASE)
_SNT_NUMBERED_STREET = re.compile(r"^(?P<place>снт\s+[а-яё][а-яё -]{1,45}?)\s+ул(?:ица)?\.?\s*(?P<street>\d{1,3}[а-яё]?)\s+д(?:ом)?\.?\s*(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])", re.IGNORECASE)
_PARENTHETICAL_PLACE = re.compile(r"\b(?:ул\.?|улица)\s+[а-яё -]+\s*\([а-яё -]+\)\s*д(?:ом)?\.?\s*\d", re.IGNORECASE)
_STREET_CONFIRMATION = re.compile(r"^(?:ул(?:ица)?\.?\s+)?(?P<street>[а-яё-]+(?:\s+[а-яё-]+){0,2}?)(?:\s*,\s*|\s+)(?:же\s+)?правильно\s+понимаю\s*\??$", re.IGNORECASE)
_NON_STREET_CONFIRMATION = re.compile(r"\b(?:квартир\w*|домофон\w*|подъезд\w*|дом|этаж|номер|вс[её]|адрес|я|вы|мы|это|то|так|здесь|там|значит|город|время|сегодня|завтра|сейчас|цена|стоимость|можно|можете|сможете)\b", re.IGNORECASE)
_REVERSED_ENTRANCE = re.compile(r"\bпод\s+(\d{1,2})(?!\d)\b(?!\s*этажом\b)(?=\s*(?:домофон|дмф|этаж|эт\b|$|[,.;]))", re.IGNORECASE)
_INTERCOM_CODE = re.compile(r"\b(?:домофон(?:а|е|ом)?|дмф)\s*(?:(?:так\s*же|тоже)\s+)?[:№\-–—]?\s*([а-яёa-z]{0,2}\d{1,6}(?:\s*[#*]\s*\d{1,6})*[#*]*(?:[а-яёa-z]{1,2})?)(?![\dа-яёa-z#*])(?!\s*(?:руб|₽|р\b))", re.IGNORECASE)
_REVERSED_INTERCOM_CODE = re.compile(r'(?:^|[,;\n])\s*([а-яёa-z]{0,2}\d{1,6}(?:\s*[#*]\s*\d{1,6})*[#*]*(?:[а-яёa-z]{1,2})?)\s+(?:домофон|дмф)\b', re.IGNORECASE)
_INTERCOM_PRICE = re.compile(r"\b(?:домофон[а-яё]*|дмф)\s*(?:(?:так\s*же|тоже)\s+)?[:№\-–—]?\s*\d+(?:[.,]\d+)?\s*(?:руб\w*|₽|р\b)", re.IGNORECASE)
_NUMBERED_PLACE_HOUSE = re.compile(r"^(?:адрес\s*[:—-]?\s*)?(?P<place>(?:(?:микрорайон|мкр\.?)\s*)?[а-яё][а-яё -]{1,50}\d{1,3}[а-яё]?)\s*,\s*д(?:ом)?\.?\s*(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])", re.IGNORECASE)
_REVERSED_NUMBERED_PLACE = re.compile(r"^(?P<place>\d{1,3}\s*[а-яё]?\s*(?:мкр\.?|микрорайон|квартал))\s*,?\s*д(?:ом)?\.?\s*(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])", re.IGNORECASE)
_HOUSE_BLOCK = re.compile(r'(?<![\w/])(?:д(?:ом)?\.?\s*)?(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)\s+(?:блок|бл\.?)\s*(?P<block>\d{1,3}[а-яё]?)(?![\w/])', re.IGNORECASE)
_POSTFIX_PLACE_HOUSE = re.compile(r"^(?P<place>\d{1,3}(?:-й)?\s+(?:мкр(?:-н)?\.?|микрорайон|квартал))\s*,?\s*(?P<house>\d{1,4}[а-яё]?)\s+дом\b", re.IGNORECASE)
_SPLIT_MOBILE = re.compile(r"(?m)^[ \t]*(?P<a>[78]9\d{2})[ \t]*\r?\n[ \t]*(?P<b>\d{4})[ \t]*\r?\n[ \t]*(?P<c>\d{3})[ \t]*$")
_MID_NUMBERED_PLACE = re.compile(r"\b(?P<place>(?:микрорайон|мкр\.)\s*[а-яё][а-яё -]{1,60}\d{1,3}[а-яё]?)\s*,\s*д(?:ом)?\.?\s*(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])", re.IGNORECASE)
_PHONE_AFTER_ACCESS = re.compile(r"(?P<code>\d{1,4}#\d{1,6})[ \t]+(?P<phone>[78]-9\d{2}-\d{3}-\d{2}-\d{2})(?!\d)")
_ROOM = re.compile(r"\bкомнат[аеу]?\s*[:№.]?\s*(\d{1,4})(?![\dа-яёa-z])(?=\s*(?:[,.;]|$|\+?[78]\d{2}))", re.IGNORECASE)
_UNIT_CHOICE_QUESTION = re.compile(r"^квартира\s+(\d{1,4})\s*\?\s*или\s+(?:строение|корпус)\s*\??$", re.IGNORECASE)
_EXPLICIT_BACKUP = re.compile(r"если.{0,50}(?:не\s+буду\s+отвечать|не\s+отвеч\w*|не\s+дозвон\w*).{0,60}(?:(?:по)?звон\w*|набер\w*)|на\s+всякий\s+случай\s+(?:другой\s+)?номер", re.IGNORECASE)
_BACKUP_FOLLOWUP = re.compile(r"^второй\s+(?:номер\s+)?на\s+всякий\s+случай[.!\s]*$", re.IGNORECASE)
_ABBREV_ENTRANCE = re.compile(r"(?<!\w)(\d{1,2})\s+под\b(?=\s+дмф\s*\d)", re.IGNORECASE)
_POSTFIX_SHORT_ENTRANCE = re.compile(r'(?<!\w)(\d{1,2})\s+под\.?(?=\s*(?:\d{1,2}\s*(?:этаж|эт\b)|домофон|дмф|[,.;]|$))', re.I)
_DIAL_INTERCOM_CODE = re.compile(r'\bдомофон(?:а|е|ом)?\s+(?:набир|набер|наберите|набирать|набрать)\s*[:№-]?\s*(\d{1,6}(?:[#*]\d{1,6})*[#*]*)(?![\w#*])(?!\s*(?:руб|₽|р\b))', re.I)
_PLAIN_ACCESS_CODE = re.compile(r'\bкод\s*[:№-]?\s*(\d{1,6}(?:[#*]\d{1,6})*[#*]*)(?![\w#*])(?!\s*(?:руб|₽|р\b))', re.I)
_MID_NUMBERED_PLACE_HOUSE = re.compile(r'(?:^|[,\n])\s*(?P<place>[а-яё][а-яё -]{1,50}\d{1,3}[а-яё]?)\s*,?\s*д(?:ом)?\.?\s*(?P<house>\d{1,4}(?:/\d{1,3})?[а-яё]?)(?![\w/])', re.I)
_TYPED_CITY_ADDRESS = re.compile(r'(?:^|[\n,])\s*(?:г\.|город)\s*([а-яё-]+(?:[ \t]+(?!ул(?:ица)?\b|проспект\b)[а-яё-]+){0,2})', re.I)
_UNLABELLED_UNIT = re.compile(r"^\s*,\s*(\d{1,4})\s*\((?=[^)]*(?:подъезд|этаж|домофон))", re.IGNORECASE)
_TYPED_STREET = re.compile(r"\b(?:улиц\w*|ул\.|проспект\w*|пр-т|переул\w*|пер\.|бульвар\w*|шоссе|набережн\w*)", re.IGNORECASE)
_SHOP_NAME = re.compile(r"\bотдел\s+Смартфон\s+\d+\b", re.IGNORECASE)
_PHONE_CHOICE_QUESTION = re.compile(r"на\s+какой.{0,50}номер\w*.{0,30}звонить|какой\s+из.{0,40}номер\w*.{0,30}(?:связи|звонить)", re.IGNORECASE)
_PHONE_ORDINAL_ANSWER = re.compile(r"^\s*(?:на\s+)?(первый|второй)(?:\s+(?:номер|телефон))?[.!\s]*$", re.IGNORECASE)
_FINAL_ADDRESS_QUESTION = re.compile(r"окончательн\w*\s+адрес|подтверд\w*.{0,25}адрес\s+для\s+выезда", re.IGNORECASE)
_BEFORE_VISIT = r"(?:перед\s+(?:вашим\s+)?(?:выезд|приезд|приход)|до\s+(?:выезд|приезд|приход)|до\s+того\s+как\s+подъех)"
_CALL_BEFORE = re.compile(r"(?:позвон\w*|набер\w*).{0,70}" + _BEFORE_VISIT + "|" + _BEFORE_VISIT + r".{0,70}(?:позвон\w*|набер\w*)", re.IGNORECASE)
_ARRIVAL_CALL = re.compile(r'(?:позвоните|позвонить|наберите|набрать)[^.!?\n]{0,50}(?:(?:когда|как)\s+(?:подъед[еи]те|подойд[её]те|приед[еи]те)\b|(?:как|когда)\s+буд(?:ете|ите|ут)\s+подъезжать|когда\s+буд(?:ете|ите)\s+у\s+подъезда)|'
                           r'(?:когда|как)\s+(?:подъед[еи]те|подойд[её]те|приед[еи]те)\b[^.!?\n]{0,50}(?:позвоните|позвонить|наберите|набрать)',re.I)
_INTERCOM_ACCESS_CALL = re.compile(
    r'\bдомофон(?:а)?\s*(?:нет|не\s+работает|отсутствует)\b'
    r'[^.!?\n]{0,80}\b(?:поэтому|так\s+что)\b'
    r'[^.!?\n]{0,80}\b(?:позвоните|позвонить|наберите|набрать)\b|'
    r'\bдомофон(?:а)?\s*(?:нет|не\s+работает|отсутствует)\b'
    r'\s*[,;—-]?\s*(?:пожалуйста\s*[,;]?\s*)?'
    r'\b(?:позвоните|позвонить|наберите|набрать)\b|'
    r'\b(?:позвоните|позвонить|наберите|набрать)\b'
    r'(?:\s+(?:мне|нам|пожалуйста|по\s+(?:телефону|номеру))){0,3}'
    r'\s*[,;—-]?\s*\bдомофон(?:а)?\s*(?:нет|не\s+работает|отсутствует)\b', re.I)
_GATE_ACCESS_CALL = re.compile(
    r'\b(?:позвоните|позвонить|наберите|набрать)\b[^.!?\n]{0,60}'
    r'\b(?:открою|откроем)\s+(?:вам\s+)?(?:ворота|калитку)\b', re.I)
_OTHER_ACCESS_CALL_TIME = re.compile(r'\bсейчас\b|\bпосле\s+(?:ремонта|работ|визита)\b', re.I)
_ADVANCE_CALL = re.compile(r"(?:позвоните|звонить|наберите|наберете).{0,30}заранее|заранее.{0,30}(?:позвоните|звонить|наберите|наберете)|(?:позвоните|наберите).{0,30}(?:(?:как|когда)\s+будете\s+выезжать|как\s+собер[её]тесь)|за\s+\d+\s+час\w*.{0,25}(?:наберете|позвоните)", re.IGNORECASE)
_MINUTES_CALL = re.compile(r"\b(?:позвоните|позвонить|наберите|набрать)\s+(?:минут\s+за\s+\d{1,3}|за\s+\d{1,3}\s+минут)\b|\bза\s+(?:час|полчаса|\d{1,3}\s+(?:минут\w*|час\w*))\s+(?:желательно\s+|пожалуйста\s+)?(?:позвоните|позвонить|наберите|набрать)\b", re.IGNORECASE)
_NO_CALL = re.compile(r"\bне\s+(?:звоните|набирайте|(?:надо|нужно)\s+(?:звонить|набирать))|\b(?:звонить|набирать|позвонить)\s+не\s+(?:нужно|надо)", re.IGNORECASE)
_ACCESS_ORDINALS = {'один': '1', 'первый': '1', 'второй': '2', 'третий': '3', 'четвертый': '4',
                    'пятый': '5', 'шестой': '6', 'седьмой': '7', 'восьмой': '8',
                    'девятый': '9', 'десятый': '10', 'одиннадцатый': '11', 'двенадцатый': '12'}
_WORD_ACCESS = re.compile(r'\b(подъезд|этаж)\s+(' + '|'.join(_ACCESS_ORDINALS) + r')\b', re.IGNORECASE)
_ONE_ENTRANCE = re.compile(r'\bодин\s+под[ъь]езд\b|\bпод[ъь]езд\s+один\b', re.I)
_ACCESS_LANDMARK = re.compile(r'нумераци\w*\s+подъезд\w*\s+наоборот|\bлифт\s+(?:не\s+)?работает\b', re.IGNORECASE)
_CREW_REQUEST = re.compile(r'\b(?:нужн[оы]|требуются)\s+(?:будет\s+)?(два|двое|2|один|1)\s+(?:человека?|мастер[аов]*|исполнител[яей]*)\b', re.IGNORECASE)
_QUIET_PERIOD = re.compile(r'\b(?:режим\s+тишины|тихий\s+час)\b[^.!?\n]{0,45}\b(?:с|от)\s*\d{1,2}(?:[:.]\d{2})?\s*(?:до|[-–—])\s*\d{1,2}(?:[:.]\d{2})?', re.I)


def _arrival_call_requested(text):
    if _ARRIVAL_CALL.search(text) and not any(p.search(text) for p in (_CALL_BEFORE,_ADVANCE_CALL,_MINUTES_CALL)):
        return True
    # An absent intercom explains this call's purpose. An explicitly requested
    # advance/later call still keeps its own timing instead of becoming arrival.
    return bool((_INTERCOM_ACCESS_CALL.search(text) or _GATE_ACCESS_CALL.search(text)) and not any(pattern.search(text)
        for pattern in (_CALL_BEFORE, _ADVANCE_CALL, _MINUTES_CALL, _OTHER_ACCESS_CALL_TIME)))


def _call_request_quote(text):
    if len(text) <= 500:
        return text
    matches = [match for pattern in (_CALL_BEFORE, _ADVANCE_CALL, _MINUTES_CALL,
                                     _ARRIVAL_CALL, _INTERCOM_ACCESS_CALL, _GATE_ACCESS_CALL)
               if (match := pattern.search(text))]
    start = max(0, min(match.start() for match in matches) - 60) if matches else 0
    return text[start:start + 500]


def _split_named_city_before_street(parsed):
    """Separate a client-typed city before an explicit street label.

    A phone/colon or lower-case city can bypass the legacy city-head parser.
    Only a known city followed by a street label and a nonempty street name
    qualifies; the advertising city never supplies this observed city.
    """
    if not parsed or not parsed.street:
        return parsed
    match = re.fullmatch(r'\s*(?P<city>[а-яё]+(?:[ -][а-яё]+){0,2})\s+'
                         r'(?:улица|ул\.?)\s+(?P<street>.+?)\s*', parsed.street, re.I)
    if not match:
        return parsed
    from contact_cities import city_by_name
    city = city_by_name(match['city'])
    if not city or parsed.locality and parsed.locality.casefold() != city.name.casefold():
        return parsed
    return replace(parsed, street=match['street'], locality=city.name)


def _non_address_candidate(parsed, text):
    """Reject source-proven quantities, never an explicitly typed street.

    The legacy C-level parser accepts capitalized words before digits. In the
    reviewed histories these were a task verb, an OS version and a station
    name. Do not discard all C-level addresses or all long client messages.
    """
    # An address question can promote the same weak legacy candidate to A.
    # Require a street-type token in the candidate, not that promotion alone.
    if not parsed or _TYPED_STREET.search(parsed.raw or ""):
        return False
    for pattern in (_TASK_QUANTITY, _KITCHEN_QUANTITY, _FURNITURE_QUANTITY, _OS_VERSION):
        if any(m.start() < parsed.end and m.end() > parsed.start for m in pattern.finditer(text)):
            return True
    if any(m.start() < parsed.end and m.end() > parsed.start
           for m in re.finditer(r'\b\d+(?:[.,]\d+)?\s*[*×]\s*\d+(?:[.,]\d+)?\b', text)):
        return True
    return bool(_VENUE.search(parsed.street or "") and _VENUE_LOCATION.search(text))


def _address_reference_role(messages, index, text, parsed, references=(), current_worksite=None):
    """Classify an explicitly non-work address; never guess from 'meet' alone."""
    if not parsed or not parsed.street or not parsed.house:
        return ''
    head = text[:parsed.end]
    previous = [m for m in _PAST_ADDRESS.finditer(head) if not re.search(r'\bне\s*$', head[:m.start()], re.I)]
    current = list(_CURRENT_ADDRESS.finditer(head))
    if previous and (not current or previous[-1].start() > current[-1].start()):
        return 'previous'
    worksite = re.search(r'\bадрес\s+(?:выполнения\s+)?работ\b|\bработать\s+(?:нужно|будем)\b', text, re.I)
    if worksite:
        return ''
    if re.search(r'\b(?:адрес|место)\s+(?:встречи|сбора)\b', text, re.I):
        return 'meeting'
    if re.search(r'\bэто\s+(?:как\s+)?ориентир\b|\bадрес\s+(?:только\s+|как\s+)ориентир\b|^\s*ориентир\s*:', text, re.I):
        return 'landmark'
    pickup = re.compile(r'\b(?:забрат|забер|подобрат|подбер)\w*\s+(?:меня|нас)\b|'
                        r'\bзабер[её]м\b[^.!?\n]{0,80}\bпоедем\b|'
                        r'\bза\s+мной\s+заех', re.I)
    if pickup.search(text):
        return 'meeting'
    # A later neutral repeat retains the established role of this exact point.
    # An explicit worksite assertion above, or an already confirmed worksite,
    # takes precedence over a previous pickup reference.
    current_worksite = current_worksite or {}
    if (_same_street(current_worksite.get('street', ''), parsed.street)
            and current_worksite.get('building') == parsed.house):
        return ''
    for reference in reversed(references):
        point = reference.get('address') or {}
        if (_same_street(point.get('street', ''), parsed.street)
                and point.get('building') == parsed.house):
            return reference['role']
    # Two requested addresses can share one staff turn. A client response
    # naming the previously requested pickup street still describes pickup.
    previous_client = next((m for m in reversed(messages[max(0, index - 5):index]) if _incoming(m)), {})
    previous_text = _text(previous_client)
    street = re.sub(r'^\s*(?:ул\.?|улица)\s+', '', parsed.street, flags=re.I)
    if pickup.search(previous_text) and street and re.search(re.escape(street), previous_text, re.I):
        return 'meeting'
    return ''


def _client_intent_message(message):
    """Explicit direction/actor wins over a legacy role alias for new intents."""
    direction = message.get('direction')
    sender = str(message.get('sender_type') or message.get('by') or '').casefold()
    return ((direction == 'in' or not direction and message.get('role') in ('user', 'client'))
            and sender in ('', 'client', 'customer', 'contact', 'user', 'lead'))


_ELECTRICAL_OBJECTS = {
    'socket': r'розет(?:к\w*|ок)',
    'switch': r'выключател\w*',
    'chandelier': r'люстр\w*',
    'light': r'светильник\w*|бра',
}


def electrical_condition_mentions(text):
    """Literal object/condition spans, without sharing across another request."""
    text = str(text or '')
    noun = r'(?:' + '|'.join(_ELECTRICAL_OBJECTS.values()) + r')'
    group = noun + r'(?:\s*(?:,\s*|\s+и\s+)' + noun + r')*'
    condition = r'(?:не\s*работа\w*|неисправ\w*|сломан\w*|работа(?:ет|ют)|исправн\w*)'
    # A comma listing two nouns can share a predicate. A comma between two
    # explicit predicates cannot: "socket broken, chandelier works".
    view = list(text)
    for comma in re.finditer(',',text):
        left = max(text.rfind(c,0,comma.start()) for c in '.!?;\n') + 1
        ends = [i for c in '.!?;\n' if (i := text.find(c,comma.end())) >= 0]
        right = min(ends) if ends else len(text)
        if (re.search(condition,text[left:comma.start()],re.I)
                and re.search(condition,text[comma.end():right],re.I)):
            view[comma.start()] = ';'
    view = ''.join(view)
    modifiers = r'(?:(?:несколько|некоторые|все|обе|оба|две|два|одна|один|потолочн\w*|нов\w*)\s+){0,3}'
    patterns = [r'\b(?P<condition>' + condition + r')\s+' + modifiers + r'(?P<objects>' + group + r')\b',
                r'\b(?P<objects>' + group + r')\s*(?:[—:-]\s*)?(?:(?:уже|сейчас|теперь)\s+)?(?P<condition>' + condition + r')\b']
    quoted = [(m.start(),m.end()) for m in re.finditer(r'«[^»]*»|“[^”]*”|"[^"\n]*"',text)]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern,view,re.I):
            start = max(view.rfind(c,0,match.start()) for c in '.!?;\n') + 1
            ends = [i for c in '.!?;\n' if (i := view.find(c,match.end())) >= 0]
            end = min(ends) + 1 if ends else len(text)
            clause = text[start:end]
            before = text[start:match.start()]
            mode = 'asserted'
            if any(a <= match.start() < b for a,b in quoted):
                mode = 'quoted'
            elif re.search(r'не\s+подтвержден\w*|неверно|неправда|не\s+значит',clause,re.I):
                mode = 'not_asserted'
            elif '?' in clause:
                mode = 'question'
            elif re.search(r'\bесли\b|\bвдруг\b|\bбудет\b|\bбудут\b',clause,re.I):
                mode = 'hypothetical'
            elif re.search(r'\bвозможно\b|\bкажется\b|\bпохоже\b|\bнаверн\w*|может\s+быть|не\s+знаю|\bили\b',clause,re.I):
                mode = 'uncertain'
            elif re.search(r'сказал|говорит|со\s+слов|по\s+слов|написал',clause,re.I):
                mode = 'attributed'
            elif (re.search(r'\bвчера\b|\bраньше\b|\bранее\b|\bпрежде\b',clause,re.I)
                  or re.fullmatch(r'не\s*работал[аои]?',match['condition'],re.I)):
                mode = 'past'
            elif re.search(r'\bне\s*$',before,re.I) and not match['condition'].lower().startswith('не работ'):
                mode = 'not_asserted'
            for obj in re.finditer(r'\b' + noun + r'\b',match['objects'],re.I):
                key = next(k for k,p in _ELECTRICAL_OBJECTS.items() if re.fullmatch(p,obj[0],re.I))
                state = ('not_working' if re.match(r'не|сломан',match['condition'],re.I) else 'working')
                value = dict(object=key,condition=state,mode=mode,quote=clause.strip())
                if value not in found:
                    found.append(value)
    return found


def electrical_condition_context(messages):
    """Absence of a fault report is unknown, never a claim that an item works."""
    import assistant_prices
    noun = r'\b(?:' + '|'.join(_ELECTRICAL_OBJECTS.values()) + r')\b'
    objects, evidence, clauses = {}, [], []
    for message in assistant_prices.current_enquiry_messages(messages):
        if (not _client_intent_message(message) or not message.get('id')
                or str(message.get('delivery_status') or '').lower() in ('failed','error','pending','queued','sending')):
            continue
        body = _text(message)
        if re.match(r'^\s*(?:новый|другой)\s+заказ\b|^\s*новое\s+обращение\b',body,re.I):
            objects, evidence, clauses = {}, [], []
        for match in re.finditer(noun,body,re.I):
            key = next(k for k,p in _ELECTRICAL_OBJECTS.items() if re.fullmatch(p,match[0],re.I))
            objects.setdefault(key,dict(nonworking_status='not_reported',working_status='not_reported',evidence_ids=[]))
        # Keep exact, object-bound source clauses before asking the model to
        # paraphrase. A separate "с люстрами разобраться" must not inherit
        # the preceding socket predicate. Shared noun lists remain intact.
        for clause in re.split(r'[.!?;\n]+|\s+(?=(?:и|а)\s+с\s+)', body):
            clause = clause.strip()
            for match in re.finditer(noun,clause,re.I):
                key = next(k for k,p in _ELECTRICAL_OBJECTS.items() if re.fullmatch(p,match[0],re.I))
                entry = dict(object=key,message_id=message['id'],quote=clause,
                             object_literal=match[0],source='exact_client_clause')
                if entry not in clauses:
                    clauses.append(entry)
        for mention in electrical_condition_mentions(body):
            evidence.append(dict(mention,message_id=message['id'],source='literal_client_span'))
            if mention['mode'] == 'asserted':
                state = objects[mention['object']]
                field = 'nonworking_status' if mention['condition']=='not_working' else 'working_status'
                other = 'working_status' if field=='nonworking_status' else 'nonworking_status'
                state[field],state[other] = 'reported','not_reported'
                if message['id'] not in state['evidence_ids']:
                    state['evidence_ids'].append(message['id'])
    return dict(objects=objects,evidence=evidence,client_source_clauses=clauses,
                source='literal_client_spans',not_a_diagnosis=True) if objects else {}


def unsupported_electrical_condition(prose, context):
    return any(m['mode'] == 'asserted'
               and context.get('objects',{}).get(m['object'],{}).get(
                   'nonworking_status' if m['condition']=='not_working' else 'working_status') != 'reported'
               for m in electrical_condition_mentions(prose))


def work_placement_answers(messages):
    """An observed question's literal place answer does not order nearby work."""
    import assistant_prices
    room = r'(?:на\s+кухне|в\s+(?:ванной|туалете|санузле|подвале|комнате|квартире)|на\s+даче)'
    nearby = (r'(?:под|над|за|возле|у|рядом\s+с)\s+(?:раковин(?:ой|ы)|мойк(?:ой|и)|ванной|унитаз(?:ом|а)|'
              r'стиральной\s+машин(?:ой|ы)|шкаф(?:ом|а)|стол(?:ом|а))')
    place = r'(?:(?:не\s+)?(?:' + room + '|' + nearby + r'))'
    literal = (r'\s*(?:(?:он|она|оно)\s+(?:(?:стоит|находится|расположен[ао]?)\s+)?)?'
               + place + r'(?:\s*(?:,\s*(?:а\s+)?|\s+и\s+|\s+)' + place + r')*[.!\s]*')
    subject, question, result = None, None, []
    for message in assistant_prices.current_enquiry_messages(messages):
        body = _text(message).strip()
        bad = (message.get('out_pending') or str(message.get('delivery_status') or '').lower()
               in ('failed','error','pending','queued','sending'))
        if message.get('direction') == 'out':
            question = None
            if (not bad and message.get('id') and message.get('sender_type') in ('',None,'operator','staff','employee','human')
                    and not re.search(r'[«»“”"]',body)
                    and re.search(r'\b(?:где|какой|какая|какое|какие|куда)\b|что\s+за',body,re.I)):
                question = message
            continue
        if not _client_intent_message(message) or bad or not message.get('id') or not body:
            continue
        if subject and question and re.fullmatch(literal,body,re.I):
            result.append(dict(message_id=message['id'],quote=body,question_message_id=question['id'],
                subject_message_id=subject['id'],subject_quote=_text(subject),source='client_placement_answer',
                requested_service_changed=False,exclude_from_service_selection=True))
        elif (not re.fullmatch(r'здравствуйте[.!\s]*|добрый\s+(?:день|вечер)[.!\s]*|доброе\s+утро[.!\s]*',body,re.I)
                and re.search(r'[а-яё]{4}',body,re.I)):
            subject, question = message, None
    return result


def work_location_references(messages):
    """Only location clauses are masked in the service-selection view."""
    import assistant_prices
    references, address_question = [], None
    location = r'\b(?:ориентир|район|рядом|неподал[её]ку)\b'
    work = r'\b(?:почин|поменя|замен|ремонт|установ|вскры|откры|собра|разобра|нужно|надо|требуется)\w*'
    for message in assistant_prices.current_enquiry_messages(messages):
        body = _text(message).strip()
        bad = (message.get('out_pending') or str(message.get('delivery_status') or '').lower()
               in ('failed','error','pending','queued','sending'))
        if message.get('direction') == 'out':
            address_question = message if (not bad and message.get('id')
                and message.get('sender_type') in ('',None,'operator','staff','employee','human')
                and not re.search(r'[«»“”"]',body)
                and re.search(r'адрес|улиц|где[^.!?]{0,20}(?:жив[её]те|работ)',body,re.I)) else None
            continue
        if not _client_intent_message(message) or bad or not message.get('id'):
            continue
        if re.match(r'^\s*(?:новый|другой)\s+заказ\b|^\s*новое\s+обращение\b',body,re.I):
            references, address_question = [], None
        for clause in re.split(r'[.!?;\n]+',body):
            clause = clause.strip()
            if (not clause or not re.search(location,clause,re.I) or re.search(work,clause,re.I)
                    or re.search(r'сказал|спросил|цитат',clause,re.I)):
                continue
            explicit = bool(re.match(r'^\s*(?:это\s+)?ориентир\b',clause,re.I))
            if not explicit and re.search(r'[«»“”"]',clause):
                continue
            if not explicit and not address_question:
                continue
            references.append(dict(message_id=message['id'],quote=clause,
                question_message_id=(address_question or {}).get('id',''),
                source='client_location_reference',map_verified=False,
                exact_address_verified=False,exclude_from_service_selection=True))
    return references


def furniture_transport_operations(messages):
    """Requested disassembly/packing is separate from later assembly."""
    import assistant_prices, assistant_catalog
    furniture = r'\b(?:мебел\w*|шкаф\w*|гарнитур\w*|кроват\w*|трюмо|комод\w*|стол\w*|стуль\w*)'
    operations = {'disassembly': r'\b(?:разобрать|разбирать|разбор(?:ка|ки|ку|ом)?|демонтировать)\b',
                  'packing': r'\b(?:упаковать|упаковывать|упаковк\w*|обмотать\s+пл[её]нк\w*)\b'}
    result, subject = {}, False
    for message in assistant_prices.current_enquiry_messages(messages):
        body = _text(message)
        if (not _client_intent_message(message) or not message.get('id')
                or str(message.get('delivery_status') or '').lower() in ('failed','error','pending','queued','sending')):
            continue
        if re.match(r'^\s*(?:новый|другой)\s+заказ\b|^\s*новое\s+обращение\b',body,re.I):
            result, subject = {}, False
        view = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', body)
        if re.search(furniture,view,re.I):
            subject = True
        if not subject:
            continue
        if re.search(r'^\s*(?:теперь|передумал[аи]?)\b[^.!?\n]{0,35}\bтолько\s+(?:собрать|сборк\w*)\b',view,re.I):
            result = {}
        for operation, pattern in operations.items():
            if re.search(pattern + r'\s+(?:больше\s+)?не\s+(?:нуж\w*|надо)|не\s+(?:нужно|надо|хочу)\s+' + pattern,view,re.I):
                result.pop(operation,None)
            for clause in assistant_catalog._requested_work_clauses(view,pattern):
                independent = (re.search(r'\b(?:сам|сама|сами)\b',clause,re.I)
                    and not re.search(r'не\s+(?:могу|можем|получается)|не\s+справл\w*|помоги\w*',clause,re.I))
                if (independent or re.search(r'\b(?:уже|купил\w*|забрал\w*)\b',clause,re.I)
                        or re.search(r'ноутбук|компьютер|насос|принтер|двер\w*',clause,re.I)
                        and not re.search(furniture,clause,re.I)):
                    continue
                result[operation] = dict(operation=operation,message_id=message['id'],quote=clause.strip(),
                                         source='client_requested_operation',execution_approved=False)
    return list(result.values())


def service_destination_hint(messages, address=None, evidence=None):
    """An answer to an address question is a work-place hint, not map proof."""
    result = {}
    for index, message in enumerate(messages):
        if not _client_intent_message(message):
            continue
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', _text(message))
        previous = next((m for m in reversed(messages[:index]) if m.get('direction') == 'out'), {})
        address_prompt = (not previous.get('out_pending')
                          and str(previous.get('delivery_status') or '').lower() not in ('failed', 'error', 'pending', 'queued', 'sending')
                          and re.search(r'адрес|где[^.!?\n]{0,25}работ', _text(previous), re.I))
        found = re.search(r'\b(?:надо|нужно|требуется)\s+(?:ехать|доехать|подъехать)\s+в\s+сторону\s+'
                          r'(?P<place>[а-яё-]{3,50}(?:\s*\([^()\n]{2,60}\))?)', body, re.I)
        if (found and not re.search(r'\bне\s*$|\b(?:мастер|сосед|клиент)\w*[^.!?\n]{0,25}(?:сказал|писал)', body[:found.start()], re.I)
                and (address_prompt or re.search(r'адрес\s+работ|работы\s+(?:надо|нужно)', body, re.I))):
            result = dict(message_id=message.get('id', ''), quote=_text(message),
                          value=found['place'].strip(), source='client_address_answer',
                          question_message_id=previous.get('id', '') if address_prompt else '',
                          status='unverified_work_destination', map_verified=False)
    if result and address and address.get('city') and address.get('building'):
        # Only an explicit, later complete work address can replace this hint.
        # A city of origin or a pickup point must not erase the destination.
        evidence = evidence or {}
        city_id = evidence.get('address.city', {}).get('message_id')
        building_id = evidence.get('address.building', {}).get('message_id')
        positions = {m.get('id'): i for i, m in enumerate(messages)}
        if (city_id and city_id == building_id and city_id in positions
                and positions[city_id] > positions.get(result['message_id'], len(messages))):
            result.update(status='replaced_by_explicit_work_address', replaced_by_message_id=city_id)
    return result


def passenger_pickup_request(messages):
    """A request to carry the client is separate from repair and parts stock."""
    result = {}
    last_out = max((i for i, m in enumerate(messages) if m.get('direction') == 'out'), default=-1)
    for index, message in enumerate(messages):
        if not _client_intent_message(message):
            continue
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', _text(message)).casefold().replace('ё', 'е')
        if re.search(r'не\s+(?:надо|нужно|требуется)[^.!?\n]{0,25}(?:забирать|подбирать)\s+(?:меня|нас)|'
                     r'\bя\s+сам[а]?\s+(?:доберусь|доеду)|\bмы\s+сами\s+(?:доберемся|доедем)', body):
            result = {}
            continue
        person = re.search(r'\b(?:забрат|забер|подобрат|подбер)\w*\s+(?:меня|нас)\b|заехать\s+за\s+мной', body)
        continuation = result and re.search(r'заеха|заберем', body) and re.search(r'\bпоедем\b', body)
        if (re.search(r'\b(?:сосед|муж|жена|друг|такси|курьер)\w*\s+(?:забер|подбер)', body)
                or re.search(r'\b(?:я|мы)\s+(?:сам[аи]?\s+)?(?:заберу|заберем|подберу|подберем)\b', body)):
            continue
        modality = re.search(r'\?|можете|сможете|удобно|прошу|нужно|если|заберите|подберите|заедьте', body)
        if (person or continuation) and modality and not re.search(r'\b(?:не\s+забирайте|не\s+подбирайте)\b', body):
            result = dict(message_id=message.get('id', ''), quote=_text(message),
                          origin_message_id=result.get('origin_message_id') or message.get('id', ''),
                          actor='service', passenger='client', status='requested_not_verified',
                          vehicle_available=None, approval_confirmed=False,
                          latest_is_request=index > last_out)
    if result:
        result['latest_is_request'] = next((i for i, m in enumerate(messages) if m.get('id') == result['message_id']), -1) > last_out
    return result


def client_call_permission(messages):
    """Permission for the client to call us, not a requested outbound call."""
    if not messages or not _client_intent_message(messages[-1]):
        return {}
    message = messages[-1]
    body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', _text(message)).casefold().replace('ё', 'е')
    if (re.search(r'перенес|отмен|запис|приед|приеха|адрес|цен[аыуе]|стоим|жалоб|обещ|жду|ждем', body)
            or re.search(r'\b(?:маме|папе|ему|ей|клиенту|соседу)\b', body)
            or re.search(r'\bне\s+(?:по|пере)звонить\b', body)):
        return {}
    if not re.search(r'\b(?:можно(?:\s+ли)?|могу(?:\s+ли)?)\s+'
                     r'(?:(?:я|мне|вам|сейчас|сегодня|уже|потом|позже|вечером|пожалуйста|снова)\s+){0,5}'
                     r'(?:по|пере)звонить\b', body):
        return {}
    return dict(message_id=message.get('id', ''), quote=_text(message), caller='client',
                recipient='service', requested_time='now' if 'сейчас' in body else 'unspecified',
                call_completed=False, service_availability_confirmed=False)


def active_furniture_scope(messages):
    """Only an explicit client narrowing changes classification, not history."""
    scope = None
    for index, message in enumerate(messages):
        if not _incoming(message):
            continue
        body = _text(message)
        match = re.search(r'(?:хотя\s+бы|только)\s+(?:с\s+)?(?:ремонт\w*|почин\w*)[^.!?\n]{0,40}(?:кроват|шкаф|комод|мебел)', body, re.I)
        if match and not re.search(r'не\s+(?:надо|нужно|нужен|нужна)|без\s+ремонт', body, re.I):
            scope = dict(message_id=message.get('id',''), quote=body,
                         text='\n'.join(_text(m) for m in messages[index:] if _incoming(m)),
                         prior_numeric_quote=any(m.get('direction')=='out' and re.search(r'\d\s*(?:руб|₽|р\b)',_text(m),re.I) for m in messages[:index]))
    return scope or {}


def business_payment(messages):
    """Payment method comes from the client, never from a staff suggestion."""
    result = {}
    previous_out = ''
    for message in messages:
        body = _text(message)
        if message.get('direction') == 'out':
            previous_out = '' if message.get('out_pending') else body
            continue
        if not _incoming(message):
            continue
        invoice_phrase = re.search(r'\bпо\s+сч[её]ту\b|выставлен\w*\s+сч[её]т',body,re.I)
        bare_invoice = re.fullmatch(r'\s*(?:(?:да|верно|можно|только|будем|хочу)[,!.\s]+)?по\s+сч[её]ту[.!?\s]*',body,re.I)
        invoice = invoice_phrase and (bare_invoice or re.search(r'оплат|расч[её]т|юр\.?\s*лиц|организац|выставл',body,re.I))
        if re.search(r'не\s+по\s+сч[её]ту|(?:оплачу|оплата|рассчитаюсь)\s+налич',body,re.I):
            result = dict(kind='cash' if re.search(r'налич',body,re.I) else 'other',message_id=message.get('id',''),quote=body,source='client_message')
        elif invoice:
            result = dict(kind='invoice',confirmed='?' not in body and not re.search(r'можно|сможете',body,re.I),message_id=message.get('id',''),quote=body,source='client_message')
        elif re.search(r'защит\w*\s+(?:сделк|платеж)',body,re.I) and re.search(r'онлайн|оплат',body,re.I):
            result = dict(kind='protected_avito',confirmed=False,message_id=message.get('id',''),quote=body,source='client_message')
        elif (re.fullmatch(r'\s*(?:да|верно|правильно)[.!\s]*',body,re.I)
              and re.search(r'\bпо\s+сч[её]ту\b',previous_out,re.I) and not re.search(r'\bили\b',previous_out,re.I)):
            result = dict(kind='invoice',confirmed=True,message_id=message.get('id',''),quote=body,question_quote=previous_out,source='staff_question_client_answer')
    return result


def business_customer(messages):
    """A company is confirmed by the client, not inferred from task quantity."""
    found, previous_out = {}, None
    for message in messages:
        body = _text(message)
        if message.get('direction') == 'out':
            previous_out = None if message.get('out_pending') else message
            continue
        if not _incoming(message):
            continue
        if re.search(r'\b(?:мы|я)\s+не\s+(?:организац|служба\s+доставки)|\bне\s+организация\b|\b(?:я\s+)?для\s+себя\s+заказ', body, re.I):
            found = {}
        elif re.search(r'\bмы\s+(?:организац|служба\s+доставки)|\bот\s+организации\b|'
                       r'\bв\s+организации\b[^.!?\n]{0,25}\b(?:нужно|надо|требуется|необходимо)\b', body, re.I):
            found = dict(message_id=message.get('id', ''), quote=body, source='client_message')
        elif previous_out and re.fullmatch(r'\s*(?:да|верно|правильно)[.!\s]*', body, re.I):
            question = _text(previous_out)
            if re.fullmatch(r'\s*(?:вы\s+)?(?:из\s+)?организац(?:ия|ии)\s*\?\s*', question, re.I):
                found = dict(message_id=message.get('id', ''), quote=body,
                             question_message_id=previous_out.get('id', ''), question_quote=question,
                             source='staff_question_client_answer')
        previous_out = None
    return found


def furniture_manufacture(messages):
    """An answered staff question may clarify the task; asking alone cannot."""
    found = {}
    furniture = r'шкаф|мебел|комод|кухн|тумб|стол'
    for index, message in enumerate(messages):
        if not _incoming(message):
            continue
        body = _text(message)
        if re.search(r'не\s+изготов|собрать\s+готов', body, re.I):
            found = {}
        elif re.search(r'изготов', body, re.I) and re.search(furniture, body, re.I):
            found = dict(confirmed=True,message_id=message.get('id',''),quote=body,source='client_message')
        elif (index and messages[index-1].get('direction') == 'out'
              and not messages[index-1].get('out_pending')
              and re.search(r'изготов', _text(messages[index-1]), re.I)
              and not re.search(r'\bили\b',_text(messages[index-1]),re.I)
              and re.search(furniture,'\n'.join(_text(m) for m in messages[:index] if _incoming(m)),re.I)):
            explicit_manufacture = (re.match(r'^\s*да\b', body, re.I)
                                    and re.search(r'\b(?:сделать|изготовить)\b[^.!?\n]{0,30}(?:шкаф|кладовк|мебел|комод|кухн|тумб|стол)', body, re.I)
                                    and not re.search(r'\?|\bно\b|\bне\b|ремонт|собрать\s+готов', body, re.I))
            if re.fullmatch(r'\s*(?:да|верно|нужно|да[,!\s]+нужно)[.!\s]*',body,re.I) or explicit_manufacture:
                found = dict(confirmed=True,message_id=message.get('id',''),question_message_id=messages[index-1].get('id',''),
                             quote=body,question_quote=_text(messages[index-1]),source='staff_question_client_answer')
            elif re.fullmatch(r'\s*нет[.!\s]*',body,re.I):
                found = {}
    return found


def observed_clog_question(message):
    """A delivered staff question, never a quoted or still pending proposal."""
    body = _text(message)
    return (message.get('direction') == 'out'
            and message.get('sender_type', 'operator') in ('operator', 'employee', 'human', 'staff', 'bot', 'assistant', '')
            and message.get('role') != 'system' and not message.get('out_pending')
            and str(message.get('delivery_status') or message.get('delivery') or '').lower()
            not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')
            and bool(re.search(r'\bзасор\w*\b', body, re.I)) and body.count('?') == 1
            and not re.search(r'[«»“”"]|\b(?:или|не|и|сказал\w*|спрашивал\w*)\b', body, re.I))


def clog_work_context(messages):
    """Keep uncertain/reported blockage separate from requested unblocking.

    This is an evidence projection for selecting a service and its tariff. It
    neither edits history nor establishes a technical diagnosis. Clause scope
    keeps a separately requested sink job after an uncertain toilet report.
    """
    result = dict(uncertain_reports=[], excluded_reports=[], requested_reports=[])
    previous = None
    for position, message in enumerate(messages):
        body = _text(message)
        client = _client_intent_message(message) and message.get('role') not in ('assistant', 'system')
        if client and re.search(r'^\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', body, re.I):
            result = dict(uncertain_reports=[], excluded_reports=[], requested_reports=[])
            previous = None
        if message.get('direction') == 'out':
            previous = message if observed_clog_question(message) else None
            continue
        # Do not treat a system/client role collision as an actual order.
        if not client:
            if re.search(r'засор|прочист', body, re.I):
                result['excluded_reports'].append(dict(message_id=message.get('id', ''), position=position,
                    quote=body, reason='nonclient'))
            continue
        clauses = re.split(r'(?<=[.!?;\n])\s*|\s+Но\s+(?=(?:нужно|надо|требуется|прошу)\b)', body, flags=re.I)
        for clause in clauses:
            quote = clause.strip()
            if not quote:
                continue
            has_clog = bool(re.search(r'засор|прочист', quote, re.I))
            unknown = bool(re.search(r'не\s+(?:знаю|уверен\w*|понимаю)|\bвозможно\b|\bможет\b(?:\s+быть)?|'
                                     r'наверно|вроде|кажется|засор\s+ли|^\s*(?:это\s+)?засор\s*\?\s*$', quote, re.I))
            conditional = bool(re.search(r'\b(?:если|допустим|вдруг)\b', quote, re.I))
            negative = bool(re.search(r'\bзасор\w*\s+нет\b|\bне\s+засор\b|\bнет\s+засор|'
                                     r'не\s+(?:(?:нужно|надо)\s+)?(?:устраня|прочищ|прочист)|'
                                     r'прочист\w*[^.!?\n]{0,25}не\s+нуж', quote, re.I))
            reported = bool(re.search(r'[«»“”"]|\b(?:сказал\w*|говорит|написал\w*|спрашивал\w*)\b', quote, re.I))
            row = dict(message_id=message.get('id', ''), position=position, quote=quote)
            if unknown and not reported and not conditional and (has_clog or previous):
                result['uncertain_reports'].append(dict(row,
                    question_message_id=previous.get('id', '') if previous else '',
                    conditional=conditional))
                # A later correction also withdraws an earlier literal
                # blockage claim about that object. Another named job stays.
                objects = r'унитаз|раковин|ванн|труб|канализ'
                current_objects = set(re.findall(objects, quote + ' ' + (_text(previous) if previous else ''), re.I))
                for old in list(result['requested_reports']):
                    old_objects = set(re.findall(objects, old['quote'], re.I))
                    if not current_objects or not old_objects or current_objects & old_objects:
                        result['excluded_reports'].append(dict(old, reason='retracted_by_client_uncertainty',
                            correction_message_id=message.get('id', '')))
                        result['requested_reports'].remove(old)
            if has_clog:
                if unknown or conditional or negative or reported:
                    result['excluded_reports'].append(dict(row, reason=('uncertain' if unknown else
                        'conditional' if conditional else 'negative' if negative else 'reported')))
                else:
                    result['requested_reports'].append(row)
        previous = None
    return result


def scoped_clog_text(text, context):
    """Mask only excluded literal clauses in the selection view, not history."""
    positive = {row['quote'].casefold() for row in context.get('requested_reports', [])}
    for row in context.get('excluded_reports', []):
        if row['quote'].casefold() in positive:
            continue
        replacement = re.sub(r'засор\w*|прочист\w*', '[неподтверждённая работа]', row['quote'], flags=re.I)
        text = re.sub(re.escape(row['quote']), lambda _: replacement, text, flags=re.I)
    return text


def confirmed_clog(messages, context=None):
    """Only a client's unambiguous answer confirms a staff clog question.

    Keep both source messages for audit. The confirmation names the client's
    requested service; it is not a technician's diagnosis or proof of repair.
    """
    context = clog_work_context(messages) if context is None else context
    uncertain_positions = {row['position'] for row in context['uncertain_reports']}
    found, previous_out = {}, None
    for position, message in enumerate(messages):
        body = _text(message)
        if message.get('direction') == 'out':
            previous_out = message if observed_clog_question(message) else None
            continue
        if not _client_intent_message(message) or message.get('role') in ('assistant', 'system'):
            continue
        if (position in uncertain_positions
                or re.search(r'^\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b|'
                             r'\bзасор\w*\s+нет\b|\bне\s+засор\b|\bнет\s+засор', body, re.I)):
            found = {}
        elif previous_out and re.fullmatch(r'\s*(?:да|верно|правильно)[.!\s]*', body, re.I):
            question = _text(previous_out)
            if (re.search(r'\bзасор\w*\b', question, re.I)
                    and question.count('?') == 1
                    and not re.search(r'\b(?:или|не|и)\b', question, re.I)):
                found = dict(message_id=message.get('id', ''), quote=body,
                             question_message_id=previous_out.get('id', ''), question_quote=question,
                             source='staff_question_client_answer')
        previous_out = None
    return found


def confirmed_furniture_completion(messages):
    """A client's yes can confirm finishing assembly, never the staff alone."""
    found, question, scope_start = {}, None, 0
    furniture = r'шкаф|комод|кроват|мебел|тумб|стол'
    for index, message in enumerate(messages):
        if message.get('direction') == 'out':
            question = message if (message.get('sender_type', 'operator') in ('operator', 'employee', 'human', '')
                                   and not message.get('out_pending')) else None
            continue
        if not _incoming(message) or message.get('sender_type', 'client') not in ('client', ''):
            continue
        body = _text(message)
        if re.search(r'^\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', body, re.I):
            found, question, scope_start = {}, None, index
            continue
        if re.search(r'\bне\s+(?:надо|нужно)\s+дособ|\bдособ\w*\s+не\s+(?:надо|нужно)', body, re.I):
            found = {}
        elif question and re.fullmatch(r'\s*(?:да|верно|правильно|да[,!\s]+нужно)[.!\s]*', body, re.I):
            asked = _text(question)
            if re.fullmatch(r'\s*(?:нужно\s+|надо\s+)?дособрать(?:\s+(?:шкаф|комод|кровать|мебель|тумбу|стол))?(?:\s+(?:нужно|надо))?\s*\?\s*', asked, re.I):
                prior = messages[scope_start:index]
                literal = '\n'.join(_text(m) for m in prior if _incoming(m) and m.get('sender_type', 'client') in ('client', '')
                                    and not re.search(r'[«»“”"]|сказал|написал|если|\?', _text(m), re.I))
                viewed = [m for m in prior if _incoming(m) and m.get('sender_type', 'client') in ('client', '')
                          and m.get('media_reviewed') and not m.get('unread_media')
                          and m.get('media_observation', {}).get('device_kind') in ('wardrobe', 'bed', 'dresser')]
                if re.search(furniture, literal + '\n' + asked, re.I) or viewed:
                    found = dict(message_id=message.get('id', ''), quote=body,
                                 question_message_id=question.get('id', ''), question_quote=asked,
                                 object_message_id=viewed[-1]['id'] if viewed else '',
                                 requested_action='finish_assembly', source='staff_question_client_answer')
        question = None
    return found


def graphics_device_scope(messages):
    """Bind a black-picture complaint to a host only from client evidence."""
    incoming=[m for m in messages if _incoming(m)]
    text='\n'.join(_text(m) for m in incoming)
    if not (re.search(r'видеокарт',text,re.I) and re.search(r'нет\s+(?:картинки|изображения)|(?:экран\w*[^.!?\n]{0,20}ч[её]рн|ч[её]рн\w*\s+экран)',text,re.I)):
        return {}
    # A requested physical card operation remains a card service, even when
    # the card is in a PC. Neither a supplied component nor a symptom proves it.
    for m in incoming:
        body=_text(m)
        scope=re.sub(r'не\s+(?:нужен|нужно|надо)\s+ремонт\s+видеокарт\w*|ремонт\s+видеокарт\w*\s+не\s+нужен','',body,flags=re.I)
        operation=r'(?:отремонт|ремонт|почин|пайк|перепа|прогрев|прошив|чистк|почист|обслужив)\w*'
        if re.search(operation+r'\s+(?:(?:сам\w*|стар\w*|нов\w*|сгоревш\w*)\s+){0,3}видеокарт|'
                     r'видеокарт\w*\s+(?:(?:нужно|нужен|нужна|требуется|на|для|в)\s+)?'+operation+r'|'
                     r'видеокарт\w*[^.!?\n,;]{0,25}(?:термопаст|термопроклад)',scope,re.I):
            return dict(kind='component_request',message_id=m.get('id',''),quote=body[:500],source='client_message',component_fault_confirmed=False)
    if re.search(r'драйвер',text,re.I):
        return {}  # Keep the existing scoped software-only path.
    pc=r'(?:компьютер\w*|пк|системн\w*\s+блок\w*)'
    prompt=re.compile(r'видеокарт\w*[^.!?\n]{0,35}(?:вставлен|установлен)\w*[^.!?\n]{0,20}\b'+pc+r'\b',re.I)
    yes=re.compile(r'^\s*(?:да|ага|конечно)(?:[,!\s]+конечно)?[.!\s]*$',re.I)
    no=re.compile(r'^\s*(?:нет|неа|нету)[.!\s]*$',re.I)
    asked=sum(m.get('direction')=='out' and not m.get('out_pending') and '?' in _text(m) and _text(m).count('?')==1 and bool(prompt.search(_text(m))) for m in messages)
    evidence={};kind='device_uncertain';unavailable=False;negative_confirmation=False
    def asserted(candidate,body):
        start=max(body.rfind(mark,0,candidate.start()) for mark in '.!?\n')+1
        end=min([pos for mark in '.!?\n' if (pos:=body.find(mark,candidate.end()))>=0] or [len(body)])
        prefix=body[start:candidate.end()]
        if re.search(r'\b(?:если|допустим|предположим|вдруг|вроде|кажется|наверно\w*)\b|не\s+уверен',prefix,re.I):return False
        return end==len(body) or body[end]!='?' or bool(re.search(r'сколько|стоим|цен[аыуе]',body[start:end],re.I))
    for i,m in enumerate(messages):
        if not _incoming(m):continue
        body=_text(m)
        negative=next((c for c in re.finditer(r'\b(?:нет\s+(?:у\s+меня\s+)?'+pc+r'|без\s+'+pc+r'|видеокарт\w*\s+не\s+(?:вставлен|установлен))',body,re.I) if asserted(c,body)),None)
        direct=next((c for c in re.finditer(r'видеокарт\w*[^.!?\n]{0,35}(?:вставлен|установлен)\w*[^.!?\n]{0,20}\b'+pc+r'\b|'
                         r'\b'+pc+r'\b[^.!?\n]{0,40}нет\s+(?:картинки|изображения)|'
                         r'(?:ремонт|диагност|почин)\w*\s+'+pc+r'\b',body,re.I) if asserted(c,body)),None)
        previous=messages[i-1] if i else {}
        bound=(previous.get('direction')=='out' and not previous.get('out_pending') and _text(previous).count('?')==1
               and 'или' not in _text(previous).lower() and bool(prompt.search(_text(previous))))
        if direct or negative or bound and (yes.fullmatch(body) or no.fullmatch(body) or re.search(r'не\s*знаю|не\s+помню|не\s+разбираюсь',body,re.I)):
            unavailable=bool(bound and re.search(r'не\s*знаю|не\s+помню|не\s+разбираюсь',body,re.I))
            negative_confirmation=bool(bound and no.fullmatch(body))
            kind='standalone_diagnostic' if negative else 'device_uncertain' if unavailable or negative_confirmation else 'host_diagnostic'
            evidence=dict(message_id=m.get('id',''),quote=body[:500],source='client_message',question_message_id=previous.get('id','') if bound else '')
    return dict(kind=kind,asked=asked,unavailable=unavailable,host_confirmation_negative=negative_confirmation,component_fault_confirmed=False,**evidence)


def visual_work_context(text, observations):
    """A reviewed object can resolve an unnamed job, never add another job.

    Keep all original observations separately for audit. In particular, a TV
    behind a cabinet or an oven next to a pipe is not a repair request.
    """
    import assistant_catalog
    named = assistant_catalog._furniture_object_labels(text)
    patterns = {
        'computer': r'компьютер|ноутбук|моноблок|монитор|монмтор|\bпк\b|видеокарт|материнск\w*\s+плат|материнк',
        'tv': r'телевиз|\bтв\b',
        'oven': r'духов|варочн|индукцион|электроплит|газов\w*\s+плит|\bплит[аыуе]\b',
        'bed': r'кроват|кроваь|манеж',
        'wardrobe': r'шкаф',
        'dresser': r'комод|тумб|мебельн\w*\s+ящик',
        'furniture': r'мебел',
        'pipe': r'труб|стояк|радиатор|отоплен|батаре',
        'plumbing': r'унитаз|бачок|смесител|раковин|мойк|ванн|душев',
        'electric': r'розетк|выключател|электропровод|проводк|светиль|люстр|светодиодн',
        'network': r'роутер|router|коннектор|сетев\w*\s+кабел|вит\w*\s+пар|оптоволок',
        'printer': r'принтер|мфу|сканер',
        'washer': r'стирал|посудомоеч',
        'other_furniture': r'диван|стул|стол(?:ик|ешниц)?\b|полк|полоч',
    }
    families = {key for key, pattern in patterns.items() if re.search(pattern, named, re.I)}
    if re.search(r'кухн|кухонн\w*\s+гарнитур', named, re.I) and re.search(
            r'собрать|сборк|разобрать|разборк|снять|повесить|установ|подогн', named, re.I):
        families.add('kitchen')
    device_families = dict(pc='computer', pc_component='computer', monitor='computer', tv='tv',
                           oven='oven', bed='bed', wardrobe='wardrobe', dresser='dresser',
                           ethernet_cable='network')
    selected, excluded = [], []
    for observation in observations:
        family = device_families.get(observation.get('device_kind'))
        matches = (not family or not families or family in families
                   or family in {'bed','wardrobe','dresser'} and 'furniture' in families)
        if matches:
            selected.append(observation)
        else:
            excluded.append(dict(observation, rule_id='OWNER-CLIENT-REPORTED-SCOPE-20261019',
                                 scope_reason='Видимый предмет не добавляет работу к названному клиентом объёму'))
    return selected, excluded


def intent_text(text, facts):
    if facts.get('current_enquiry_scope'):
        text = facts['current_enquiry_scope']['text']
    if facts.get('active_service_scope'):
        text = facts['active_service_scope']['text']
    if facts.get('clog_work_context'):
        text = scoped_clog_text(text, facts['clog_work_context'])
    for placement in facts.get('work_placement_answers', []):
        # Never erase the same words inside a separate service request. This
        # view masks only complete literal placement lines; history is intact.
        text = re.sub(r'^' + re.escape(placement['quote']) + r'$',
                      '[место обсуждаемой работы]',text,flags=re.M)
    for reference in facts.get('work_location_references', []):
        # The exact clause, not the whole message: an independent lock job in
        # the following sentence remains an actual requested operation.
        text = re.sub(r'(^|(?<=[.!?;]))\s*' + re.escape(reference['quote']) + r'(?=[.!?;\n]|$)',
                      r'\1[ориентир места работы]',text,count=1,flags=re.M)
    for background in facts.get('client_background_work', []):
        if background['exclude_from_service_selection']:
            text = text.replace(background['quote'], '[самостоятельная работа клиента]', 1)
    if facts.get('router_configuration_only'):
        text = re.sub(r'\b(?:прошив\w*|прошить|перепрош\w*)\b', '[WITHDRAWN_OPERATION]', text, flags=re.I)
    if facts.get('furniture_manufacture'):
        text += '\nКлиент подтвердил изготовление мебели.'
    if facts.get('confirmed_clog'):
        text += '\nКлиент подтвердил запрос: устранение засора.'
    if facts.get('confirmed_furniture_completion'):
        text += '\nКлиент подтвердил запрос: собрать мебель до конца.'
    if facts.get('graphics_scope',{}).get('kind')=='host_diagnostic':
        text=re.sub(r'видеокарт\w*','[COMPONENT]',text,flags=re.I)
        text+='\nКлиент подтвердил диагностику компьютера с отсутствием изображения.'
    # A named department at a station is an address landmark, not a second
    # appliance repair request. Change only the observed name inside a proven
    # location quote; keep service requests in the rest of the message.
    for row in facts.get("address_notes", []):
        quote = row["quote"]
        text = text.replace(quote, _SHOP_NAME.sub("отдел [название]", quote))
    observations = [] if facts.get('visual_context_conflict') else visual_work_context(
        text, facts.get('image_observations', []))[0]
    devices = {o.get('device_kind') for o in observations}
    # A PC with its display is one signal-path complaint. The photographed
    # peripheral does not establish a second independent repair order.
    if 'pc' in devices:
        text += '\nОсновная техника на просмотренном фото: компьютер.'
    elif 'monitor' in devices:
        text += '\nОсновная техника на просмотренном фото: монитор.'
    if 'tv' in devices:
        text += '\nОсновная техника на просмотренном фото: телевизор.'
    if 'oven' in devices:
        text += '\nНа просмотренном фото духовка / духовой шкаф (тип газа по фото не установлен).'
    if (devices & {'wardrobe', 'bed', 'dresser'} and re.search(r'собрать|сборк|разобрать', text, re.I)
            and not re.search(r'телевиз|компьютер|ноутбук|кронштейн|принтер|роутер|розетк|светиль|люстр', text, re.I)):
        # Only a reviewed primary object can resolve an unnamed assembly.
        names = {'wardrobe': 'шкаф', 'bed': 'кровать', 'dresser': 'комод'}
        text += '\nОсновной предмет на просмотренном фото: ' + ', '.join(names[d] for d in sorted(devices & names.keys())) + '.'
    import personal_media
    for o in observations:
        if o.get('visible_symptom') in ('screen_bands','tv_screen_bands') and o.get('device_kind') in ('tv','monitor'):
            text += '\nНа экране ' + ('телевизора' if o['device_kind']=='tv' else 'монитора') + ' видны полосы.'
        if o.get('visible_symptom') == 'screen_cracks' and o.get('device_kind') == 'tv':
            text += '\nНа просмотренном фото телевизора видны трещины на экране; причина не установлена.'
        if (o.get('visible_symptom') in personal_media.FURNITURE_SIGNS
                and not assistant_assembly_only(text)):
            text += '\nНа просмотренном фото: ' + personal_media.FURNITURE_SIGNS[o['visible_symptom']][1] + '.'
    return text


def assistant_assembly_only(text):
    import assistant_catalog
    return (assistant_catalog.furniture_assembly_request(text)
            and not assistant_catalog.furniture_repair_request(text))


def service_contact_instruction(facts, messages=()):
    """Only an explicit, resolved client choice supplies the service first line."""
    phone = facts.get('contact_phone_to_use')
    if (not phone or contact_phone.normalize(phone) != phone
            or facts.get('phone_needs_confirmation') is not False
            or phone not in facts.get('phone_values', [])):
        return None
    choice = facts.get('phone_selection') or {}
    if choice.get('kind') in ('explicit_backup', 'explicit_alternative'):
        return None
    if not choice:
        evidence = facts.get('evidence', {}).get('contact_phone_to_use', {})
        if not any(row.get('value') == phone and row.get('role') == 'contact'
                   and row.get('message_id') == evidence.get('message_id') for row in facts.get('phones', [])):
            return None
        source = next((m for m in messages if m.get('id') == evidence.get('message_id') and _incoming(m)), None)
        if not source or re.search(r'[«»"?]|\bесли\b|\bне\s+звон', _text(source), re.I):
            return None
        choice = dict(evidence, quote=_text(source)[:500])
    if not choice.get('message_id') or not choice.get('quote'):
        return None
    return dict(line='Звонить на ' + phone, phone=phone, message_id=choice['message_id'],
                quote=choice['quote'], source='client_message',
                rule_id='OWNER-CONTACT-FIRST-LINE-20261023')


def crm_comment_lines(facts):
    lines = [("Дополнение к адресу со слов клиента: «" if row.get('kind') in ('literal_address_addition', 'literal_address_addition_withdrawal')
              else "Ориентир со слов клиента: «") + row["quote"] + "»." for row in facts.get("address_notes", [])]
    optional = facts.get('mixed_optional_work') or {}
    if optional.get('rule_id') == 'OWNER-MIXED-OPTIONAL-LOOK-20261023' and optional.get('comment'):
        lines.append(optional['comment'])
    destination = facts.get('work_destination_hint') or {}
    if destination.get('status') == 'unverified_work_destination':
        lines.append('Ориентир места работ со слов клиента: «' + destination['quote'] + '». Территория не проверена.')
    passenger = facts.get('passenger_pickup_request') or {}
    if passenger.get('quote'):
        lines.append('Просьба забрать клиента: «' + passenger['quote'] + '». Перевозка не подтверждена.')
    for reference in facts.get('address_references', []):
        if reference['role'] == 'previous' and facts.get('address', {}).get('building'):
            continue  # A corrected worksite must not carry old addresses into CRM.
        label = {'meeting':'Место встречи/забора клиента', 'previous':'Прежний адрес'}.get(reference['role'], 'Адрес-ориентир')
        lines.append(label + ' со слов клиента: «' + reference['quote'] + '». Это не подтверждённый адрес работ.')
    systems={'xbox_live':'Xbox Live','windows':'Windows','printer':'принтера'}
    for observation in facts.get('image_observations',[]):
        if observation.get('content_kind')=='device_message' and observation.get('error_code'):
            lines.append('На просмотренном изображении сообщение '+systems[observation['error_system']]+', код '+observation['error_code']+'. Причина ошибки не установлена.')
    lines += ['Деталь задачи со слов клиента: «' + row['quote'] + '».' for row in facts.get('task_notes', [])]
    preservation = facts.get('data_preservation_context') or {}
    if preservation.get('quote') and preservation.get('source') == 'client_message':
        line = 'Сведения о сохранении данных со слов клиента: «' + preservation['quote'] + '»'
        if preservation.get('question_quote'):
            line += ' — ответ на «' + preservation['question_quote'] + '»'
        lines.append(line + '.')
    availability = facts.get('material_availability') or {}
    if availability.get('quote') and availability.get('source') == 'client_message':
        line = 'Наличие материалов/комплектующих со слов клиента: «' + availability['quote'] + '»'
        if availability.get('question_quote'):
            line += ' — ответ на «' + availability['question_quote'] + '»'
        lines.append(line + '.')
    requested_visit = facts.get('requested_visit') or {}
    lock_work = facts.get('lock_work_choice') or {}
    if lock_work.get('value') == 'repair' and lock_work.get('quote'):
        lines.append('Работа с замком/ручкой со слов клиента: «' + lock_work['quote'] + '».')
    if requested_visit.get('source') == 'client_message' and requested_visit.get('quote'):
        if requested_visit.get('client_confirmed'):
            lines.append('Клиент подтвердил время: «' + requested_visit['quote'] + '».')
        elif requested_visit.get('range_quote'):
            lines.append('Пожелание о визите со слов клиента: «' + requested_visit['range_quote']
                         + '». На вопрос «' + requested_visit['question_quote'] + '» ответил: «'
                         + requested_visit['quote'] + '». Визит этим не подтверждён.')
        else:
            lines.append('Пожелание о визите со слов клиента: «' + requested_visit['quote'] + '».')
    age = facts.get('client_age') or {}
    adult = facts.get('adult_presence') or {}
    if age.get('status') == 'minor':
        lines.append('Клиент несовершеннолетний; документы должен заполнить взрослый.')
        if adult.get('quote'):
            label = ('Присутствие взрослого при визите подтверждено со слов клиента' if adult.get('status') == 'confirmed'
                     else 'Присутствие взрослого при визите не подтверждено; последнее сообщение клиента')
            line = label + ': «' + adult['quote'] + '»'
            if adult.get('question_quote'):
                line += ' — ответ на «' + adult['question_quote'] + '»'
            lines.append(line + '.')
    lines += ['Ограничение визита со слов клиента: «' + row['quote'] + '».' for row in facts.get('visit_constraints', [])]
    if facts.get('active_service_scope'):
        lines.append('Актуальный объём со слов клиента: «' + facts['active_service_scope']['quote'] + '».')
    for background in facts.get('client_background_work', []):
        lines.append('Самостоятельная работа клиента (обстоятельство, не заказ этой работы): «' + background['quote'] + '».')
    import personal_media
    for observation in facts.get('service_image_observations', facts.get('image_observations', [])):
        if observation.get('model'):
            lines.append('Модель с просмотренного изображения: ' + observation['model'] + '.')
        names = {'pc':'компьютер','monitor':'монитор','tv':'телевизор','ethernet_cable':'сетевой кабель',
                 'oven':'духовка / плита с духовкой','bed':'кровать','wardrobe':'шкаф','dresser':'мебельный ящик'}
        if observation.get('device_kind') in names:
            line = 'На просмотренном изображении: ' + names[observation['device_kind']]
            if observation.get('visible_symptom') in ('screen_bands','tv_screen_bands'):
                line += ', видны полосы на экране (причина не установлена)'
            if observation.get('visible_symptom') == 'screen_cracks' and observation.get('device_kind') == 'tv':
                line += ', видны трещины на экране (причина не установлена)'
            if observation.get('connector_type') == 'RJ45':
                line += ', коннектор RJ45'
            if observation.get('visible_symptom') in personal_media.FURNITURE_SIGNS:
                line += ', ' + personal_media.FURNITURE_SIGNS[observation['visible_symptom']][1].lower() + ' (причина не установлена)'
            lines.append(line + '.')
        if observation.get('device_kind') == 'pc_component':
            lines.append('На просмотренном изображении отдельная комплектующая ПК; наличие целого компьютера по фото не подтверждено.')
    if facts.get('budget_limit'):
        lines.append('Ограничение бюджета со слов клиента: не больше ' + str(facts['budget_limit']['amount']) + ' рублей. Окончательная стоимость не подтверждена.')
    if isinstance(facts.get('client_age', {}).get('value'), int):
        lines.append('Возраст клиента со слов: ' + str(facts['client_age']['value']) + '.')
    code = facts.get("address", {}).get("intercom", "")
    # CRM has a yes/no intercom field. The actual code needs its own carrier.
    if isinstance(code, str) and re.search(r"\d", code):
        lines.append(("Код входа: " if facts.get('intercom_present') is False else "Домофон: ") + code + ".")
    unit_quote = facts.get('evidence', {}).get('address.office', {}).get('quote', '')
    room = _ROOM.search(unit_quote)
    if room:
        lines.append("Помещение со слов клиента: комната " + room[1] + ".")
    for backup in facts.get('fallback_phones', []):
        lines.append("Резервный телефон " + backup['value'] + ". Условие со слов клиента: «" + backup['quote'] + "».")
    if facts.get("call_before_visit"):
        lines.append("Позвонить при подъезде по просьбе клиента." if facts.get('call_timing')=='upon_arrival' else "Позвонить перед выездом по просьбе клиента.")
        quote = facts.get("evidence", {}).get("call_before_visit", {}).get("quote")
        if quote:
            lines.append("Условия звонка со слов клиента: «" + quote + "».")
    if facts.get('required_crew_count'):
        lines.append('Клиент просит ' + str(facts['required_crew_count']) + ' исполнителей. Состав бригады не подтверждён.')
    if facts.get('intercom_present') is False:
        lines.append('Домофон отсутствует.')
    elif facts.get('intercom_present') is True:
        lines.append('Домофон работает.' if facts.get('intercom_working') is True else
                     'Домофон не работает.' if facts.get('intercom_working') is False else 'Домофон есть.')
    elif isinstance(facts.get('intercom_working'), bool):
        lines.append('Домофон работает.' if facts['intercom_working'] else 'Домофон не работает или отсутствует.')
    if facts.get('staff_introduction', {}).get('name'):
        lines.append('Представились клиенту: «' + facts['staff_introduction']['name'] + '».')
    return list(dict.fromkeys(lines))


def staff_introduction(messages):
    """Only delivered staff words can establish the name used with this client."""
    result = {}
    previous = None
    for message in messages:
        if message.get('direction') not in ('in', 'out'):
            continue
        text = _text(message).strip()
        if message.get('direction') == 'out':
            if message.get('out_pending') or str(message.get('delivery_status') or message.get('delivery') or '').lower() in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled'):
                continue
            explicit = re.search(r'\b(?:[Мм]еня зовут|[Яя] мастер)\s+([А-ЯЁ][а-яё-]{1,39})\b', text)
            question = (re.fullmatch(r'\s*[Вв]ас\s+зовут\s+([А-ЯЁ][а-яё-]{1,39})\s*\?\s*', _text(previous))
                        if previous and previous.get('direction') == 'in' else None)
            if explicit:
                result = dict(name=explicit[1], confirmation_message_id=message.get('id', ''), quote=text[:500], kind='explicit_staff_introduction')
            elif (question and re.match(r'^\s*(?:да|верно|правильно)\b', text, re.IGNORECASE)
                  and not re.search(r'\bне\s+' + re.escape(question[1]) + r'\b', text, re.IGNORECASE)):
                result = dict(name=question[1], question_message_id=previous.get('id', ''),
                              confirmation_message_id=message.get('id', ''),
                              quote=(_text(previous) + '\nСотрудник: ' + text)[:500], kind='client_name_question_staff_confirmation')
        previous = message
    return result


def residence_place(messages):
    """A residence statement supplies a place, without choosing a map location."""
    for message in reversed(messages):
        if not _incoming(message):
            continue
        body = _text(message)
        typed_place = re.search(r'\b(?:[Мм]кр\.?|[Мм]икрорайон)\s*([А-ЯЁ][а-яё-]{3,})\b',body)
        island = re.search(r'\bна\s+([А-ЯЁ][а-яё-]+\s+острове)\b',body)
        if typed_place or island:
            match = typed_place or island
            return dict(value=match[1],message_id=message.get('id',''),quote=match[0],source='explicit_client_place',map_verified=False)
        match = re.search(r'\b(?:[Мм]ы|[Яя])\s+в\s+([А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){0,2})\s+жив[её](?:м|т)|\b(?:[Мм]ы\s+жив[её]м|[Яя]\s+живу)\s+в\s+([А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){0,2})', _text(message))
        if match:
            return dict(value=match[1] or match[2], message_id=message.get('id', ''), quote=match[0])
    return {}


def observed_location_answer(messages):
    """Bind short location replies to a real delivered question, literally.

    Consecutive short replies may correct a name. No dictionary completion,
    settlement type, territory or map result is inferred from these strings.
    """
    window = []
    for row in reversed(messages):
        if (not isinstance(row, dict) or row.get('direction') in ('system', 'note')
                or row.get('sender_type') in ('system', 'avito')):
            continue
        if _incoming(row):
            body = _text(row).strip(' .,!\n')
            value = re.sub(r'^(?:в|во|на)\s+', '', body, flags=re.I)
            if (not re.fullmatch(r'[А-Яа-яЁё-]+(?:\s+[А-Яа-яЁё-]+){0,3}', value)
                    or re.search(r'\b(?:да|нет|завтра|сегодня|дома|домой|квартире|даче|потом|позже|сейчас|'
                                 r'напишу|знаю|помню|мне|меня|можно|привезу|приеду|спасибо|ок|окей|'
                                 r'хорошо|ладно|понял|поняла|договорились|пожалуйста|область|край|'
                                 r'республика|округ)\b', value, re.I)):
                return {}
            window.append((row, value))
            continue
        if not window or row.get('out_pending') or str(row.get('delivery_status') or row.get('delivery') or '').lower() in (
                'failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled'):
            return {}
        question = _text(row)
        if (row.get('direction') != 'out' and row.get('role') != 'assistant'
                or question.count('?') > 1
                or re.search(r'модел|марк[аиу]|тип\b|материал|комплектующ', question, re.I)
                or not re.search(r'\b(?:в\s+каком|какой)\s+(?:город|насел[её]нн)|'
                                 r'\bкуда\b[^.!?\n]{0,40}(?:приехать|выезд|подъехать)|'
                                 r'\bгде\b[^.!?\n]{0,25}(?:находитесь|жив[её]те)|^\s*город\s*\??\s*$', question, re.I)):
            return {}
        latest, value = window[0]
        chronological = list(reversed(window))
        return dict(value=value, message_id=latest.get('id', ''), quote=_text(latest),
                    question_message_id=row.get('id', ''), question_quote=question,
                    answer_window_message_ids=[m.get('id', '') for m, _ in chronological],
                    prior_values=[v for _, v in chronological[:-1]],
                    source='observed_location_answer', map_verified=False, confirmed=False)
    return {}


def untyped_place_candidate(messages, known, address):
    """Keep a locality-looking address tail for lookup, never choose its city.

    These are low-confidence hints from explicit address structure or a
    dimension-plus-place message. They are not map results or confirmed CRM
    settlement fields; a product name alone is insufficient.
    """
    answer = observed_location_answer(messages)
    if answer:
        return answer
    city = str(known.get('city') or '')
    place = r'(?P<place>[а-яё-]*(?:ово|ево|ино|ичи|аши))'
    for message in reversed(messages):
        if not _incoming(message):
            continue
        body = _text(message)
        # Preserve an informal coastal address as a lookup hint. In particular,
        # a shortened locality must not be silently expanded or map-approved.
        if (city and re.fullmatch(r'\s*[А-Яа-яЁё-]+\s+\d+[а-яё]?\s+(?:[А-Яа-яЁё-]+\s+){0,2}бухта[.!\s]*', body, re.I)):
            return dict(value=body.strip('.! \n'), message_id=message.get('id', ''), quote=body[:700],
                        source='untyped_client_location_hint', map_verified=False, confirmed=False)
        match = None
        if city:
            match = re.search(r'\bадрес\s*[:—-]?\s*'+re.escape(city)+r'\s*,\s*'+place+r'\s*[.!?]*$',body,re.I)
        if not match and address.get('street') and address.get('building'):
            match = re.search(re.escape(address['street'])+r'\s*,?\s*(?:д(?:ом)?\.?\s*)?'+re.escape(address['building'])+
                              r'\s*[,;]?\s*(?:[а-яё]\s+)?'+place+r'\s*[.!?]*$',body,re.I)
        if (not match and known.get('direction')=='mnc' and re.search(r'размер|длина|ширина|высота',body,re.I)):
            match = re.search(r'\d+(?:[,.]\d+)?\s*(?:см|метр\w*)?\s+'+place+r'\s*[.!?]*$',body,re.I)
        if match and len(match['place'])>=4 and match['place'].casefold() not in ('готово','таково','каково','ничего'):
            return dict(value=match['place'],message_id=message.get('id',''),quote=body[:700],
                        source='untyped_client_location_hint',map_verified=False,confirmed=False)
    return {}


def _same_street(left, right):
    def key(value):
        value = re.sub(r"^\s*(?:ул\.\s*|(?:ул|улиц[аыуе])\s+)", "", value.casefold().replace("ё", "е")).strip()
        value = re.sub(r'^(\d{1,3})(?=[а-яё])', r'\1 ', value)
        # A narrow grammatical equivalence, not fuzzy correction of a street.
        return re.sub(r"(?:скую|ской|ская)\b", "ск", value)
    return bool(left and right and key(left) == key(right))


def _literal_address_addition(message, parsed, text):
    """Keep a bounded untyped suffix as a quote, never a verified locality."""
    if (not parsed or not parsed.street or not parsed.house
            or not message.get('id')
            or message.get('direction') != 'in'
            or message.get('sender_type', 'client') not in ('client','customer','user','contact','lead','')
            or message.get('out_pending')
            or str(message.get('delivery_status') or '').lower() in ('pending','failed','queued','sending','error')
            or re.search(r'[«»“”"]|\b(?:если|возможно|наверное|кажется|сосед\w*|сказал\w*|раньше)\b', text, re.I)):
        return None
    tail = re.fullmatch(r'\s*[.;]\s*(?P<quote>[а-яё][а-яё-]{3,39}(?:\s+[а-яё][а-яё-]{2,29}){0,2})[.!]?\s*',
                        text[parsed.end:], re.I)
    if not tail or re.search(r'\b(?:не|спасибо|пожалуйста|срочно|сегодня|завтра|вчера|утром|вечером|время|'
                             r'нуж\w*|надо|хочу|мож\w*|цен\w*|руб\w*|час\w*|минут\w*|телефон\w*|'
                             r'установ\w*|замен\w*|ремонт\w*|собра\w*|сдел\w*|добав\w*|повес\w*|подключ\w*)\b',
                             tail['quote'], re.I):
        return None
    return dict(message_id=message.get('id',''), quote=tail['quote'],
                kind='literal_address_addition', verified=False)


def _literal_address_addition_withdrawal(message, parsed, text, notes):
    """Withdraw only an exact previous literal suffix, preserving the denial."""
    if (not message.get('id') or message.get('direction') != 'in'
            or message.get('sender_type', 'client') not in ('client','customer','user','contact','lead','')
            or message.get('out_pending')
            or str(message.get('delivery_status') or '').lower() in ('pending','failed','queued','sending','error')
            or re.search(r'[«»“”"]|\b(?:если|возможно|наверное|кажется|сосед\w*|сказал\w*|раньше)\b', text, re.I)):
        return None
    tail = text[parsed.end:] if parsed else text
    denial = re.fullmatch(r'\s*[.;]?\s*(?P<quote>не\s+(?P<name>[а-яё][а-яё-]{3,39}(?:\s+[а-яё][а-яё-]{2,29}){0,2}))[.!]?\s*', tail, re.I)
    if not denial:
        return None
    key = lambda value: ' '.join(value.casefold().replace('ё', 'е').split())
    withdrawn = [row for row in notes if row.get('kind') == 'literal_address_addition'
                 and key(row['quote']) == key(denial['name'])]
    if not withdrawn:
        return None
    return dict(message_id=message['id'], quote=denial['quote'],
                kind='literal_address_addition_withdrawal', verified=False,
                withdrawn_quote=withdrawn[0]['quote'],
                withdrawn_source_message_ids=[row['message_id'] for row in withdrawn])


def _observed_current_address_confirmation(messages, index, address, conflicts, evidence):
    message = messages[index]
    if (not conflicts or any(c['kind'] != 'address_changed' for c in conflicts)
            or message.get('direction') != 'in'
            or message.get('sender_type','client') not in ('client','customer','user','contact','lead','')
            or message.get('out_pending')
            or str(message.get('delivery_status') or '').lower() in ('pending','failed','queued','sending','error')
            or not re.fullmatch(r'(?:да|верно|правильно|ага)[.!\s]*', _text(message), re.I)):
        return None
    previous = next((m for m in reversed(messages[:index]) if m.get('direction') in ('in','out')
                     and m.get('sender_type') not in ('system','avito')), {})
    if (previous.get('direction') != 'out' or previous.get('out_pending')
            or previous.get('sender_type') not in ('operator','employee','human','staff')
            or previous.get('delivery_status') not in ('delivered','read','sent')
            or not previous.get('id') or not message.get('id')):
        return None
    question = re.fullmatch(r'(?:Здравствуйте[!,.]\s*)?Адрес для выезда:\s*(?P<address>[^?\n]{1,160}),\s*верно\?\s*',
                            _text(previous).strip(), re.I)
    if not question:
        return None
    target = question['address'].strip()
    parsed = contact_address.parse(target)
    if (not parsed or parsed.start != 0 or parsed.end != len(target) or parsed.parts
            or not contact_address.same_address(parsed.street, parsed.house,
                                                address.get('street'), address.get('building'))):
        return None
    sources = list(dict.fromkeys(evidence.get('address.' + key, {}).get('message_id')
                                 for key in ('street','building')))
    if not sources or any(not mid or mid == 'client-card' for mid in sources):
        return None
    return dict(message_id=message['id'], quote=_text(message), question_message_id=previous['id'],
                question_quote=_text(previous), source_address_message_ids=sources,
                confirmed_fields=['street','building'], kind='literal_current_address_confirmation')


def _text(message):
    return str(message.get("body") or message.get("text") or message.get("content") or "")


def _incoming(message):
    return message.get("direction") == "in" or message.get("role") in ("user", "client")


def explicit_help_withdrawal(text):
    """A present, unconditional withdrawal of help; no CRM action implied."""
    if re.search(r'\bесли\b|\bвдруг\b|\bвозможно\b|\bнаверно\w*|не\s+думаю|не\s+уверен', text, re.I):
        return False
    clauses = re.findall(r'[^.!?\n]+[.!?\n]?', text)
    courtesy = r'(?:(?:большое\s+)?(?:спасибо|благодарю)(?:\s+за\s+(?:беспокойство|помощь|внимание))?|извините|пожалуйста)'
    prefix = r'(?:' + courtesy + r'|добрый\s+(?:день|вечер)|доброе\s+утро|здравствуйте|но|мне|нам|теперь|уже|больше|да|нет)'
    subject = r'(?:(?:ваша\s+)?(?:помощь|услуга)|(?:ваши\s+)?услуги)'
    modifiers = r'(?:(?:мне|нам|теперь|уже|больше)\s+)*'
    for clause in reversed(clauses):
        clean = re.sub(r'[^\w\s,!?—-]', ' ', clause).strip()
        clean = re.sub(r'\s+', ' ', clean)
        if re.fullmatch(r'(?:' + courtesy + r'[,!\s]*)+', clean, re.I):
            continue
        if ('?' not in clause and not re.search(r'[«»“”"]', clause)
                and not re.search(r'\b(?:но|завтра|после|сегодня|теперь)\b|'
                                  r'вс[её]\s+же|нужна?\s+помощь|помогите|(?<!не )\bприезжайте', clean, re.I)
                and re.match(r'^(?:пожалуйста[,\s]+)?(?:не\s+(?:надо|нужно)\s+'
                             r'(?:(?:ко\s+мне|к\s+нам|сюда)\s+)?(?:приезжать|подъезжать|приходить)|'
                             r'не\s+(?:приезжайте|подъезжайте|приходите))'
                             r'(?:\s*[,!—-]|\s*$)', clean, re.I)):
            return True
        return bool('?' not in clause and not re.search(r'[«»“”"]', clause)
                    and re.fullmatch(r'(?:' + prefix + r'[,\s]*)*' + subject + r'\s+' + modifiers
                    + r'не\s+(?:понадобится|понадобятся|потребуется|потребуются|нужна|нужны|нужен|нужно)'
                    + r'(?:[,\s]+' + courtesy + r')*[,!\s]*', clean, re.I))
    return False


def other_provider_choice(message):
    """A client's completed current choice, not a plan or verified cancellation."""
    if (not _incoming(message) or not message.get('id')
            or message.get('sender_type', 'client') not in ('client','customer','user','contact','lead','')
            or message.get('out_pending')
            or str(message.get('delivery_status') or '').lower() in ('failed','error','pending','queued','sending','cancelled','canceled')):
        return None
    body = _text(message)
    if re.search(r'[?«»“”"]|\b(?:если|вдруг|допустим|возможно|наверно\w*|кажется)|не\s+(?:думаю|уверен)', body, re.I):
        return None
    clauses = [clause.strip(' ,!') for clause in re.split(r'[.!\n]+', body) if clause.strip(' ,!')]
    while clauses and re.fullmatch(r'(?:спасибо|благодарю|извините)(?:\s+за\s+беспокойство)?', clauses[-1], re.I):
        clauses.pop()
    if not clauses or not re.fullmatch(
            r'(?:но\s+)?(?:(?:я|мы)\s+)?(?:уже\s+)?выбрал[аи]?\s+(?:себе\s+)?другого\s+(?:мастера|специалиста)',
            clauses[-1], re.I):
        return None
    arrived = bool(re.search(r'\b(?:спасибо|благодарю)\s*[,—-]?\s*что\s+(?:вы\s+)?(?:приехали|подъехали|пришли)\b', body, re.I))
    return dict(message_id=message['id'], quote=body, source='client_message',
                kind='other_provider_selected', arrival_reported=arrived,
                arrival_verified=False, crm_cancellation_confirmed=False)


def preceding_staff_speech(messages, index):
    """Observed adjacent staff/client turns, never a future planned question."""
    for position in range(index - 1, -1, -1):
        row = messages[position]
        if (not isinstance(row, dict) or row.get('direction') in ('note', 'system')
                or row.get('sender_type') in ('system', 'avito')):
            continue
        if _incoming(row) and re.fullmatch(r'\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[,!\.\s]*', _text(row), re.I):
            continue
        staff = row.get('direction') == 'out' or row.get('role') == 'assistant'
        pending = row.get('out_pending') or str(row.get('delivery_status') or row.get('delivery') or '').lower() in (
            'failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')
        return (position, row) if staff and not pending else None
    return None


_QUANTITY_NUMBERS = {
    'один': 1, 'одна': 1, 'одно': 1, 'одного': 1, 'одном': 1,
    'два': 2, 'две': 2, 'двух': 2, 'двумя': 2,
    'три': 3, 'трех': 3, 'трёх': 3, 'четыре': 4, 'четырех': 4, 'четырёх': 4,
    'пять': 5, 'пяти': 5, 'шесть': 6, 'шести': 6,
}
_QUANTITY_OBJECTS = {
    'printer': r'принтер\w*|мфу', 'cartridge': r'картридж\w*',
    'fridge': r'холодильник\w*', 'seal': r'резинк\w*|уплотнител\w*',
    'tv': r'телевизор\w*', 'computer': r'компьютер\w*|ноутбук\w*',
}


def _quantity_mentions(text, generic_object=None):
    """Literal noun/count pairs; units, models and overlapping types stay separate."""
    source = str(text or '')
    number = r'(?:[1-9]\d?|' + '|'.join(_QUANTITY_NUMBERS) + ')'
    nouns = '|'.join(_QUANTITY_OBJECTS.values())
    if generic_object:
        nouns += r'|устройств\w*|аппарат\w*'
    patterns = [r'(?<![\w\d])(?P<count>' + number + r')\s+(?P<noun>' + nouns + r')\b',
                r'\b(?P<noun>' + nouns + r')\s+(?P<count>' + number + r')(?!\w)']
    quoted = [(m.start(), m.end()) for m in re.finditer(r'«[^»]*»|“[^”]*”|"[^"\n]*"', source)]
    result = []
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.I):
            noun = match['noun']
            family = next((key for key, value in _QUANTITY_OBJECTS.items()
                           if re.fullmatch(value, noun, re.I)), generic_object)
            start = max(source.rfind(mark, 0, match.start()) for mark in '.!?;\n') + 1
            end = next((pos for pos in range(match.end(), len(source)) if source[pos] in '.!?;\n'), len(source))
            clause = source[start:end + 1]
            certainty_clause = clause
            if (family == 'tv' and re.search(r'\b(?:нужн\w*|надо|прошу)\b', clause, re.I)
                    and re.search(r'повесить|навесить|установить|монтаж', clause, re.I)):
                # A trailing price enquiry in the same sentence does not
                # turn the preceding explicit work count into "two TVs?".
                certainty_clause = re.sub(
                    r'[,—\s]*(?:(?:а|и)\s+)?(?:сколько\s+(?:будет\s+)?сто(?:ит|ят|ить)|'
                    r'как(?:ая|ова)\s+(?:цена|стоимость))[^.!?;\n]*[?]\s*$', '', clause, flags=re.I)
            if family == 'tv' and match['count'].isdigit() and match.start('noun') < match.start('count'):
                suffix = source[match.end():end]
                if (re.match(r'\s*(?:(?:и|[,/хx×-])\s*\d{1,3})*\s*(?:дюйм|["″]|см\b)', suffix, re.I)
                        or noun.casefold() == 'телевизор' and not re.match(r'\s*(?:шт\b|штук|единиц)', suffix, re.I)):
                    # "Телевизоры 43 и65 дюймов" is a size correction,
                    # not43 devices. A singular model/size number without an
                    # explicit count unit cannot establish object quantity.
                    continue
            mode = 'asserted'
            if any(a <= match.start() < b for a, b in quoted):
                mode = 'quoted'
            elif (re.search(r'\?|\b(?:если|вдруг|возможно|наверн\w*|кажется|не\s+уверен\w*|неясн\w*|неизвестн\w*)\b', certainty_clause, re.I)
                  or family == 'tv' and re.search(r'\bили\s+(?:\d+|одн\w*|дв\w*|тр\w*|четыр\w*|'
                                                   r'пят\w*|шест\w*|сем\w*|восем\w*|девят\w*|десят\w*|нескольк\w*)\b', clause, re.I)):
                mode = 'uncertain'
            elif re.search(r'\b(?:сказал\w*|по\s+словам|сосед\w*|друг\w*\s+заказ\w*)\b', clause, re.I):
                mode = 'attributed'
            elif re.search(r'\b(?:планирую|планирует|буду|будет|хочу|хочет)\s+(?:купить|приобрести)\b', clause, re.I):
                mode = 'planned_purchase'
            elif re.search(r'\bне\s*$', source[start:match.start()], re.I):
                mode = 'negated'
            elif re.search(r'\b(?:сначала|раньше|ранее|первоначально)\b', source[start:match.start()].split(',')[-1], re.I):
                mode = 'historical'
            count = int(match['count']) if match['count'].isdigit() else _QUANTITY_NUMBERS[match['count'].casefold()]
            result.append(dict(object=family, count=count, quote=match[0], mode=mode,
                               span=list(match.span())))
    return result


def item_quantity_context(messages):
    """Source-bound quantities, never an automatic sum of appliance categories."""
    import assistant_prices
    evidence, objects = [], {}
    messages = assistant_prices.current_enquiry_messages(messages)
    for index, message in enumerate(messages):
        if (not _client_intent_message(message) or message.get('out_pending')
                or str(message.get('delivery_status') or message.get('delivery') or '').lower()
                in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')):
            continue
        body = _text(message)
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', literal, re.I):
            evidence, objects = [], {}
        parts = re.findall(r'(?:^|[,:;\s]|\bи)\s*([1-9])\s+(мфу|обычн\w*|со?\s+скан\w*)(?!\w)', literal, re.I)
        for item in _quantity_mentions(body):
            if len(parts) >= 2 and re.search(r'мфу', item['quote'], re.I):
                continue
            evidence.append(dict(item, message_id=message.get('id', ''), source='client_literal_count'))
            state = objects.setdefault(item['object'], dict(explicit_counts=[], current_count=None,
                current_message_id='', listed_type_units=None, total_unresolved=False))
            if item['mode'] == 'negated' and state['current_count'] == item['count']:
                state.update(current_count=None, total_unresolved=True)
            if item['mode'] != 'asserted':
                continue
            correction = bool(re.search(r'\b(?:поправка|точнее|ошиб\w*|на\s+самом\s+деле)\b', literal, re.I))
            if correction:
                state.update(explicit_counts=[item['count']], current_count=item['count'],
                             current_message_id=message.get('id', ''), total_unresolved=False,
                             listed_type_units=None)
            else:
                state['explicit_counts'] = list(dict.fromkeys(state['explicit_counts'] + [item['count']]))
                state.update(current_count=item['count'] if len(state['explicit_counts']) == 1 else None,
                             current_message_id=message.get('id', ''),
                             total_unresolved=len(state['explicit_counts']) != 1)
        # Elliptical type lists can follow a printer question in the same
        # client turn. A scanner function does not make an additional device.
        previous = preceding_staff_speech(messages, index)
        if (len(parts) >= 2 and not re.search(r'\?|\b(?:если|возможно|кажется|по\s+словам|сказал\w*)\b', literal, re.I)
                and ('printer' in objects or previous and re.search(r'принтер|мфу', _text(previous[1]), re.I))):
            state = objects.setdefault('printer', dict(explicit_counts=[], current_count=None,
                current_message_id='', listed_type_units=None, total_unresolved=False))
            units = sum(int(n) for n, _ in parts)
            unresolved = state['current_count'] != units or state['total_unresolved']
            state.update(listed_type_units=units, total_unresolved=unresolved,
                         current_count=None if unresolved else state['current_count'])
            evidence.append(dict(object='printer', message_id=message.get('id', ''), quote=body,
                source='client_literal_type_list', listed_type_units=units,
                types_may_overlap=True, mode='type_list_not_total'))
    if not evidence:
        return None
    return dict(source='server_literal_item_quantities', objects=objects, evidence=evidence,
                independent_model_understanding=False,
                interpretation='Количество относится только к названному предмету и своему сообщению. '
                    'Перечисленные типы могут пересекаться; не складывайте их в точное число устройств. '
                    'Неразрешённое противоречие не становится определённым числом в свободном пересказе. '
                    'Сохраняйте неопределённость или явно указанный клиентом источник/исправление, '
                    'не подменяйте весь смысл готовой строкой и не добавляйте обязательный вопрос.')


def tv_mount_work_volume(messages):
    """The count of the client's actual TV-mount work, not screen size."""
    import assistant_catalog
    import assistant_prices
    rows = [m for m in assistant_prices.current_enquiry_messages(messages)
            if _client_intent_message(m) and m.get('role') not in ('system', 'assistant')
            and m.get('speaker_role', 'client') == 'client' and not m.get('out_pending')
            and str(m.get('delivery_status') or m.get('delivery') or '').lower()
            not in ('failed', 'error', 'pending', 'queued', 'sending', 'processing', 'cancelled', 'canceled')]
    scope = assistant_catalog.choose('\n'.join(_text(m) for m in rows), dict(direction='mnc'))
    if scope['status'] != 'supported' or {item['id'] for item in scope['items']} != {'tv-mount'}:
        return None
    state = (item_quantity_context(rows) or {}).get('objects', {}).get('tv', {})
    count = state.get('current_count')
    if type(count) is not int or not 1 <= count <= 99 or state.get('total_unresolved'):
        return None
    source = next((m for m in rows if m.get('id') == state.get('current_message_id')), {})
    clauses = assistant_prices._literal_price_scope(_text(source)).split('\n')
    bound = next((clause for clause in clauses
                  if re.search(assistant_prices._INSTALL + '|' + assistant_prices._HANG, clause, re.I)
                  and any(item['object'] == 'tv' and item['count'] == count and item['mode'] == 'asserted'
                          for item in _quantity_mentions(clause))), None)
    if not bound:
        return None
    return dict(count=count, message_id=source.get('id', ''), quote=_text(source),
                value=f'{count} телевизора для навеса', source='client_literal_current_mount_count',
                booking_confirmed=False, independent_model_understanding=False)


def item_quantity_violations(candidate, context):
    if not context:
        return []
    objects = context['objects']
    generic = 'printer' if set(objects) == {'printer'} else None
    review = candidate.get('context_review') or {}
    for prose in [candidate.get('reply', ''), *[review.get(k, '') for k in ('last_intent', 'latest_client_meaning', 'note')]]:
        for mention in _quantity_mentions(prose, generic):
            if mention['mode'] != 'asserted':
                continue
            state = objects.get(mention['object'])
            if state and (state['total_unresolved'] or state['current_count'] != mention['count']):
                return ['item_quantity_not_grounded']
            if not state and mention['count'] > 1 and any(row['object'] != mention['object']
                    and row['count'] == mention['count'] for row in context['evidence'] if 'count' in row):
                return ['item_quantity_not_grounded']
    return []


def alternative_visit_day_preference(messages):
    """A day still to choose after an observed promise to check the schedule.

    This records a conversational preference, never crew availability, an
    accepted appointment, or completion of the staff member's promised check.
    """
    if not messages or not _client_intent_message(messages[-1]):
        return None
    body = _text(messages[-1]).strip()
    if (len(body) > 220 or re.search(r'[«»“”"?]|\bне\s+(?:надо|нужно|давайте)|'
                                   r'сказал|написал|спросил|\bвчера\b|\bпозавчера\b|'
                                   r'звон|куп|достав|забра|привез|материал|детал', body, re.I)
            or not re.fullmatch(
                r'(?:Хорошо[.! ,]*)?(?:Если\s+сегодня\s+у\s+вас\s+не\s+получается\s*,?\s*)?'
                r'(?:давайте|можно)\s*,?\s*на\s+другой\s+день[.!\s]*', body, re.I)):
        return None
    previous = preceding_staff_speech(messages, len(messages) - 1)
    if not previous:
        return None
    _, staff = previous
    if staff.get('direction') != 'out':
        return None
    promise = _text(staff).strip()
    if not re.fullmatch(r'(?:Я\s+)?(?:посмотрю\s+по\s+графику|уточню\s+график\s+выезда)'
                        r'\s*[,—-]?\s*(?:(?:и\s+)?вам\s+напишу)?[.!\s]*', promise, re.I):
        return None
    return dict(message_id=messages[-1].get('id', ''), quote=body,
                staff_message_id=staff.get('id', ''), staff_quote=promise,
                source='client_alternative_after_pending_schedule_check',
                day_chosen=False, availability_verified=False,
                appointment_confirmed=False, crm_write_confirmed=False)


def _preceding_visit_question(messages, index):
    previous = preceding_staff_speech(messages, index)
    if not previous:
        return None
    _, row = previous
    prompt = _text(row)
    if (prompt.count('?') != 1 or re.search(r'звон|созвон|телефон|номер|куп|привез|принос|забрать|фото|снимок|достав|\bк\s+нам\b', prompt, re.I)):
        return None
    visit = re.search(r'\b(?:когда|во\s+сколько|на\s+какое\s+время)\b[^?!]{0,80}\b(?:меня|мастера|специалиста)\s+принять\b|'
                      r'\bкогда\b[^?!]{0,40}\b(?:(?:я\s+)?(?:могу|смогу)|(?:мне|нам)\s+(?:можно|удобно))'
                      r'[^?!]{0,30}\b(?:приехать|подъехать|подойти)\b', prompt, re.I)
    return row if visit else None


def _short_visit_question(messages, index, body):
    if not re.fullmatch(r'\s*(?:а\s+)?(?:вы\s+)?(?:сегодня|завтра|послезавтра)\s+(?:вы\s+)?(?:сможете|можете)\s*\?\s*', body, re.I):
        return None
    return _preceding_visit_question(messages, index)


VISIT_RANGE = re.compile(
    r'\b(?P<day>послезавтра|сегодня|завтра)\s+с\s*'
    r'(?P<start>(?:[01]?\d|2[0-3])[:.][0-5]\d)\s*(?:[-–—]|до)\s*'
    r'(?P<end>(?:[01]?\d|2[0-3])[:.][0-5]\d)(?!\d)', re.I)


def client_visit_range(messages, index):
    """A literal requested range; no inferred 12-hour conversion or booking."""
    message = messages[index]
    body = _text(message)
    matches = list(VISIT_RANGE.finditer(body))
    if (not _incoming(message) or message.get('role') == 'assistant'
            or message.get('sender_type') in ('operator', 'assistant', 'bot', 'system', 'avito')
            or len(matches) != 1 or len(re.findall(r'\b(?:послезавтра|сегодня|завтра)\b', body, re.I)) != 1
            or re.search(r'позвон|перезвон|созвон|напиш|напис|свяж|куп|привез|принос|забрать|фото|снимок|'
                         r'\bесли\b|\bне\b|\bили\b|сосед|мастер\s+(?:сказал|написал)|[«»“”"]', body, re.I)
            or re.search(r'\b(?:я|сам|сама|мы)\b[^.!?\n]{0,25}\b(?:приед|подъед|заед)', body, re.I)):
        return None
    question = _preceding_visit_question(messages, index)
    explicit = re.search(r'мне\s+удобно|хочу\s+записаться|(?:можете|сможете)\s+(?:приехать|подъехать)', body, re.I)
    if not question and not explicit:
        return None
    match = matches[0]
    hours = [int(match[key].replace('.', ':').split(':')[0]) for key in ('start', 'end')]
    daypart = re.search(r'\b(?:дн[её]м|утром|вечером|ночи|после\s+обеда)\b', body, re.I)
    ambiguous = not daypart and any(1 <= hour <= 12 for hour in hours)
    minutes = [int(match[key].replace('.', ':').split(':')[0]) * 60
               + int(match[key].replace('.', ':').split(':')[1]) for key in ('start', 'end')]
    invalid_order = minutes[1] <= minutes[0]
    result = dict(message_id=message.get('id', ''), quote=body[:500],
                  window=match[0].casefold() + (' ' + daypart[0].casefold() if daypart else ''),
                  source='client_message', status='requested', appointment_confirmed=False,
                  requires_clarification=bool(ambiguous or invalid_order),
                  clarification_kind='range_order' if invalid_order else 'daypart' if ambiguous else '')
    if question:
        result.update(question_message_id=question.get('id', ''), question_quote=_text(question)[:500])
    return result


def confirmed_visit_daypart(messages, index, period):
    """Bind a bare yes only to the delivered question about this exact range."""
    if (not period.get('requires_clarification') or period.get('clarification_kind') != 'daypart'
            or not period.get('message_id')):
        return None
    message = messages[index]
    if (not _incoming(message) or message.get('role') == 'assistant'
            or message.get('sender_type') in ('operator', 'assistant', 'bot', 'system', 'avito')
            or not re.fullmatch(r'\s*да(?:[,!.\s]+дн[её]м)?[.!\s]*', _text(message), re.I)):
        return None
    previous = preceding_staff_speech(messages, index)
    if not previous:
        return None
    position, question = previous
    if not re.fullmatch(r'\s*Это время дн[её]м\?\s*', _text(question), re.I):
        return None
    source = next((m for m in reversed(messages[:position]) if _incoming(m)
                   and m.get('sender_type') not in ('system', 'avito')), {})
    if source.get('id') != period['message_id']:
        return None
    return dict(period, window=period['window'] + ' днём', requires_clarification=False,
                range_message_id=period['message_id'], range_quote=period['quote'],
                message_id=message.get('id', ''), quote=_text(message)[:500],
                question_message_id=question.get('id', ''), question_quote=_text(question)[:500])


def explicit_visit_expectation(body):
    """One literal customer time, not a slot check or a CRM booking.

    Only a complete positive waiting statement is confirmation. Quotations,
    conditions, questions, callbacks and multiple alternatives do not qualify.
    Calendar words stay literal: no conversion using the machine's date.
    """
    day = r'(?:сегодня|завтра|послезавтра|в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))'
    clock = r'(?P<time>(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?)(?![\d.:])'
    when = rf'(?:(?P<day>{day})\s+(?:тогда\s+)?)?(?P<at>в|к)\s*{clock}'
    waiting = r'(?:вас\s+(?:жду|жд[её]м|ожидаю|ожидаем)|(?:жду|жд[её]м|ожидаю|ожидаем)\s+вас)'
    prefix = r'\s*(?:(?:да|хорошо|отлично|договорились|тогда)[,!\s]+)*'
    suffix = r'[.!(),\s]*(?:(?:спасибо|благодарю)[.!()\s]*)?'
    found = None
    for pattern in (when + r'[,\s]+' + waiting, waiting + r'[,\s]+' + when):
        found = re.fullmatch(prefix + pattern + suffix, body, re.I)
        if found:
            break
    if not found:
        return None
    parts = found['time'].replace('.', ':').split(':')
    time = f'{int(parts[0]):02d}:{int(parts[1]) if len(parts) == 2 else 0:02d}'
    day = re.sub(r'\s+', ' ', found['day'] or '').casefold()
    return dict(day=day, time=time, window=' '.join(filter(None, (day, found['at'].casefold() + ' ' + time))))


def named_visit_preference(messages, index):
    """One literal calendar preference; no clock inference or booking proof.

    Preserve an ambiguous replacement as ambiguous instead of silently using
    the previous day. The existing territory, availability and CRM gates still
    decide whether any visit can be proposed or created.
    """
    from datetime import date as calendar_date
    message = messages[index]
    if (not _client_intent_message(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client' or message.get('out_pending')
            or str(message.get('delivery_status') or message.get('delivery') or '').lower()
            in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')):
        return None
    body = _text(message)
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), body)
    months = {'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,
              'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
    pattern = (r'\b(?P<day>\d{1,2})(?:-го)?\s+(?P<month>'+'|'.join(months)+r')\b'
               r'(?:\s+(?P<year>\d{4})(?:\s*(?:года|г[.]))?)?\s+'
               r'(?P<at>после|до|в|к)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})(?![\d:])')
    found = list(re.finditer(pattern, literal, re.I))
    if not found:
        return None
    qualified = []
    for match in found:
        start = max(literal.rfind(c,0,match.start()) for c in '.!?;\n')+1
        ends = [n for c in '.!?;\n' if (n:=literal.find(c,match.end()))>=0]
        clause = literal[start:min(ends) if ends else len(literal)]
        if (re.search(r'\b(?:если|допустим|возможно|сказал\w*|написал\w*|спросил\w*|сосед\w*)\b|'
                      r'позвон|перезвон|созвон|напиш|напис|куплю|купим|привез|принос|забрать|фото|снимок|'
                      r'\b(?:я|мы|сам|сама)\b[^.!?;\n]{0,25}\b(?:приед|подъед|заед)', clause,re.I)):
            continue
        preference = re.search(r'\b(?:(?:мне|нам)\s+)?удобно\b|\b(?:прим[уе]|примем|жду\s+вас)\b',clause,re.I)
        cancellation = re.search(r'\b(?:неудобно|не\s+подходит|отменяю)\b|\bне\s+(?:после|до|в|к)\s*\d',clause,re.I)
        if not preference and not cancellation and not _preceding_visit_question(messages,index):
            continue
        qualified.append((match,cancellation))
    if not qualified:
        return None
    result = dict(message_id=message.get('id',''),quote=body[:500],source='client_message',
                  stated_at=str(message.get('created_at')or''),appointment_confirmed=False,
                  client_confirmed=False,calendar_source='literal_named_month',requires_clarification=False)
    if len(qualified)!=1:
        return dict(result,status='ambiguous',window='',requires_clarification=True,clarification_kind='calendar')
    match,cancelled=qualified[0]
    if cancelled:
        return dict(result,status='withdrawn',window='',requires_clarification=True,clarification_kind='calendar')
    try:
        day = calendar_date(int(match['year']),months[match['month'].lower()],int(match['day']))
        hour,minute=int(match['hour']),int(match['minute'])
        if not 0<=hour<=23 or not 0<=minute<=59:raise ValueError('Invalid clock')
    except (ValueError,TypeError):
        return dict(result,status='ambiguous',window='',requires_clarification=True,clarification_kind='calendar')
    if match['at'].lower() in ('после','до'):
        return dict(result,status='requested',window=match[0],date_iso=day.isoformat(),
                    date_text=match[0][:match.start('at')-match.start()].strip(),
                    time_kind='after' if match['at'].lower()=='после' else 'before',
                    boundary_time=f'{hour:02d}:{minute:02d}',
                    requires_clarification=True,clarification_kind='exact_clock')
    return dict(result,status='requested',window=match[0],date_iso=day.isoformat(),time=f'{hour:02d}:{minute:02d}')


def requested_visit(messages):
    """Preserve a clear client visit preference, never a booked appointment.

    Relative dates are quoted, not converted using today's clock. Contact,
    purchase and drop-off plans must not become a technician's visit.
    """
    result = {}
    for index, message in enumerate(messages):
        if (not _incoming(message) or message.get('role') == 'assistant'
                or message.get('sender_type') in ('operator', 'assistant', 'bot', 'employee', 'staff', 'system', 'avito')):
            continue
        body = _text(message)
        if re.search(r'\b(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно)\b', body, re.I):
            result = {}
        if other_provider_choice(message) or explicit_help_withdrawal(body) or re.search(r'\bне\s+(?:нужно|надо|приед|сегодня|завтра|можете|сможете)|отмен|передумал', body, re.I):
            result = {}
            continue
        named = named_visit_preference(messages,index)
        if named:
            result = named if named['status']!='withdrawn' else {}
            continue
        expectation = explicit_visit_expectation(body)
        if expectation:
            result = dict(expectation, message_id=message.get('id', ''), quote=body[:500],
                          source='client_message', status='requested', client_confirmed=True,
                          stated_at=str(message.get('created_at') or ''), appointment_confirmed=False)
            continue
        clarified = confirmed_visit_daypart(messages, index, result)
        if clarified:
            result = clarified
            continue
        if VISIT_RANGE.search(body):
            period = client_visit_range(messages, index)
            if period:
                result = period
            continue
        if re.search(r'позвон|перезвон|созвон|напиш|напис|свяж|куп|привез|принос|забрать|фото|снимок', body, re.I):
            continue
        if re.search(r'\bнет\b|не\s+(?:раньше|позже)|\b(?:я|сам|сама|мы)\b[^.!?\n]{0,25}\b(?:приед|подъед|заед)', body, re.I):
            continue
        visit_question = (re.search(r'можете|сможете|приедете|подъедете|заедете|выезжаете', body, re.I)
                          and re.search(r'прие|подъе|зае|поех|выезд|прибы', body, re.I))
        explicit_preference = re.search(r'мне\s+удобно|(?:нужен|нужна)\s+(?:мастер|помощь)|хочу\s+записаться', body, re.I)
        contextual_question = _short_visit_question(messages, index, body)
        days = list(re.finditer(r'\b(?:послезавтра|сегодня|завтра)\b', body, re.I))
        windows = list(re.finditer(r'\b(?:после\s+обеда|с\s+утра|утром|вечером|дн[её]м|'
                                  r'(?:в|к|после|до)\s+(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?(?!\d))\b', body, re.I))
        if (not visit_question and not explicit_preference and not contextual_question) or len(days) != 1 or len(windows) > 1:
            continue
        window = re.sub(r'\s+', ' ', ' '.join([days[0][0]] + [m[0] for m in windows])).casefold()
        result = dict(message_id=message.get('id', ''), quote=body[:500], window=window,
                      source='client_message', status='requested', appointment_confirmed=False)
        if contextual_question:
            result.update(question_message_id=contextual_question.get('id', ''), question_quote=_text(contextual_question)[:500])
    return result


def written_landline_parts(messages, index):
    """Merge only a labelled customer phone and their explicit city code.

    Advertising geography never supplies a code. A complete later phone or a
    new enquiry separates scopes; conflicting subscriber parts stay unresolved.
    """
    def eligible(message):
        return (_incoming(message) and message.get('sender_type') not in ('bot', 'system', 'operator', 'assistant', 'avito')
                and not message.get('unread_media') and not message.get('voice_transcript')
                and not message.get('attachments'))

    def code(message):
        return re.fullmatch(r'\s*(?:телефонный\s+)?код(?:\s+города)?\s*[:—-]?\s*([348]\d{2,4})[.!\s]*', _text(message), re.I)

    def subscriber(message):
        text = _text(message)
        match = re.fullmatch(r'\s*(?:(?:мой|наш)\s+)?(?:стационарный|городской|домашний)\s+(?:телефон|номер)\s*[:—-]?\s*([1-9]\d{4,6})[.!\s]*', text, re.I)
        if not match:
            match = re.fullmatch(r'\s*(?:позвоните|наберите)\s+?([1-9]\d{4,6})(?:\s+как\s+собер[её]тесь)?[.!\s]*', text, re.I)
            if not match:
                match = re.fullmatch(r'\s*(?:позвоните|наберите)([1-9]\d{4,6})(?:\s+как\s+собер[её]тесь)?[.!\s]*', text, re.I)
        return match

    def stamp(message):
        try:
            parsed = datetime.fromisoformat(str(message.get('created_at') or '').replace('Z', '+00:00'))
            return parsed.timestamp() if parsed.tzinfo else None
        except (ValueError, TypeError):
            return None

    current = messages[index]
    if not eligible(current) or not (code(current) or subscriber(current)):
        return None
    current_time = stamp(current)
    if current_time is None:
        return None
    codes, numbers = [], []
    for message in reversed(messages[max(0, index-30):index+1]):
        if not eligible(message):
            continue
        text = _text(message)
        if contact_phone.find_all(text) or re.search(r'\b(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', text, re.I):
            break
        cm, nm = code(message), subscriber(message)
        if not (cm or nm):
            continue
        when = stamp(message)
        if when is None or not 0 <= current_time-when <= 86400:
            break
        if cm:
            codes.append((cm[1], message))
        if nm:
            numbers.append((nm[1], message))
    if not codes or not numbers:
        return None
    if len({v for v, _ in codes}) != 1 or len({v for v, _ in numbers}) != 1:
        return dict(value='', conflict=True)
    city_code, code_message = codes[0]
    number, number_message = numbers[0]
    if len(city_code+number) != 10:
        return dict(value='', conflict=True)
    value = contact_phone.normalize('+7'+city_code+number)
    if not value:
        return None
    parts = sorted((code_message, number_message), key=lambda m: stamp(m))
    return dict(value=value, raw='; '.join(_text(m) for m in parts),
                message_ids=[m.get('id', '') for m in parts],
                context_message_id=number_message.get('id', ''))


def written_phone_fragments(messages, index):
    """A complete, rapid client-only numeric burst answering a phone request.

    Keep the entire burst rather than finding a phone-looking suffix. Partial
    or overlong continuations can retract an earlier derived candidate.
    """
    def eligible(m):
        return (_incoming(m) and m.get('sender_type') not in ('bot','system','operator','assistant','avito')
                and not m.get('attachments') and not m.get('unread_media')
                and not m.get('voice_transcript') and contact_phone.is_fragment(_text(m)))

    def stamp(m):
        try:
            value = datetime.fromisoformat(str(m.get('created_at') or '').replace('Z', '+00:00'))
            return value.timestamp() if value.tzinfo else None
        except (ValueError, TypeError):
            return None

    if not eligible(messages[index]):
        return None
    start = index
    while start and eligible(messages[start-1]):
        start -= 1
    burst = messages[start:index+1]
    if len(burst) < 2:
        return None
    times = [stamp(m) for m in burst]
    if (any(t is None for t in times) or times[-1] - times[0] > 300
            or any(not 0 <= b-a <= 120 for a, b in zip(times, times[1:]))):
        return None
    anchor = None
    for m in reversed(messages[:start]):
        body = _text(m)
        if m.get('direction') == 'out':
            # A model/flat/order number question is not a contact request.
            noncontact = (not re.search(r'телефон', body, re.I)
                          and re.search(r'номер\s+(?:модел|дом|квартир|подъезд|этаж|детал|заказ|заявк|серийн|сч[её]тчик)', body, re.I))
            if (not m.get('out_pending') and not noncontact
                    and re.search(r'\b(?:номер|номре|телефон)\w*\b', body, re.I)
                    and re.search(r'\?|подскаж|остав|напиш|связ|дайте|нужен', body, re.I)):
                anchor = m
            break
        if _incoming(m) and re.fullmatch(r'\s*(?:(?:мой|наш)\s+)?(?:номер|телефон)(?:\s+для\s+связи)?\s*[:.!]?\s*', body, re.I):
            anchor = m
            break
    anchor_time = stamp(anchor or {})
    if not anchor or anchor_time is None or not 0 <= times[0] - anchor_time <= 86400:
        return None
    parts = [_text(m).strip() for m in burst]
    digits = re.sub(r'\D', '', ''.join(parts))
    complete = bool(re.fullmatch(r'(?:[78]9\d{9}|9\d{9})', digits))
    found = contact_phone.from_fragments(parts) if complete else None
    if found and found.value != contact_phone.normalize(digits):
        found = None
    return dict(found=found, raw='; '.join(parts), message_ids=[m.get('id','') for m in burst],
                context_message_id=anchor.get('id',''))


def reviewed_image_contact(messages, index):
    """A reviewed contact needs both the exact image and customer context.

    A supplier label is never a customer phone. Reviewing a photograph alone
    does not confirm a booking, a diagnosis, or ownership of every printed field.
    """
    message = messages[index]
    observation = message.get('media_observation') or {}
    if (not _incoming(message) or message.get('sender_type') in ('bot','system','operator','assistant','avito')
            or not message.get('media_reviewed') or message.get('unread_media')
            or message.get('image_count') != 1 or not message.get('reviewable_image')
            or observation.get('source') not in ('reviewed_image','offline_reviewed_image')
            or not message.get('id') or observation.get('message_id') != message['id']
            or not message.get('media_signature') or observation.get('signature') != message['media_signature']
            or observation.get('content_kind') != 'contact_note' or observation.get('contact_role') != 'customer'):
        return None
    raw = observation.get('contact_phone')
    phone = contact_phone.normalize(raw) if isinstance(raw, str) else None
    if not phone:
        return None
    caption = _text(message)
    own_contact = re.search(r'\b(?:мой|наш)\s+(?:номер|телефон)\b|\b(?:номер|телефон)\s+для\s+связи\b', caption, re.I)
    previous = next((m for m in reversed(messages[:index])
                     if m.get('direction') in ('in','out') and m.get('sender_type') not in ('system','avito')), {})
    question = _text(previous)
    requested = (previous.get('direction') == 'out' and not previous.get('out_pending')
                 and re.search(r'\b(?:номер|номре|телефон)\b', question, re.I)
                 and re.search(r'\?|подскаж|остав|напиш|связ', question, re.I))
    if not (own_contact or requested):
        return None
    return dict(value=phone, raw=raw, message_id=message['id'], source=observation['source'],
                signature=message['media_signature'], context_message_id=message['id'] if own_contact else previous['id'])


def collect(messages, known=None):
    known = known or {}
    phones: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, str]] = []
    notes, ambiguities, rejected = [], [], []
    address_references = []
    address: dict[str, str] = dict(known.get("card_address") or {})
    for key in address:
        evidence["address." + key] = {"message_id": "client-card", "quote": "Подтверждено в карточке LeadChat для этого диалога"}
    preferred, asked_address, last_out = "", False, ""
    phone_selection, backup_candidate = None, None
    fallbacks = []
    call_before_visit = False
    uncertain_address_fields = []
    required_crew_count, intercom_working, intercom_present = None, None, None
    needs_phone_confirmation = False
    landline_unresolved = False
    card_phone = contact_phone.normalize(known.get("phone"))
    if card_phone:
        phones.append({"value": card_phone, "message_id": "client-card", "raw": str(known["phone"]), "role": "card"})
        preferred = card_phone
    for index, message in enumerate(messages or []):
        text = _text(message).strip()
        image_contact = reviewed_image_contact(messages, index)
        if not text and not image_contact:
            continue
        if not _incoming(message):
            previous = messages[index - 1] if index else {}
            access_request = _text(previous).strip()
            if (_incoming(previous) and not _NO_CALL.search(access_request)
                    and re.search(r'\bза\s+(?:мин(?:ут)?\.?\s+)?\d{1,3}(?:\s+минут)?\s*[,;—-]?\s*чтобы\s+(?:открыть|встретить)', access_request, re.IGNORECASE)
                    and re.search(r'\b(?:наберу|позвоню)(?:\s+вам)?\s+за\s+\d{1,3}\s+(?:минут|час)', text, re.IGNORECASE)
                    and not re.search(r'\bне\s+(?:наберу|позвоню)', text, re.IGNORECASE)):
                call_before_visit = True
                evidence['call_before_visit'] = dict(message_id=previous.get('id', ''),
                    commitment_message_id=message.get('id', ''),
                    kind='client_access_request_and_staff_commitment',
                    quote=(access_request + '\nСотрудник: ' + text)[:500])
            asked_address = bool(_ADDRESS_QUESTION.search(text))
            last_out = text
            continue
        mid = str(message.get("id") or f"message-{index}")
        confirmation = _observed_current_address_confirmation(messages, index, address, conflicts, evidence)
        if confirmation:
            conflicts.clear()
            evidence['address.confirmation'] = confirmation
        prior_access = (intercom_present, intercom_working, call_before_visit)
        prior_access_evidence = {k: evidence[k] for k in ('intercom_present', 'intercom_working', 'call_before_visit') if k in evidence}
        for crew in _CREW_REQUEST.finditer(text):
            negated = bool(re.search(r'\bне\s*$', text[:crew.start()], re.IGNORECASE))
            required_crew_count = None if negated else 2 if crew[1].lower() in ('два', 'двое', '2') else 1
            evidence['required_crew_count'] = dict(message_id=mid, quote=('Не ' if negated else '') + crew[0], withdrawn=negated)
        intercom_status = (re.search(r'\bдомофон(?:а)?\s*[-—:]?\s*(не\s+работает|нет|отсутствует|работает|есть)\b', text, re.IGNORECASE)
                          or re.search(r'\b(нет)\s+домофона\b', text, re.IGNORECASE))
        if intercom_status:
            status = intercom_status[1].lower()
            intercom_present = status not in ('нет', 'отсутствует')
            intercom_working = None if status == 'есть' else status == 'работает'
            if intercom_working is None:
                evidence.pop('intercom_working', None)
            else:
                evidence['intercom_working'] = dict(message_id=mid, quote=intercom_status[0])
            evidence['intercom_present'] = dict(message_id=mid, quote=intercom_status[0])
            if not intercom_present:
                # A code from an earlier address/card is no longer current.
                # A door code in this same message can still be added below.
                address.pop('intercom', None)
                evidence.pop('address.intercom', None)
        elif (ellipsis := re.search(r'\bлифт\s+(не\s+)?работает\s*[,;]\s*домофон\s*[-—:]?\s*тоже\b', text, re.IGNORECASE)):
            intercom_present = True
            intercom_working = not bool(ellipsis[1])
            evidence['intercom_working'] = dict(message_id=mid, quote=text[:500], kind='same_clause_ellipsis_to_working_lift')
            evidence['intercom_present'] = dict(message_id=mid, quote=text[:500], kind='same_clause_ellipsis_to_working_lift')
        elif (present := re.search(r'\bесть\s+домофон\b', text, re.IGNORECASE)):
            intercom_present, intercom_working = True, None
            evidence.pop('intercom_working', None)
            evidence['intercom_present'] = dict(message_id=mid, quote=present[0])
        if _NO_CALL.search(text):
            call_before_visit = False
            evidence.pop("call_before_visit", None)
        elif _CALL_BEFORE.search(text) or _ADVANCE_CALL.search(text) or _MINUTES_CALL.search(text) or _arrival_call_requested(text):
            call_before_visit = True
            evidence["call_before_visit"] = {"message_id": mid, "quote": _call_request_quote(text)}
        found = contact_phone.find_all(text)
        if found:
            landline_unresolved = False
        landline = written_landline_parts(messages, index)
        if landline and landline.get('value'):
            found.append(contact_phone.Found(value=landline['value'], raw=landline['raw'], start=0, end=0))
            landline_unresolved = False
        elif landline:
            phones = [p for p in phones if p.get('source') != 'client_landline_parts']
            preferred, landline_unresolved = '', True
        fragment = written_phone_fragments(messages, index)
        if fragment:
            ids = set(fragment['message_ids'])
            phones = [p for p in phones if not (p.get('source') == 'client_phone_fragments'
                      and set(p.get('fragment_message_ids', [])) <= ids)]
            if preferred and not any(p['value'] == preferred for p in phones):
                preferred, phone_selection = '', None
            if fragment['found']:
                found.append(contact_phone.Found(value=fragment['found'].value, raw=fragment['raw'], start=0, end=0))
        if image_contact:
            found.append(contact_phone.Found(value=image_contact['value'], raw=image_contact['raw'], start=0, end=0))
        for access in _PHONE_AFTER_ACCESS.finditer(text):
            value = contact_phone.normalize(access['phone'])
            if value and not any(p.start == access.start('phone') for p in found):
                found.append(contact_phone.Found(value=value, raw=access['phone'], start=access.start('phone'), end=access.end('phone')))
        # Only the observed 4/4/3 mobile layout is joined. Two complete
        # numbers on separate lines remain independent candidates.
        for split in _SPLIT_MOBILE.finditer(text):
            value = contact_phone.normalize(split['a'] + split['b'] + split['c'])
            if value:
                found.append(contact_phone.Found(value=value, raw=split[0], start=split.start(), end=split.end()))
        prior_preferred = preferred
        if found:
            phone_selection = None
        requested = []
        for phone in found:
            context = text[max(0, phone.start - 45):phone.end + 45]
            call = bool(_CALL.search(context)) and not re.search(r"не\s+звон", context, re.IGNORECASE)
            record = {"value": phone.value, "message_id": mid, "raw": phone.raw,
                      "start": phone.start, "end": phone.end, "role": "contact" if call else "provided"}
            if image_contact and phone.end == 0:
                record.update(source=image_contact['source'], signature=image_contact['signature'],
                              context_message_id=image_contact['context_message_id'])
            elif fragment and fragment['found'] and phone.end == 0:
                record.update(source='client_phone_fragments', fragment_message_ids=fragment['message_ids'],
                              context_message_id=fragment['context_message_id'])
            elif landline and phone.end == 0:
                record.update(source='client_landline_parts', fragment_message_ids=landline['message_ids'],
                              context_message_id=landline['context_message_id'])
            phones.append(record)
            if call:
                requested.append(phone.value)
        values = list(dict.fromkeys(p["value"] for p in phones))
        unique_found = list(dict.fromkeys(p.value for p in found))
        phone_mixup = any(not re.search(r'\bне\s*$', text[:m.start()], re.IGNORECASE)
                          for m in _PHONE_MIXUP.finditer(text))
        provided = list(dict.fromkeys(p["value"] for p in phones if p["role"] != "card"))
        ordinal = _PHONE_ORDINAL_ANSWER.fullmatch(text)
        previous_client = messages[index - 1] if index and _incoming(messages[index - 1]) else {}
        previous_numbers = contact_phone.find_all(_text(previous_client))
        explicit_alternative = bool(
            len(found) == 1 and len(values) == 2 and prior_preferred
            and len(previous_numbers) == 1 and previous_numbers[0].value == prior_preferred
            and re.fullmatch(r'\s*или\s*[:—-]?\s*', text[:found[0].start], re.IGNORECASE)
            and re.fullmatch(r'[.!\s]*', text[found[0].end:]))
        backup = (unique_found[0] if len(unique_found) == 1 and prior_preferred and unique_found[0] != prior_preferred and _EXPLICIT_BACKUP.search(text) else
                  unique_found[0] if explicit_alternative else
                  backup_candidate['alternate'] if backup_candidate and backup_candidate['index'] == index - 1 and _BACKUP_FOLLOWUP.fullmatch(text) else '')
        if backup:
            preferred = prior_preferred or backup_candidate['primary']
            needs_phone_confirmation = False
            for p in phones:
                if p['value'] == backup:
                    p['role'] = 'fallback'
            fallbacks.append({'value': backup, 'message_id': mid, 'quote': text[:500]})
            phone_selection = {'message_id': mid, 'quote': text, 'kind': 'explicit_alternative' if explicit_alternative else 'explicit_backup'}
            backup_candidate = None
        elif _PHONE_CHOICE_QUESTION.search(last_out) and (len(unique_found) == 1 or ordinal and len(provided) == 2):
            preferred = unique_found[0] if unique_found else provided[0 if ordinal[1].lower() == "первый" else 1]
            needs_phone_confirmation = False
            phone_selection = {"message_id": mid, "quote": text}
        elif phone_mixup:
            preferred, needs_phone_confirmation = (unique_found[0], False) if len(unique_found) == 1 else ('', True)
            phone_selection = dict(message_id=mid, quote=text, kind='explicit_correction') if preferred else None
        elif unique_found and re.search(r"втор[оы]", text, re.IGNORECASE) and _CALL.search(text):
            preferred, needs_phone_confirmation = unique_found[-1], False
        elif len(set(requested)) == 1:
            preferred, needs_phone_confirmation = requested[0], False
        elif len(unique_found) == 1 and (_CORRECTION.search(text) or phone_mixup):
            preferred, needs_phone_confirmation = unique_found[0], False
            phone_selection = dict(message_id=mid, quote=text, kind='explicit_correction')
        elif len(values) == 1:
            preferred, needs_phone_confirmation = values[0], False
        elif found and len(values) > 1:
            preferred, needs_phone_confirmation = "", True
            phone_selection = None
            backup_candidate = ({'primary': prior_preferred, 'alternate': unique_found[0], 'index': index}
                                if prior_preferred and len(unique_found) == 1 and len(values) == 2 else None)
        if not found and (phone_mixup or _CORRECTION.search(text) and re.search(r"номер|телефон", text, re.IGNORECASE)):
            preferred, needs_phone_confirmation = "", True
        if landline_unresolved:
            preferred, needs_phone_confirmation = '', True

        if not text:
            # Keep a typed contact out of the address, task and consent parsers.
            asked_address, last_out = False, ''
            continue

        # Parse fragments in context, then merge only client-stated fields.
        # Preserve the original quote; normalize only this observed field-label
        # typo so a floor cannot overwrite the already known street and house.
        parse_text = re.sub(r"\bэтпж(?=\s+\d{1,2}\b)", "этаж", text, flags=re.IGNORECASE)
        # In a labelled microdistrict/house/flat chain, "104д-9кв" uses
        # postfix field labels. An explicitly prefixed "д104д" keeps its
        # literal house letter. The original quote remains evidence.
        parse_text = re.sub(r'(\b\d{1,3}[а-яё]?\s*(?:мкр\.?|микрорайон|квартал)\s*[-–—,]\s*\d{1,4})д(?=\s*[-–—,]\s*\d{1,4}\s*кв\b)',
                            r'\1 дом', parse_text, flags=re.I)
        ambiguous_access = re.compile(r'(?<![\w.,])\d{1,2}[.,]\d{1,2}\s+этаж\w*\b', re.I)
        if ambiguous_access.search(parse_text):
            notes.append(dict(message_id=mid, quote=text[:500], kind='ambiguous_access'))
            # Preserve the full quote, but do not pick the trailing number as
            # a floor or reinterpret the leading number as an entrance.
            parse_text = ambiguous_access.sub(lambda m: ' ' * len(m[0]), parse_text)
        # An invitation before the address is speech, not an untyped town.
        # Spaces preserve offsets for the house/unit parser and original quote.
        parse_text = re.sub(r'^\s*(?:приезжайте|подъезжайте)(?:\s+(?:посмотрите|пожалуйста)){0,2}[,.!\s]+',
                            lambda m: ' ' * len(m[0]), parse_text, flags=re.I)
        previous = _PAST_ADDRESS.search(parse_text)
        current = _CURRENT_ADDRESS.search(parse_text, previous.end()) if previous else None
        if previous and current and not re.search(r'\bне\s*$', parse_text[:previous.start()], re.I):
            # The client explicitly supplies a replacement in the same text.
            # Mask only the obsolete prefix; source offsets/quote stay intact.
            parse_text = ' ' * current.end() + parse_text[current.end():]
        explicit = _STREET_WITH_CITY_WORD.search(parse_text)
        numbered_place = _NUMBERED_PLACE_HOUSE.search(parse_text) or _REVERSED_NUMBERED_PLACE.search(parse_text) or _POSTFIX_PLACE_HOUSE.search(parse_text) or _MID_NUMBERED_PLACE.search(parse_text) or _MID_NUMBERED_PLACE_HOUSE.search(parse_text)
        legacy = contact_address.parse(parse_text, про_адрес=asked_address)
        if explicit and address.get("settlement"):
            prior_quote = evidence.get("address.settlement", {}).get("quote", "")
            if re.search(r"\b(?:ул\.?|улица)\s*" + re.escape(explicit["street"]), prior_quote, re.IGNORECASE):
                # The previous partial street was mistaken for a settlement.
                # An explicit full street of the same name resolves that parse,
                # not an unrelated or genuinely changed locality.
                address.pop("settlement", None)
                evidence.pop("address.settlement", None)
        # In "Дубрава3, д. 39" the explicit house is 39. Retain the
        # numbered place literally, without inventing its administrative type.
        parsed = (contact_address.Found(street=numbered_place["place"].strip(), house=numbered_place["house"], raw=numbered_place[0], start=numbered_place.start(), end=numbered_place.end(), level="A", parts=contact_address.parts_only(parse_text[numbered_place.end():]), settlement=legacy.settlement if legacy and numbered_place.re is _MID_NUMBERED_PLACE else None, locality=legacy.locality if legacy and numbered_place.re is _MID_NUMBERED_PLACE else None) if numbered_place else
                  contact_address.Found(street=explicit["street"], house=explicit["house"], raw=explicit[0], start=explicit.start(), end=explicit.end(), level="A", parts=contact_address.parts_only(parse_text)) if explicit else None)
        if numbered_place and parsed and not parsed.parts.get('office'):
            # The explicit numbered-place head overrides the legacy parser
            # to protect its house. Read its inline comma-flat with the same
            # grammar instead of losing it while copying only labelled parts.
            unit = contact_address.comma_unit(parse_text[parsed.end:])
            if unit:
                parsed.parts['office'] = unit['kv2']
                parsed.end += unit.end()
                parsed.raw = parse_text[parsed.start:parsed.end]
        parsed = (parsed or legacy
                  or contact_address.parse_by_city(parse_text, known.get("city"), про_адрес=asked_address)
                  or contact_address.parse_place(parse_text))
        numbered_snt = _SNT_NUMBERED_STREET.search(parse_text)
        if numbered_snt:
            parsed = contact_address.Found(street=numbered_snt['street'], house=numbered_snt['house'],
                settlement=numbered_snt['place'], raw=numbered_snt[0], start=0, end=numbered_snt.end(), level='A',
                parts=contact_address.parts_only(parse_text))
        if parsed and parsed.street:
            pair = re.search(re.escape(parsed.street) + r'\s*,?\s*(?:д(?:ом)?\.?\s*)?(?P<lo>[1-9]\d{0,3})\s*[-–—]\s*(?P<hi>[1-9]\d{0,3})(?![\d/-])', parse_text, re.IGNORECASE)
            if (pair and (_TYPED_STREET.search(pair[0]) or re.search(r'\bдом\b|\bд\.', pair[0], re.IGNORECASE))
                    and 0 < int(pair['hi']) - int(pair['lo']) <= 2):
                parts = dict(parsed.parts or {})
                after = contact_address.parts_only(parse_text[pair.end():])
                if parts.get('office') == pair['hi'] and not after.get('office'):
                    parts.pop('office', None)
                parts.update(after)
                parsed = replace(parsed, house=pair['lo'] + '-' + pair['hi'], parts=parts, end=pair.end())
        if parsed and str(getattr(parsed, 'settlement_type', '') or '').casefold() == 'жк':
            notes.append(dict(message_id=mid, quote=text[:500]))
            parsed = replace(parsed, settlement=None, settlement_type=None)
        # The legacy matcher lets whitespace cross a newline and can absorb
        # the preceding prose, e.g. "Спасибо за понимание\nЛенина 55".
        # Prefer the same house on its own line; never choose among houses.
        if parsed and '\n' in (parsed.raw or ''):
            line_candidates = [(line, contact_address.parse(line, про_адрес=asked_address)) for line in parse_text.splitlines()]
            matching = [(line, p) for line, p in line_candidates if p and p.house == parsed.house]
            if len(matching) == 1:
                _, candidate = matching[0]
                parsed = replace(parsed, street=candidate.street)
        parsed = _split_named_city_before_street(parsed)
        if _non_address_candidate(parsed, parse_text):
            rejected.append({"message_id": mid, "quote": text[:500], "reason": "task_version_or_venue_is_not_a_street"})
            parsed = None
        role = _address_reference_role(messages, index, text, parsed, address_references, address)
        if role:
            reference = dict(role=role, message_id=mid, quote=text[:700],
                             address=dict(street=parsed.street, building=parsed.house, **(parsed.parts or {})),
                             worksite_verified=False)
            address_references.append(reference)
            if (_same_street(address.get('street', ''), parsed.street) and address.get('building') == parsed.house
                    and evidence.get('address.building', {}).get('message_id') == 'client-card'):
                for key in ('street', 'building', 'office', 'entrance', 'floor', 'intercom', 'city', 'area'):
                    address.pop(key, None)
                    evidence.pop('address.' + key, None)
            intercom_present, intercom_working, call_before_visit = prior_access
            for key in ('intercom_present', 'intercom_working', 'call_before_visit'):
                evidence.pop(key, None)
            evidence.update(prior_access_evidence)
            asked_address, last_out = False, ''
            continue  # A reference cannot set the worksite's flat/entrance/code.
        withdrawal = _literal_address_addition_withdrawal(message, parsed, text, notes) if parse_text == text else None
        if withdrawal:
            withdrawn_ids = withdrawal['withdrawn_source_message_ids']
            notes = [n for n in notes if not (n.get('kind') == 'literal_address_addition'
                     and n['message_id'] in withdrawn_ids)]
            notes.append(withdrawal)
        addition = _literal_address_addition(message, parsed, text) if parse_text == text else None
        if addition and not any(n.get('message_id') == mid and n.get('quote') == addition['quote'] for n in notes):
            notes = [n for n in notes if not (n.get('kind') == 'literal_address_addition_withdrawal'
                     and n.get('withdrawn_quote', '').casefold().replace('ё', 'е') == addition['quote'].casefold().replace('ё', 'е'))]
            notes.append(addition)
        if _VENUE_LOCATION.search(text) and _VENUE.search(text):
            notes.append({"message_id": mid, "quote": text[:500]})
        elif (_ENTRANCE_LANDMARK.search(text) or _ACCESS_NOTE.search(text) or _PHONE_AFTER_ACCESS.search(text)) and (parsed or address):
            notes.append({"message_id": mid, "quote": text[:500]})
        if (_APPROACH_LANDMARK.search(text)
                and message.get('sender_type') not in ('bot', 'system', 'operator', 'assistant')):
            # An approach cue may precede the address. Quote it as a landmark;
            # it does not establish the actual village or neighbourhood.
            notes.append({'message_id': mid, 'quote': text[:500]})
        if (parsed or address) and _PARENTHETICAL_PLACE.search(text):
            # Retain the client's exact location qualifier; a parenthesis does
            # not establish whether it is a village, district or neighbourhood.
            notes.append({'message_id': mid, 'quote': text[:500]})
        if (parsed or address) and (edge := _EDGE_ENTRANCE.search(text)):
            notes.append({'message_id': mid, 'quote': edge[0]})
        if (parsed or address) and _ACCESS_LANDMARK.search(text):
            notes.append({'message_id': mid, 'quote': text[:500]})
        if ((parsed or address) and re.search(r'напишите',text,re.I)
                and re.search(r'подойд[её]те|подъед[еи]те|приед[еи]те',text,re.I)):
            notes.append(dict(message_id=mid,quote=text[:500],kind='arrival_message_request'))
        updates = {}
        if parsed:
            updates = {"street": parsed.street, "building": parsed.house,
                       "settlement": parsed.settlement or "", "city": parsed.locality or ""}
            if parsed.area and not parsed.street:
                updates["area"] = parsed.area
            updates.update(parsed.parts or {})
            typed_city = _TYPED_CITY_ADDRESS.search(parse_text)
            if typed_city and parsed.street and parsed.house:
                updates['city'] = typed_city[1].strip()
            # Incident1076888: preserve the client's untyped place suffix.
            # This observed name does not establish Tomsk (or any branch).
            place = re.search(r'\bюжные\s+ворота\b', parse_text[parsed.end:], re.IGNORECASE) if parsed.street and parsed.house else None
            if place and not updates.get('settlement'):
                updates['settlement'] = place[0]
                notes.append(dict(message_id=mid, quote=text[:500]))
        if (index and _incoming(messages[index-1])
                and re.search(r'\bв\s+(?:деревн\w*|сел[ео]|пос[её]лк\w*)\s+(?:рядом|недалеко|возле)\b', _text(messages[index-1]), re.IGNORECASE)
                and re.fullmatch(r'[А-ЯЁ][а-яё-]{2,35}(?:\s+[А-ЯЁ]?[а-яё-]{2,35})?[.!\s]*', text)
                and text.strip('.! ').lower() not in ('спасибо', 'завтра', 'сегодня', 'позже', 'потом')):
            updates['settlement'] = text.strip('.! ')
        house = contact_address.house_only(parse_text)
        if house and (address.get("street") or address.get("settlement") or address.get("area")):
            updates["building"] = house
        block = _HOUSE_BLOCK.search(parse_text)
        if block and updates.get('building') == block['house']:
            # A stated block is part of the destination. Keep its label;
            # neither a model nor a nearby map match may turn it into 5б/2.
            updates['building'] = block['house'] + ' блок ' + block['block']
            notes.append({'message_id': mid, 'quote': text[:500]})
        if address or updates:
            updates.update(contact_address.parts_only(parse_text))
            if room := _ROOM.search(parse_text):
                updates['office'] = room[1]
        choice = _UNIT_CHOICE_QUESTION.fullmatch(last_out.strip())
        house_unit_confirmed = bool(choice and re.fullmatch(r'(?:это\s+)?квартира[.!\s]*', text, re.IGNORECASE)
                                    and re.fullmatch(r'\d{1,4}/' + re.escape(choice[1]), address.get('building', '')))
        if house_unit_confirmed:
            updates.update(building=address['building'].split('/')[0], office=choice[1])
        updates = {k: v for k, v in updates.items() if v}
        for access in _WORD_ACCESS.finditer(text.lower().replace('ё', 'е')):
            updates['entrance' if access[1] == 'подъезд' else 'floor'] = _ACCESS_ORDINALS[access[2]]
        if _ONE_ENTRANCE.search(text):
            updates['entrance'] = '1'
        code = _INTERCOM_CODE.search(text) or _REVERSED_INTERCOM_CODE.search(text) or _DOOR_CODE.search(text) or _DIAL_INTERCOM_CODE.search(text)
        if not code and (address or updates) and re.search(r'подъезд|домофон|вход|двер',text+'\n'+last_out,re.I):
            for candidate in _PLAIN_ACCESS_CODE.finditer(text):
                clause = re.split(r'[.,;\n]',text[:candidate.start()])[-1][-60:]
                if not re.search(r'ошиб|телевиз|принтер|компьютер|скидк|активац|смс',clause,re.I):
                    code = candidate
                    break
        price = _INTERCOM_PRICE.search(text)
        if code and price and price.start() <= code.start() < price.end():
            code = None
        if not code and _INTERCOM_PRICE.search(text):
            # The legacy parts parser also accepts service prices after this
            # word. A currency amount cannot supply a customer's access code.
            updates.pop("intercom", None)
        if code and (address or updates):
            updates["intercom"] = re.sub(r"\s+", "", code[1])
            if code.re is _DOOR_CODE:
                access_clause = re.split(r'[.\n]', text[code.start():], maxsplit=1)[0][:200]
                notes.append({'message_id': mid, 'quote': access_clause})
            elif not intercom_status:
                if intercom_present is not True:
                    intercom_working = None
                    evidence.pop('intercom_working', None)
                intercom_present = True
                evidence['intercom_present'] = dict(message_id=mid, quote=code[0], kind='client_intercom_code')
        postfix_entrance = _POSTFIX_SHORT_ENTRANCE.search(text)
        if postfix_entrance and parsed and postfix_entrance.start() < parsed.end:
            postfix_entrance = None
        if (address or updates) and (entrance := (postfix_entrance or _ABBREV_ENTRANCE.search(text) or _REVERSED_ENTRANCE.search(text))):
            updates["entrance"] = entrance[1]
        if _same_street(address.get("street", ""), updates.get("street", "")):
            updates["street"] = address["street"]
        street_confirmation = _STREET_CONFIRMATION.fullmatch(last_out.strip())
        if street_confirmation and not re.match(r'^ул(?:ица)?\.?\s+', last_out, re.IGNORECASE):
            from contact_cities import city_by_name
            candidate = street_confirmation['street']
            previous_street = re.sub(r'^(?:ул\.?|улица)\s+', '', address.get('street', ''), flags=re.IGNORECASE).casefold().replace('ё', 'е')
            # An untyped name might be a person, not a street. Only expand a
            # bounded shared prefix of the client's actual street shorthand;
            # unrelated names need an explicit street label in the question.
            if (len(candidate) < 4 or ' ' in candidate or city_by_name(candidate, declined=True)
                    or len(previous_street) < 4 or not candidate.casefold().replace('ё', 'е').startswith(previous_street[:4])):
                street_confirmation = None
        confirmed_street = bool(address.get('street') and street_confirmation
            and not _NON_STREET_CONFIRMATION.search(street_confirmation['street'])
            and re.fullmatch(r'(?:да|верно|правильно|ага)[.!\s]*', text, re.IGNORECASE))
        if confirmed_street:
            updates['street'] = street_confirmation['street']
        changed = not house_unit_confirmed and not confirmed_street and any(address.get(k) and address[k] != updates[k] for k in ("street", "building", "settlement") if k in updates)
        if changed:
            uncertain_address_fields.clear()
            evidence.pop('address.confirmation', None)
            if not (_CORRECTION.search(text) or _FINAL_ADDRESS_QUESTION.search(last_out)):
                conflicts.append({"kind": "address_changed", "message_id": mid})
            else:
                conflicts.clear()
            # An apartment/access code from the previous address cannot carry over.
            for key in ("office", "entrance", "floor", "intercom"):
                address.pop(key, None)
                evidence.pop("address." + key, None)
            if evidence.get('intercom_present', {}).get('message_id') != mid:
                intercom_present, intercom_working = None, None
                evidence.pop('intercom_present', None)
                evidence.pop('intercom_working', None)
            elif evidence.get('intercom_working', {}).get('message_id') != mid:
                intercom_working = None
                evidence.pop('intercom_working', None)
            notes = [n for n in notes if n["message_id"] == mid]
            ambiguities.clear()
        if _PRIVATE_HOUSE.search(text) and (address or updates):
            unit = updates.get("office") or address.get("office")
            if unit and unit != "ЧД":
                # Check after clearing the old address's access details: its
                # apartment must not affect a different private house.
                conflicts.append({"kind": "private_house_with_unit", "message_id": mid})
            else:
                updates["office"] = "ЧД"
        elif address.get("office") == "ЧД" and updates.get("office") and updates["office"] != "ЧД":
            conflicts.append({"kind": "private_house_with_unit", "message_id": mid})
        if _FINAL_ADDRESS_QUESTION.search(last_out) and parsed and parsed.street and parsed.house:
            conflicts.clear()
        if parsed and (unit := _UNLABELLED_UNIT.search(parse_text[parsed.end:])) and not updates.get("office"):
            ambiguities = [{"kind": "unlabelled_office", "value": unit[1], "message_id": mid, "quote": text[:500]}]
        contextual_unit = None
        if (parsed and not updates.get('office') and re.search(r'квартир|офис', last_out, re.I)
                and (contextual_unit := re.match(r'\s*,\s*(\d{1,4})(?!\d)(?=\s*(?:[.;]|$))', parse_text[parsed.end:]))):
            updates['office'] = contextual_unit[1]
        if parsed and parsed.street and parsed.house and not updates.get('office'):
            # A hyphen may separate house and flat, but cannot prove the unit.
            # Preserve the candidate and ask, rather than learning a later CRM
            # edit as if the client had explicitly labelled it in this prefix.
            unit = re.match(r'\s*-\s*(\d{1,4})(?!\d)(?=\s*(?:$|\n|[,.;]))', parse_text[parsed.end:])
            if unit:
                ambiguities = [{'kind': 'unlabelled_office', 'value': unit[1], 'message_id': mid, 'quote': text[:500]}]
        if updates.get("office"):
            ambiguities.clear()
        for key, value in updates.items():
            uncertain_address_fields = [u for u in uncertain_address_fields if u['field'] != key]
            address[key] = value
            evidence["address." + key] = {"message_id": mid, "quote": text[:500]}
            if house_unit_confirmed and key in ('building', 'office'):
                evidence['address.' + key]['confirmation_question'] = last_out
            if confirmed_street and key == 'street':
                evidence['address.street']['confirmation_question'] = last_out
            if contextual_unit and key == 'office':
                evidence['address.office']['confirmation_question'] = last_out
        entrance_doubt = any(re.search(r'подъезд\w*[^.!?\n]{0,45}(?:могл[аи]?\s+(?:наврать|ошибиться)|не\s+помню|не\s+уверен\w*)|'
                                      r'(?:не\s+помню|не\s+уверен\w*)[^.!?\n]{0,30}подъезд',clause,re.I)
                             for clause in re.split(r'[.,;\n]+',text))
        if entrance_doubt and address:
            previous_value = address.pop('entrance', '')
            previous_evidence = evidence.pop('address.entrance', {})
            uncertain_address_fields = [u for u in uncertain_address_fields if u['field'] != 'entrance']
            uncertain_address_fields.append(dict(field='entrance',previous_value=previous_value,
                previous_message_id=previous_evidence.get('message_id',''),message_id=mid,quote=text[:500],
                verified=False,source='client_message'))
            notes.append(dict(message_id=mid,quote=text[:500],kind='uncertain_entrance'))
        asked_address = False
        last_out = ""
    if intercom_present is False and evidence.get('address.intercom', {}).get('message_id') == 'client-card':
        address.pop('intercom', None)
        evidence.pop('address.intercom', None)
    values = list(dict.fromkeys(p["value"] for p in phones))
    if preferred:
        selected = next(p for p in reversed(phones) if p["value"] == preferred)
        evidence["contact_phone_to_use"] = {"message_id": selected["message_id"], "quote": selected["raw"]}
        if selected.get('signature'):
            evidence['contact_phone_to_use'].update(source=selected['source'], signature=selected['signature'],
                                                   context_message_id=selected['context_message_id'])
        elif selected.get('source') in ('client_phone_fragments', 'client_landline_parts'):
            evidence['contact_phone_to_use'].update(source=selected['source'],
                fragment_message_ids=selected['fragment_message_ids'], context_message_id=selected['context_message_id'])
    confirmed = known.get("card_address") or {}
    if confirmed and all(address.get(k) == confirmed.get(k) for k in ("street", "building", "settlement")):
        conflicts.clear()
    reference_pending = bool(address_references and not address.get('building'))
    facts = {"phones": phones, "phone_values": values, "contact_phone_to_use": preferred,
            "phone_needs_confirmation": needs_phone_confirmation, "address": address,
            "address_needs_confirmation": bool(conflicts or ambiguities or reference_pending), "evidence": evidence, "conflicts": conflicts,
            "address_ambiguities": ambiguities, "address_notes": notes, "rejected_address_candidates": rejected,
            "address_references": address_references, "worksite_address_pending": reference_pending,
            "uncertain_address_fields": uncertain_address_fields,
            "phone_selection": phone_selection}
    facts["call_before_visit"] = call_before_visit
    facts['call_timing'] = 'upon_arrival' if call_before_visit and _arrival_call_requested(evidence.get('call_before_visit',{}).get('quote','')) else 'before_visit' if call_before_visit else 'not_stated'
    facts['required_crew_count'] = required_crew_count
    facts['required_crew_status'] = 'requested_unconfirmed' if required_crew_count else 'not_stated'
    facts['intercom_working'] = intercom_working
    facts['intercom_present'] = intercom_present
    facts['staff_introduction'] = staff_introduction(messages)
    facts['stated_place'] = residence_place(messages)
    import assistant_prices
    current_intents = assistant_prices.current_enquiry_messages(messages)
    facts['work_destination_hint'] = service_destination_hint(current_intents, address, evidence)
    facts['passenger_pickup_request'] = passenger_pickup_request(current_intents)
    facts['client_call_permission'] = client_call_permission(current_intents)
    facts['untyped_place_candidate'] = untyped_place_candidate(messages,known,address)
    import assistant_qualifiers
    facts['client_location'] = assistant_qualifiers.client_location(messages, known, facts)
    import assistant_prices
    facts['budget_limit'] = assistant_prices.consent(messages).get('budget_limit', {})
    import personal_media
    current_image_ids = {m.get('id') for m in personal_media.current_tv_screen_crack_images(current_intents)}
    facts['image_observations'] = [dict(m['media_observation']) for m in messages if m.get('direction')=='in' and m.get('media_reviewed') and m.get('media_observation',{}).get('source') in ('reviewed_image','offline_reviewed_image')
        and (m.get('media_observation',{}).get('visible_symptom') != 'screen_cracks'
             or m.get('id') in current_image_ids and personal_media.reviewed_tv_screen_cracks(m))]
    facts['current_enquiry_scope'] = assistant_prices.current_enquiry_scope(messages)
    facts['graphics_scope'] = graphics_device_scope(assistant_prices.current_enquiry_messages(messages))
    facts['standalone_printer_diagnostic'] = standalone_printer_diagnostic(assistant_prices.current_enquiry_messages(messages))
    facts['standalone_diagnostic'] = standalone_diagnostic(assistant_prices.current_enquiry_messages(messages))
    facts['active_service_scope'] = active_furniture_scope(assistant_prices.current_enquiry_messages(messages))
    facts['work_placement_answers'] = work_placement_answers(messages)
    facts['work_location_references'] = work_location_references(messages)
    facts['furniture_transport_operations'] = furniture_transport_operations(messages)
    facts['client_background_work'] = client_background_work(assistant_prices.current_enquiry_messages(messages))
    router_only = None
    enquiry = assistant_prices.current_enquiry_messages(messages)
    router_context = '\n'.join(_text(m) for m in enquiry if _incoming(m))
    if re.search(r'роутер|router', router_context, re.I) and not re.search(r'телевиз|ноутбук|компьютер|приставк', router_context, re.I):
        for m in enquiry:
            if not _incoming(m):
                continue
            body = _text(m)
            if re.search(r'без\s+прошивки|не\s+(?:нужно|надо)\s+(?:прошивать|прошить)', body, re.I):
                router_only = dict(message_id=m.get('id', ''), quote=body, source='client_message')
            elif re.search(r'прошив|прошить|перепрош', body, re.I):
                router_only = None
    facts['router_configuration_only'] = router_only
    facts['furniture_manufacture'] = furniture_manufacture(assistant_prices.current_enquiry_messages(messages))
    clog_messages = assistant_prices.current_enquiry_messages(messages)
    clog_context = clog_work_context(clog_messages)
    facts['confirmed_clog'] = confirmed_clog(clog_messages, clog_context)
    if clog_context['uncertain_reports'] or clog_context['excluded_reports']:
        facts['clog_work_context'] = clog_context
    facts['confirmed_furniture_completion'] = confirmed_furniture_completion(assistant_prices.current_enquiry_messages(messages))
    facts['business_payment'] = business_payment(assistant_prices.current_enquiry_messages(messages))
    facts['business_customer'] = business_customer(assistant_prices.current_enquiry_messages(messages))
    facts['requested_visit'] = requested_visit(assistant_prices.current_enquiry_messages(messages))
    facts['budget_ambiguity'] = assistant_prices.consent(messages).get('budget_ambiguity', {})
    # Retain a written local constraint as a quote, not as a legal rule or an
    # appointment confirmation. Staff assumptions cannot supply it.
    facts['visit_constraints'] = [
        dict(message_id=m.get('id', ''), quote=match[0], source='client_message')
        for m in assistant_prices.current_enquiry_messages(messages)
        if _incoming(m) and m.get('sender_type') not in ('bot', 'system', 'operator', 'assistant', 'avito')
        and m.get('role') != 'assistant'
        for match in _QUIET_PERIOD.finditer(_text(m))]
    facts['task_notes'] = [
        dict(message_id=m.get('id',''),quote=_text(m)[:700],source='client_message')
        for m in messages if _incoming(m)
        and re.search(r'шкаф|комод|кроват|мебел|ящик',_text(m),re.I)
        and re.search(r'отверсти|дырк|креплен|петл|саморез',_text(m),re.I)
        and re.search(r'разбит|испорч|вырва|слом|не\s+держ|заполн|задел|оторва|отвал',_text(m),re.I)]
    # Narrowing a mixed job to bed repair must retain the already written
    # damaged parts. Quote the client, without adopting an ASR diagnosis or
    # restoring furniture moving/disassembly that was not accepted.
    scope = facts['active_service_scope']
    if not scope or re.search(r'кроват', scope['quote'], re.I):
        for m in assistant_prices.current_enquiry_messages(messages):
            if (not _incoming(m) or m.get('sender_type') in ('bot','system','operator','assistant','avito')
                    or m.get('role') == 'assistant'):
                continue
            written = str(m.get('written_body') if 'written_body' in m else
                          '' if m.get('voice_transcript') else _text(m))
            if (not re.search(r'кроват', written, re.I)
                    or not re.search(r'боков\w*\s+доск|царг|ножк|каркас', written, re.I)
                    or not re.search(r'слом|лопнул|треснул|отвал|оторва|надлом|пролом|разбит|провал|вырва', written, re.I)):
                continue
            note = next((n for n in facts['task_notes'] if n['message_id'] == m.get('id','')), None)
            detail = dict(message_id=m.get('id',''),quote=written[:700],source='client_message',
                          kind='bed_part_damage',written=True)
            if note is None:
                facts['task_notes'].append(detail)
            else:
                note.update(detail)
    visual_devices = {o.get('device_kind') for o in facts['image_observations']}
    client_text = '\n'.join(_text(m) for m in messages if _incoming(m))
    scope_text = (facts.get('active_service_scope') or facts.get('current_enquiry_scope') or {}).get('text', router_context)
    facts['service_image_observations'], facts['excluded_visual_service_context'] = visual_work_context(
        scope_text, facts['image_observations'])
    stated_tv = bool(re.search(r'телевиз|\bтв\b', client_text, re.IGNORECASE))
    stated_pc = bool(re.search(r'монитор|монмтор|компьютер|ноутбук|\bпк\b', client_text, re.IGNORECASE))
    facts['visual_context_conflict'] = bool(('tv' in visual_devices and stated_pc and not stated_tv)
                                          or visual_devices & {'pc','monitor'} and stated_tv and not stated_pc)
    facts['fallback_phones'] = list({p['value']: p for p in fallbacks if p['value'] != preferred}.values())
    import qualification_state
    facts['client_age'] = qualification_state.client_age(messages)
    facts['adult_presence'] = qualification_state.adult_presence(messages, facts['client_age'])
    if known.get('direction') == 'kp':
        import assistant_catalog
        current = assistant_prices.current_enquiry_messages(messages)
        software_request = '\n'.join(_text(m) for m in current if _incoming(m))
        if (assistant_catalog.ordinary_windows_installation(software_request)
                or assistant_catalog.ordinary_office_installation(software_request)):
            preservation = qualification_state.inspect(current)['keep_data']
            source = next((m for m in current if m.get('id') == preservation.get('message_id')), None)
            if (preservation['status'] == 'answered' and preservation.get('quote') and source
                    and _incoming(source) and source.get('sender_type') not in ('bot','system','operator','assistant','avito')
                    and source.get('role') != 'assistant'):
                # Retain the literal client statement/question, not an
                # inferred promise that files have been or will be saved.
                question = next((m for m in current if m.get('id') == preservation.get('question_message_id')), {})
                facts['data_preservation_context'] = dict(message_id=preservation['message_id'],
                    quote=preservation['quote'], question_quote=preservation.get('question_quote') or _text(question),
                    source='client_message', execution_confirmed=False)
    if known.get('direction') == 'mnc':
        import qualification_state
        state = qualification_state.inspect(messages)
        material = state['materials']
        if material['status'] == 'answered' and material.get('quote') and material.get('message_id'):
            question = next((m.get('body', '') for m in messages
                             if m.get('id') == material.get('question_message_id')), '')
            facts['material_availability'] = dict(value=material['value'], message_id=material['message_id'],
                question_message_id=material.get('question_message_id', ''), quote=material['quote'],
                question_quote=material.get('question_quote') or question[:300],
                scope=material.get('availability_scope') or ('named_item' if material.get('availability_subject') else 'client_statement'),
                subject=material.get('availability_subject', ''), source='client_message')
        if state['lock_work']['status'] == 'answered':
            facts['lock_work_choice'] = dict(state['lock_work'], source='client_message')
    if known.get('direction') == 'mnc':
        import assistant_catalog
        client = '\n'.join(_text(m) for m in messages if _incoming(m))
        optional = assistant_catalog.mixed_optional_scope(messages, known, intent_text(client, facts))
        if optional:
            facts['mixed_optional_work'] = optional
    instruction = service_contact_instruction(facts, messages)
    if instruction:
        facts['service_comment_instruction'] = instruction
    facts["comment_lines"] = crm_comment_lines(facts)
    return facts


def redact_for_model(messages, facts):
    """Keep dialogue structure while replacing contact spans with stable markers."""
    result = []
    quotes = sorted({e["quote"] for k, e in facts["evidence"].items()
                     if k.startswith("address.") and e.get("quote")}, key=len, reverse=True)
    for message in messages:
        text = _text(message)
        for quote in quotes:
            text = text.replace(quote, "[АДРЕС ПОЛУЧЕН]")
        for phone in reversed(contact_phone.find_all(text)):
            text = text[:phone.start] + "[ТЕЛЕФОН ПОЛУЧЕН]" + text[phone.end:]
        result.append({"role": "client" if _incoming(message) else "bot", "text": text,
                       "свой": str(message.get("sender_type") or message.get("by") or "") == "bot"})
    return result
