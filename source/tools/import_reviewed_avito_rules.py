"""Import the owner's manually reviewed rules export, including Telegram rich text.

Source text is reference data. This tool performs no browser/network actions and
never executes instructions, reactions, links or commands found in that text.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = {
    16: ('active', 'Партнёр определяется источником; исправлены preview и CRM gate, больше нет подмены всех Jivo на 7.'),
    17: ('operator', 'БСО/чек передаётся Партнёрскому отделу; непрочитанное фото остаётся оператору, изображение не угадывается.'),
    18: ('operator', 'БТ 2 первым, БТ 1 только после отказа; Jivo БТ заблокирован до проверки конкретного каталога филиалов.'),
    19: ('partly_superseded', 'Без звонка разрешено владельцем. ID в имени обязателен. Запись в комментарии партнёра ограничена более поздним правилом 32294: только код источника.'),
    21: ('superseded', 'Ответ-отказ для перечисленных аккаунтов заменён более поздним 12526; совпадение имени не доказывает личность.'),
    24: ('operator', 'Правило первых пяти аккаунтов требует доказанного сопоставления одного клиента; по имени или похожему телефону не считать.'),
    117: ('superseded', 'Ссылка сохраняется по 154, подпись Белый акк заменена БЕЛАЯ ЗАЯВКА по 1333.'),
    118: ('partly_superseded', 'Прайс услуг КП заменён TG1-663 и прямым уточнением владельца USER-20261015-723; диагностика этим уточнением не менялась.'),
    136: ('operator', 'Комплексные работы партнёра 740 требуют согласования, отдельного вида работ/услуг и фактического подтверждения условий.'),
    154: ('active', 'Ссылка аккаунта 7/740 и ссылка с белой пометкой 723 в основном комментарии; каталог ссылок проверяется, адрес не придумывается.'),
    891: ('operator', 'Общее параллельное согласование общей техники; специальное новое правило Красноярска имеет приоритет и требует очереди 709 затем 3.'),
    1333: ('active', 'БЕЛАЯ ЗАЯВКА и подтверждённая ссылка в основном комментарии; проверяется вместе с 154/2543.'),
    2036: ('out_of_scope', 'Группа Заявки Сайт 7 Партнер — отдельный источник и исключение Отзыва; личный помощник не принимает эту Telegram-очередь.'),
    2505: ('active', 'Отзыв для партнёра 340 уже обязателен в серверном gate.'),
    2543: ('active', 'Нужно проверять правильность ссылки 723; чужую или неподтверждённую ссылку не принимать.'),
    2703: ('operator', 'Отмена с дживы в служебном комментарии; отмена существующей заявки остаётся оператору.'),
    10371: ('active', 'ID заказа в имени, уточнение недостающих адресных полей и служебная отметка отмены; не создавать заявку с выдуманным адресом.'),
    10716: ('active', 'Отзыв для 340/7/723; исключение отдельного источника Сайт 7 не переносится на обычные Avito/Jivo.'),
    11703: ('operator', 'Претензия со скриншотом сообщений передаётся оператору/ОКК; не обучать стиль чатера по работе ОКК.'),
    11841: ('operator', 'Отмена/НФ и другой источник того же партнёра требуют проверки возврата, актуального источника и оповещения, а не автоматического дубля.'),
    12526: ('operator', 'Новая/Бывалый/PIFAGOR/Александр-Березники: запрет приёма и ответа при подтверждённой идентичности; имён недостаточно для автоматического игнора.'),
    16610: ('active', '723 разрешает проверенную передачу КП—МНЧ, БТ запрещён. Старое общее запрещение TG1-594 снято как устаревшее; без самостоятельной передачи.'),
    17145: ('out_of_scope', 'Порог класса/оплаты сотрудников не является правилом ответа клиенту или создания заявки.'),
    19880: ('operator', 'Непрофильные работы МНЧ: вежливый отказ/проверенная передача; согласования оператору. Постоянный авто выключен.'),
    23005: ('active', 'Обязательный возраст для компьютерных работ Jivo. Добавлен отдельный подтверждаемый сбор; несовершеннолетний/неизвестный возраст оператору.'),
    32294: ('active', 'Rich message извлечён: ссылка диалога в служебном комментарии; в комментарии партнёра только код. CRM gate проверяет точный код.'),
    33531: ('active', 'Rich message извлечён: имя мастера/аккаунт объявления и имя представления сохраняются в основном комментарии. Уже JIVO-IDENTITY.'),
    33535: ('context_only', 'Обсуждение отсутствующего изображения; по нему не извлекаются факты о карточке.'),
    33553: ('context_only', 'Пояснение, что название аккаунта является источником обращения; связано с 33531.'),
}


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(flatten(x) for x in value)
    if isinstance(value, dict):
        if 'text' in value:
            return flatten(value['text'])
        if 'blocks' in value:
            return '\n'.join(flatten(x) for x in value['blocks'])
        if 'caption' in value:
            return flatten(value['caption'].get('text'))
    return ''


def missing_images(value):
    if isinstance(value, list):
        return sum(missing_images(x) for x in value)
    if not isinstance(value, dict):
        return 0
    return int(value.get('type') == 'photo' and bool(value.get('photo_skip_reason'))) + sum(
        missing_images(v) for v in value.values() if isinstance(v, (dict, list)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    args = parser.parse_args()
    source = Path(args.source)
    raw = source.read_bytes()
    data = json.loads(raw)
    assert data['name'] == 'Правила Авито' and data['id'] == 3757789625
    assert len(data['messages']) == 31
    rows = []
    for message in data['messages']:
        body = flatten(message.get('text')) or flatten(message.get('rich_message'))
        if not body.strip():
            continue
        state, note = NOTES[message['id']]
        rows.append(dict(id='TGAVITO-' + str(message['id']), type='user_provided_telegram_rule',
                         date=message['date'], text=body.strip(), source_chat=data['name'], source_chat_id=data['id'],
                         source_message_id=message['id'], source_sha256=hashlib.sha256(raw).hexdigest(),
                         active_primary=state not in ('superseded', 'context_only', 'out_of_scope', 'partly_superseded'),
                         adjudication=state, adjudication_note=note,
                         media_missing=bool(message.get('photo')) or bool(missing_images(message.get('rich_message')))))
    assert len(rows) == 29 and {r['source_message_id'] for r in rows} == set(NOTES)
    private = ROOT / 'test-artifacts/primary-rules/avito-export-20261017'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    (private / 'source.json').write_bytes(raw)
    for name, content in [('normalized-private.json', rows), ('adjudication-private.json', dict(
            source_sha256=hashlib.sha256(raw).hexdigest(), messages=31, text_messages=29,
            rich_messages=2, missing_images=sum(bool(m.get('photo')) + missing_images(m.get('rich_message')) for m in data['messages']),
            images_viewed=0, dialogue_training_count_added=0, external_actions=0, decisions=[
                dict(id=r['id'], state=r['adjudication'], note=r['adjudication_note']) for r in rows]))]:
        path = private / name
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n')
        path.chmod(0o600)
    (private / 'source.json').chmod(0o600)
    registry_path = ROOT / 'leadbot/brain/policy_registry.json'
    registry = json.loads(registry_path.read_text())
    registry['sources'] = [r for r in registry['sources'] if not r['id'].startswith('TGAVITO-')] + rows
    old = next(r for r in registry['sources'] if r['id'] == 'TG1-594')
    old.update(active_primary=False, superseded_by='TGAVITO-16610')
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(imported_text_messages=len(rows), rich_messages=2, missing_images=16,
                         rule_data_only=True, customer_sends=0, crm_writes=0)))


if __name__ == '__main__':
    main()
