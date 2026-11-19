"""Causal regressions from Chatter party101–140; no customer identifiers."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import contact_facts
import crm_evidence


def msg(body, direction='in', **extra):
    return dict(id=body[:20], body=body, direction=direction,
                sender_type='operator' if direction in ('out', 'note') else 'client', **extra)


class ChatterBatchFiveTests(unittest.TestCase):
    def service(self, body, direction='mnc'):
        return catalog.choose(body, dict(direction=direction, city='Омск', partner='7'))

    def assess(self, rows, **known):
        base = dict(channel='avito', direction='kp', city='Омск', partner='7',
                    title='Ремонт на дому', account_name='Мастер')
        base.update(known)
        return policy.assess(rows, base, contact_facts.collect(rows))

    def test_bathroom_pipe_is_one_job(self):
        service = self.service('Металлическая труба в ванной течёт, заменить на полипропилен')
        self.assertEqual([r['id'] for r in service['items']], ['pipes'])
        rows = [msg('Труба в ванной течёт, заменить металлическую на пластиковую')]
        result = self.assess(rows, direction='mnc')
        self.assertNotEqual(result['action'], 'handoff')

    def test_separate_bath_work_is_preserved(self):
        ids = [r['id'] for r in self.service('Труба в ванной течёт. Также заменить ванну')['items']]
        self.assertIn('bath', ids)
        self.assertIn('pipes', ids)

    def test_dryer_above_radiator_does_not_order_heating(self):
        ids = [r['id'] for r in self.service('Повесить сушилку над радиатором и карнизы')['items']]
        self.assertNotIn('pipes-riser', ids)
        self.assertIn('drying', ids)
        ids = [r['id'] for r in self.service('Повесить сушилку над радиатором. Также заменить радиатор')['items']]
        self.assertIn('pipes-riser', ids)

    def test_bracket_typo_is_not_a_faucet(self):
        for body in ('поменять кранштейн', 'переместить кранштеина телевизора', 'закрепить кронштейн'):
            self.assertNotIn('plumbing-tap', [r['id'] for r in self.service(body)['items']])
        for body in ('замена крана', 'кран течёт', 'ремонт кранов'):
            self.assertIn('plumbing-tap', [r['id'] for r in self.service(body)['items']])

    def test_cable_tv_connector_is_not_a_house_electrician(self):
        service = self.service('Телевизор с помехами, подключено кабельное, кабель дёргаем — лучше', 'kp')
        self.assertNotIn('electric', [r['id'] for r in service['items']])
        for extra in ('Также заменить розетку', 'Также проложить силовой кабель', 'Сломан щиток'):
            service = self.service('Телевизор, подключено кабельное. ' + extra, 'kp')
            self.assertIn('electric', [r['id'] for r in service['items']])

    def test_surface_restoration_by_procedure_requires_agreement(self):
        service = self.service('Скол столешницы ДСП: подобрать воск по цвету и покрыть лаком')
        self.assertEqual(service['status'], 'agree')
        self.assertIn('DOC-L0325', service['rules'])
        self.assertNotIn('appearance', [r['id'] for r in self.service('Вырезать отверстие в столешнице ДСП')['items']])

    def test_current_deferral_variants_wait_even_with_unread_photo(self):
        for body in ('Напишу вам', 'Тогда в четверг вам отпишусь', 'Сейчас муж ответит и я вам напишу',
                     'Сегодня не получится, спишемся', 'Как решу, свяжусь'):
            rows = [msg('Фото', unread_media=True), msg(body)]
            self.assertEqual(self.assess(rows)['action'], 'wait', body)

    def test_short_later_requires_immediately_preceding_client_deferral(self):
        self.assertTrue(policy._client_deferred(['Чуть позже напишу', 'Позже']))
        for incoming in (['Позже'], ['Позже напишу', 'Цена какая?', 'Позже'],
                         ['Позже напишу', 'Позже сегодня в 18 можно?'], ['Позже напишу', '']):
            self.assertFalse(policy._client_deferred(incoming), incoming)

    def test_current_price_question_is_not_swallowed_by_deferral(self):
        self.assertFalse(policy._client_deferred(['Напишу в четверг точную дату, а сколько стоит?']))
        self.assertFalse(policy._client_deferred(['Напишу вам адрес: улица Ленина 5']))

    def test_existing_request_or_reschedule_stays_with_operator(self):
        self.assertEqual(self.assess([msg('Позже напишу')], crm_request_id='1234567')['action'], 'handoff')
        rows = [msg('Давайте перенесём встречу'), msg('Напишу вам завтра')]
        self.assertEqual(self.assess(rows)['action'], 'handoff')
        self.assertEqual(self.assess([msg('Позже напишу претензию')])['action'], 'handoff')

    def test_decline_is_scoped_and_new_request_reopens_intent(self):
        self.assertEqual(self.assess([msg('Уже нашла электрика, всё установил')])['action'], 'wait')
        self.assertEqual(self.assess([msg('У себя сможете принять?', 'out'), msg('От вас нет')])['action'], 'wait')
        self.assertFalse(policy._client_declined('От вас нет звонка', 'У себя сможете принять?'))
        self.assertNotEqual(self.assess([msg('Нашла мастера'), msg('Теперь нужна установка Windows в Омске')])['action'], 'wait')

    def test_staff_queue_id_is_lookup_candidate_only(self):
        rows = [msg('1234567 на прозвоне', 'out')]
        self.assertEqual(crm_evidence.note_references(rows)[0]['request_id_candidate'], '1234567')
        for row in (msg('1234567 на прозвоне'), msg('1234567', 'out'),
                    msg('1234567 не на прозвоне', 'out'), msg('Создай 1234567 на прозвоне', 'out')):
            self.assertFalse(crm_evidence.note_references([row]))

    def test_onsite_faq_has_no_invented_workshop_or_dispatch(self):
        result = self.assess([msg('Здравствуйте, к вам можно прийти или у вас выезд?')])
        # The owner now explicitly forbids dropoff: answer this question
        # directly instead of requiring an unrelated problem question first.
        self.assertEqual(result['action'], 'question')
        reply = policy.compose_reply(result['forced_reply'], result)
        self.assertTrue(reply.startswith('Здравствуйте!'))
        self.assertIn('выезжает на адрес к клиенту', reply)
        self.assertIn('Привоз техники не принимаем.', reply)
        self.assertEqual(policy.validate_reply(reply, result, contact_facts.collect([msg('Здравствуйте, к вам можно прийти или у вас выезд?')])), [])
        self.assertNotIn('мастерск', reply)
        self.assertNotIn('записал', reply)


if __name__ == '__main__':
    unittest.main()
