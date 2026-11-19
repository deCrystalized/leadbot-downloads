"""Synthetic cross-contract checks; no imported TestCase aliases or real data."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import qualification_state as qs
import assistant_policy as policy
import assistant_prices as prices
import extension_assistant as ext
from assistant_store import Store

CASES = [{'id': 'C01', 'ctx': {'convId': 'synthetic-combined125-C01', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C01-0', 'direction': 'in', 'sender_type': 'client', 'body': 'В принтере Epson L366 засохли чернила. Работа в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'dry_ink', 'room': 'кухн', 'model': 'answered', 'problem': 'answered'}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C02', 'ctx': {'convId': 'synthetic-combined125-C02', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C02-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Здравствуйте, Нужно снять верхнюю крышку автоподачи на МФУ Pantum BF5100ADW, сохранив стекло сканера. Работа в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'adf_cover', 'room': 'кухн', 'model': 'answered', 'problem': 'answered', 'exact_printer_span': True}, 'native': True, 'negative': ['Стекло точно останется целым.', 'unconfirmed_printer_operation_outcome'], 'synthetic': True}, {'id': 'C03', 'ctx': {'convId': 'synthetic-combined125-C03', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C03-0', 'direction': 'in', 'sender_type': 'client', 'body': 'В принтере Epson L366 засохли чернила. Не на кухне, а в ванной.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'dry_ink', 'room': 'ванн', 'room_not': 'кухн', 'problem': 'answered'}, 'native': True, 'negative': ['Нужно заменить картридж.', 'unrequested_printer_component_job'], 'synthetic': True}, {'id': 'C04', 'ctx': {'convId': 'synthetic-combined125-C04', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C04-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить шланг на подачу воды к смесителю в кухне. Шланг имеется.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'кухн', 'materials': 'answered', 'material_scope': 'client_named_item_only', 'volume': 'answered', 'volume_scope': 'client_named_hose_only', 'no_repeated_known': True}, 'native': True, 'negative': ['Привезу все детали.', 'unconfirmed_materials_promise'], 'synthetic': True}, {'id': 'C05', 'ctx': {'convId': 'synthetic-combined125-C05', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C05-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить 2 шланга в ванной. Шланги имеются.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'ванн', 'materials': 'answered', 'material_scope': 'client_named_item_only', 'volume': 'answered', 'volume_contains': '2 шланга', 'no_repeated_known': True}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C06', 'ctx': {'convId': 'synthetic-combined125-C06', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C06-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить несколько шлангов в кухне. Шланг имеется.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'кухн', 'materials': 'answered', 'volume': 'missing'}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C07', 'ctx': {'convId': 'synthetic-combined125-C07', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C07-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить шланг. Не на кухне, а в ванной. Шланга нет.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'ванн', 'room_not': 'кухн', 'materials': 'answered', 'material_contains': 'нет', 'material_scope': 'client_named_item_only', 'volume': 'answered'}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C08', 'ctx': {'convId': 'synthetic-combined125-C08', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C08-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить шланг к смесителю. На кухне или в ванной — пока не решили.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room_status': 'missing', 'volume': 'answered', 'native_question': 'Работа нужна на кухне или в ванной?'}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C09', 'ctx': {'convId': 'synthetic-combined125-C09', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C09-0', 'direction': 'out', 'sender_type': 'operator', 'body': 'Работа в кухне. Шланг имеется. Нужно снять крышку автоподачи МФУ.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C09-1', 'direction': 'in', 'sender_type': 'client', 'body': 'Здравствуйте', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'room_status': 'missing', 'materials': 'missing', 'volume': 'missing'}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C10', 'ctx': {'convId': 'synthetic-combined125-C10', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C10-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Если решим делать в кухне и если шланг имеется, напишу. Если нужно заменить шланг, скажу.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'room_status': 'missing', 'materials': 'missing', 'volume': 'missing'}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C11', 'ctx': {'convId': 'synthetic-combined125-C11', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C11-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Мастер написал: «В принтере засохла краска». Сосед сказал: «В кухне, шланг имеется. Нужно заменить шланг». Мне нужно подключить принтер к ПК.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'room_status': 'missing', 'materials': 'missing', 'volume': 'missing'}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C12', 'ctx': {'convId': 'synthetic-combined125-C12', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C12-0', 'direction': 'in', 'sender_type': 'client', 'body': 'В принтере Epson L366 засохли чернила.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C12-1', 'direction': 'out', 'sender_type': 'operator', 'body': 'Обсудили прошлую проблему.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C12-2', 'direction': 'in', 'sender_type': 'client', 'body': 'Новая заявка: другой принтер HP LaserJet 1020 не включается.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'problem': 'answered', 'problem_id': 'C12-2', 'model': 'answered'}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C13', 'ctx': {'convId': 'synthetic-combined125-C13', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C13-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно снять верхнюю крышку автоподачи на МФУ Pantum BF5100ADW, сохранив стекло сканера.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C13-1', 'direction': 'out', 'sender_type': 'operator', 'body': 'от 500 рублей услуга', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C13-2', 'direction': 'in', 'sender_type': 'client', 'body': 'Новая заявка: нужно заменить шланг в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'room': 'кухн', 'volume': 'answered', 'prior_verified': False}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C14', 'ctx': {'convId': 'synthetic-combined125-C14', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C14-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить шланг в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C14-1', 'direction': 'out', 'sender_type': 'operator', 'body': 'от 800 рублей услуга.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C14-2', 'direction': 'in', 'sender_type': 'client', 'body': 'Новая заявка: Нужно снять верхнюю крышку автоподачи на МФУ Pantum BF5100ADW, сохранив стекло сканера.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'adf_cover', 'prior_verified': False}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C15', 'ctx': {'convId': 'synthetic-combined125-C15', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C15-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно заменить шланг к смесителю в кухне. Шланг имеется.', 'created_at': '2026-09-12T23:06:59+00:00'}, {'id': 'C15-1', 'direction': 'in', 'sender_type': 'client', 'body': '79990000001. Перезвоните через полчаса', 'created_at': '2026-09-12T23:06:59+00:00'}]}, 'expected': {'printer': None, 'room': 'кухн', 'materials': 'answered', 'material_scope': 'client_named_item_only', 'volume': 'answered', 'callback': True}, 'native': True, 'negative': ['Мастер уже выехал и точно позвонит через полчаса.', 'unconfirmed_action_or_visit'], 'synthetic': True}, {'id': 'C16', 'ctx': {'convId': 'synthetic-combined125-C16', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C16-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужна только диагностика принтера HP Deskjet 6075 без ремонта в кухне. Сколько стоит?', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'кухн', 'diagnostic500': True}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C17', 'ctx': {'convId': 'synthetic-combined125-C17', 'city': 'Нефтеюганск', 'dir': 'mnc', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Услуги сантехника', 'messages': [{'id': 'C17-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужна только диагностика смесителя в кухне без ремонта. Шланг имеется. Сколько стоит?', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'room': 'кухн', 'materials': 'answered', 'material_scope': 'client_named_item_only', 'volume': 'missing', 'mnc_free_callout': True}, 'native': True, 'negative': None, 'synthetic': True}, {'id': 'C18', 'ctx': {'convId': 'synthetic-combined125-C18', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C18-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно снять верхнюю крышку автоподачи на МФУ Pantum BF5100ADW, сохранив стекло сканера. Работа в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C18-1', 'direction': 'out', 'sender_type': 'operator', 'body': 'от 500 рублей за метр.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}, {'id': 'C18-2', 'direction': 'in', 'sender_type': 'client', 'body': 'Хорошо.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'adf_cover', 'room': 'кухн', 'prior_verified': False}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C19', 'ctx': {'convId': 'synthetic-combined125-C19', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C19-0', 'direction': 'in', 'sender_type': 'client', 'body': 'Нужно снять фото принтера. Работа нужна в кухне.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': None, 'room': 'кухн'}, 'native': False, 'negative': None, 'synthetic': True}, {'id': 'C20', 'ctx': {'convId': 'synthetic-combined125-C20', 'city': 'Нижний Новгород', 'dir': 'kp', 'channel': 'avito', 'partner': '7', 'accountTitle': 'Учебный мастер', 'origin': 'С1', 'itemTitle': 'Ремонт принтеров', 'messages': [{'id': 'C20-0', 'direction': 'in', 'sender_type': 'client', 'body': 'В принтере Epson L366 засохли чернила. Шланг имеется.', 'created_at': '2026-09-12T23:06:59+00:00', 'delivery_status': 'delivered'}]}, 'expected': {'printer': 'dry_ink', 'materials': 'answered', 'material_scope': 'client_named_item_only', 'not_printer_inventory': True}, 'native': False, 'negative': None, 'synthetic': True}]

class CombinedKnownFactsPrinterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='combined125-owner',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.app=ext.Assistant(Store(temp.name+'/db'))

    def native(self,ctx,suffix,claim=None,bad_source=False):
        ctx=copy.deepcopy(ctx);ctx['convId']+='-'+suffix
        out,status=self.app.handle(dict(owner='combined125-owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled'])
        self.assertTrue(out.get('pending_model'),out.get('reason'))
        task=json.loads(out['model_task']['task'])
        candidate=dict(reply=task.get('fixed_reply') or task.get('proposed_reply') or task['decision']['next_question']['question'],needs_operator=False,
            context_review=dict(last_intent='Фактическая работа клиента и только сообщённые условия',latest_client_meaning='Последняя реплика прочитана вместе с клиентским контекстом',
              selected_step_fits=True,evidence_ids=[ctx['messages'][-1]['id']],note='Ручной synthetic review, не результат модели. Без обещания совместимости, всего запаса, результата, звонка или записи.'))
        if task.get('item_fitment_context'):
            candidate['context_review']['item_fitment_review'] = copy.deepcopy(task['item_fitment_context']['required_review'])
        if task.get('diagnostic_only_terms'):
            candidate['context_review']['diagnostic_only_review']=dict(minimum_rub=500,price_kind='minimum',repair_requested=False)
        if task.get('mnc_callout_terms'):
            candidate['context_review']['mnc_callout_review']=dict(callout_rub=0,diagnostic_fee_quoted=False,repair_included=False)
        if claim:candidate['reply']=claim+' '+candidate['reply']
        if bad_source:candidate['context_review']['evidence_ids']=['unobserved-staff-source']
        final,code=self.app.handle(dict(owner='combined125-owner',action='finalize',request_id=out['request_id'],revision=out['revision'],candidate=candidate))
        self.assertEqual(code,200);self.assertFalse(final['auto_enabled'])
        return dict(ctx=ctx,preview=out,task=task,candidate=candidate,final=final,model_calls=0,manual_synthetic_review=True)

    def check(self,spec):
        ctx=copy.deepcopy(spec['ctx']);expected=spec['expected'];messages=ctx['messages'];state=qs.inspect(messages)
        stated=qs.printer_stated_scope(messages)
        if 'printer' in expected:
            self.assertEqual(stated.get('kind') if stated else None,expected['printer'])
        for key in ['problem','model','materials','volume']:
            if key in expected:self.assertEqual(state[key]['status'],expected[key],key)
        if 'problem_id' in expected:self.assertEqual(state['problem']['message_id'],expected['problem_id'])
        if 'room_status' in expected:self.assertEqual(state['room']['status'],expected['room_status'])
        if 'room' in expected:
            self.assertEqual(state['room']['status'],'answered');self.assertIn(expected['room'],state['room']['value'])
            source=next(m for m in messages if m['id']==state['room']['message_id'])
            self.assertEqual(source['direction'],'in');self.assertEqual(state['room']['quote'],source['body'])
        if 'room_not' in expected:self.assertNotIn(expected['room_not'],state['room']['value'])
        if expected.get('material_scope'):
            self.assertEqual(state['materials']['availability_scope'],expected['material_scope'])
            self.assertNotIn('compatibility_confirmed',state['materials']);self.assertNotIn('all_parts_available',state['materials'])
        if 'material_contains' in expected:self.assertIn(expected['material_contains'],state['materials']['value'])
        if 'volume_scope' in expected:self.assertEqual(state['volume']['volume_scope'],expected['volume_scope'])
        if 'volume_contains' in expected:self.assertIn(expected['volume_contains'],state['volume']['value'])
        if stated:
            source=next(m for m in messages if m['id']==stated['message_id'])
            self.assertEqual(source['direction'],'in');self.assertEqual(stated['quote'],source['body'])
            match=qs.printer_problem_match(source['body']);self.assertEqual(source['body'][match.start():match.end()],match[0])
            self.assertEqual(state['problem']['value'],match[0])
        _,parsed,known,_=ext._parse(ctx)
        if 'prior_verified' in expected:
            self.assertEqual(prices.prior_quote_verified(parsed,known,prices.consent(parsed)),expected['prior_verified'])
        if expected.get('callback'):
            callback=policy._client_requested_callback(parsed);self.assertIsNotNone(callback)
            self.assertEqual(callback['after_minutes'],30);self.assertFalse(callback['visit_time_confirmed']);self.assertFalse(callback['execution_confirmed'])
        if expected.get('diagnostic500'):
            self.assertTrue(prices.diagnostic_only_applies(parsed))
            quote=prices.answer(parsed,known,'\n'.join(m['body'] for m in parsed if m['direction']=='in'))
            self.assertIn(500,quote['amounts']);self.assertIn('от 500',quote['reply'])
        if expected.get('mnc_free_callout'):
            self.assertTrue(prices.diagnostic_only_applies(parsed))
            quote=prices.answer(parsed,known,'\n'.join(m['body'] for m in parsed if m['direction']=='in'))
            self.assertEqual(quote['amounts'],[]);self.assertIn('Выезд в черте города бесплатный.',quote['reply'])
        result=dict(id=spec['id'],state=state,printer_scope=stated,model_calls=0,scope='synthetic cross-contract control')
        if spec['native']:
            native=self.native(ctx,'positive');final=native['final'];self.assertEqual(final['validation'],[])
            self.assertTrue(final['reply']);self.assertFalse(final['needs_operator']);self.assertFalse(final['lead']['can_create_automatically'])
            if expected.get('no_repeated_known'):
                for phrase in ['кухне или в ванной','Материалы и комплектующие есть','Какой объём работ']:
                    self.assertNotIn(phrase,final['reply'])
            if expected.get('native_question'):
                self.assertEqual(native['task']['decision']['next_question']['question'],expected['native_question'])
            if expected.get('callback'):
                self.assertEqual(final['action'],'wait');self.assertEqual(final['crm_preparation']['mode'],'callback')
                self.assertFalse(final['crm_preparation']['ready']);self.assertFalse(final['crm_preparation']['visit_time_confirmed'])
            if expected.get('diagnostic500'):self.assertIn('от 500',final['reply'])
            result['native']=native
            if spec.get('negative'):
                claim,error=spec['negative'];bad=self.native(ctx,'negative',claim=claim)
                self.assertFalse(bad['final']['reply']);self.assertIn(error,bad['final']['validation']);result['negative']=bad
            if spec['id']=='C04':
                wrong=self.native(ctx,'wrong-source',bad_source=True)
                self.assertFalse(wrong['final']['reply']);self.assertTrue(wrong['final']['validation']);result['negative_source']=wrong
        target=os.environ.get('COMBINED125_CROSS_OUTPUT')
        if target:
            directory=Path(target);directory.mkdir(parents=True,exist_ok=True)
            (directory/(spec['id']+'.raw.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


def _case_test(spec):
    def test(self):self.check(spec)
    return test


for _spec in CASES:
    setattr(CombinedKnownFactsPrinterTests,'test_'+_spec['id'],_case_test(_spec))
del _spec

if __name__=='__main__':unittest.main()
