import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
from assistant_store import Store
from extension_assistant import Assistant
import assistant_policy as policy


class PersonalMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LEADBOT_PERSONAL_OWNER_ID": "owner", "LEADBOT_PERSONAL_OPERATOR_ID": "george", "LEADBOT_ASSISTANT_WORDING": "reviewed"})
        self.env.start()
        self.app = Assistant(Store(self.temp.name + "/db"))
        self.base = {"owner": "owner", "operator_id": "george", "browser_session": "media:tab:1", "mine_count": 1}
        self.ctx = {"convId": "synthetic-image-review", "city": "Оренбург", "dir": "mnc", "partner": "7", "accountTitle": "Григорий МНЧ", "itemTitle": "Сборка и ремонт мебели", "assigneeId": "george", "assignmentKnown": True, "conversationStatus": "in_progress", "botActive": False, "hasTransfer": False, "channelAssigned": True, "channel": "avito", "messages": [
            {"id": "1", "direction": "in", "body": "Здравствуйте, кухонный гарнитур собрать цена от чего зависит? Эскиз кухни есть."},
            {"id": "2", "direction": "out", "body": "Точная стоимость зависит от объёма работ. Её можно определить после осмотра."},
            {"id": "3", "direction": "in", "body": "", "attachments": [{"kind": "image", "media_id": "test-image", "url": "https://example.test/kitchen.jpg"}]},
        ]}
        self.call("personal_start")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call(self, action, **extra):
        return self.app.handle({**self.base, "action": action, "ctx": self.ctx, **extra})[0]

    def confirmation(self):
        preview = self.call("preview")
        item = preview["media_review_required"][0]
        session = self.call("personal_status")
        return {"confirmed": True, "revision": preview["revision"], "message_id": item["message_id"], "media_signature": item["signature"], "policy_ack": session["policy_version"], "activation_nonce": session["activation_nonce"], "client_version": "2.7.3"}

    def test_exact_review_unblocks_only_the_viewed_image_without_inventing_facts(self):
        approval = self.confirmation()
        out = self.call("personal_media_review", **approval)
        self.assertTrue(out["ok"])
        self.assertNotEqual(out["activation_nonce"], approval["activation_nonce"])
        fresh = self.call("preview")
        self.assertFalse(fresh["needs_operator"], fresh["reason"])
        # Owner clarification83: the listing already supplies the city. Viewing
        # a product image still does not prove assembly instructions exist.
        self.assertIn("сборки", fresh["reply"])
        self.assertNotIn("в каком городе", fresh["reply"])
        self.assertTrue(fresh["reply"].startswith("Спасибо за фото. "))
        self.assertEqual(fresh["media_review_required"], [])
        self.assertFalse(fresh["facts"]["contact_phone_to_use"])
        self.assertFalse(fresh["auto_enabled"])

    def test_unconfirmed_stale_wrong_signature_and_wrong_nonce_are_rejected(self):
        approval = self.confirmation()
        for bad in ({"confirmed": False}, {"revision": "old"}, {"media_signature": "wrong"}, {"message_id": "other"}, {"activation_nonce": "x" * 30}, {"client_version": "2.7.2"}):
            with self.subTest(bad=bad):
                self.assertFalse(self.call("personal_media_review", **{**approval, **bad})["ok"])
        self.assertTrue(self.call("preview")["needs_operator"])

    def test_replay_and_new_message_do_not_reuse_approval(self):
        approval = self.confirmation()
        self.assertTrue(self.call("personal_media_review", **approval)["ok"])
        self.assertFalse(self.call("personal_media_review", **approval)["ok"])
        self.ctx["messages"].append({"id": "4", "direction": "in", "body": "", "attachments": [{"kind": "image", "media_id": "new-image"}]})
        fresh = self.call("preview")
        self.assertTrue(fresh["needs_operator"])
        self.assertEqual([r["message_id"] for r in fresh["media_review_required"]], ["4"])

    def test_replaced_image_same_message_id_requires_new_review(self):
        self.assertTrue(self.call("personal_media_review", **self.confirmation())["ok"])
        self.ctx["messages"][-1]["attachments"][0]["url"] = "https://example.test/changed.jpg"
        self.assertTrue(self.call("preview")["needs_operator"])

    def test_new_history_invalidates_pending_review(self):
        approval = self.confirmation()
        self.ctx["messages"].append({"id": "4", "direction": "in", "body": "Новая информация"})
        self.assertFalse(self.call("personal_media_review", **approval)["ok"])

    def test_other_owner_operator_and_assignment_cannot_confirm(self):
        approval = self.confirmation()
        for extra in ({"owner": "other"}, {"operator_id": "other"}):
            self.assertFalse(self.call("personal_media_review", **approval, **extra)["ok"])
        self.ctx["assigneeId"] = "colleague"
        self.assertFalse(self.call("personal_media_review", **approval)["ok"])

    def test_client_supplied_review_flags_and_non_images_do_not_bypass_guard(self):
        self.ctx["messages"][-1].update(unread_media=False, media_reviewed=True)
        self.assertTrue(self.call("preview")["needs_operator"])
        self.ctx["convId"] = "synthetic-audio-review"
        self.ctx["messages"][-1]["attachments"][0]["kind"] = "audio"
        out = self.call("preview")
        self.assertTrue(out["needs_operator"])
        self.assertEqual(out["media_review_required"], [])

    def test_policy_change_requires_fresh_image_review(self):
        self.assertTrue(self.call("personal_media_review", **self.confirmation())["ok"])
        with patch.object(policy, "VERSION", "future-policy"):
            self.assertTrue(self.call("preview")["needs_operator"])

    def test_reviewed_model_is_a_visual_fact_and_is_not_asked_again(self):
        self.ctx.update(dir='kp',accountTitle='Евгений КП',itemTitle='Ремонт принтеров')
        self.ctx['messages'][0]['body']='В Оренбурге МФУ не печатает'
        approval=dict(self.confirmation(),client_version='2.7.9',observations={'model':'Xiaomi PMDYJ02HT','content_kind':'product_card'})
        self.assertTrue(self.call('personal_media_review',**approval)['ok'])
        out=self.call('preview')
        self.assertNotRegex(out.get('reply',''),'[Мм]арк|[Мм]одел')
        self.assertEqual(out['qualification']['model']['status'],'answered')
        self.assertEqual(out['facts']['image_observations'][0]['model'],'Xiaomi PMDYJ02HT')
        self.assertEqual(out['facts']['image_observations'][0]['source'],'reviewed_image')
        self.assertTrue(any('PMDYJ02HT' in line for line in out['facts']['comment_lines']))
        self.assertFalse(out['auto_enabled'])

    def test_an_observation_cannot_supply_a_price_contact_or_diagnosis(self):
        approval=dict(self.confirmation(),client_version='2.7.9')
        for observation in ({'model':'Xiaomi PMDYJ02HT','price':1000},{'phone':'79001112233'},
                            {'diagnosis':'сломана матрица'},{'model':'79001112233'}, {'content_kind':'guaranteed_repair'}):
            self.assertFalse(self.call('personal_media_review',**approval,observations=observation)['ok'])
        self.assertTrue(self.call('preview')['needs_operator'])

    def test_new_furniture_sign_requires_current_client_and_a_fresh_exact_review(self):
        self.ctx['messages'][0]['body']='В Оренбурге нужно починить мебельный ящик'
        self.ctx['messages'][-1]['media_reviewed']=True
        self.ctx['messages'][-1]['media_observation']={'device_kind':'dresser','visible_symptom':'detached_drawer_front'}
        before=self.call('preview')
        self.assertTrue(before['needs_operator'])
        self.assertEqual(before['facts']['image_observations'],[])
        approval=dict(self.confirmation(),observations={'content_kind':'product_photo','device_kind':'dresser','visible_symptom':'detached_drawer_front'})
        for version in ('2.7.14','2.7.15'):
            denied=self.call('personal_media_review',**dict(approval,client_version=version))
            self.assertFalse(denied['ok'])
            self.assertEqual(denied['code'],'media_observation')
        self.assertTrue(self.call('personal_media_review',**dict(approval,client_version='2.7.16'))['ok'])
        fresh=self.call('preview')
        self.assertTrue(any('фасад' in line for line in fresh['facts']['comment_lines']))
        self.assertFalse(fresh['auto_enabled'])
        self.assertFalse(self.call('personal_media_review',**dict(approval,client_version='2.7.16'))['ok'])

    def test_client_fields_cannot_spoof_a_confirmed_visual_model(self):
        self.ctx.update(dir='kp',accountTitle='Евгений КП',itemTitle='Ремонт принтеров')
        self.ctx['messages'][0]['body']='В Оренбурге МФУ не печатает'
        self.ctx['messages'][-1]['media_observation']={'model':'Xiaomi PMDYJ02HT'}
        self.ctx['messages'][-1]['media_reviewed']=True
        self.assertTrue(self.call('preview')['needs_operator'])
        self.assertTrue(self.call('personal_media_review',**self.confirmation())['ok'])
        self.assertRegex(self.call('preview')['reply'],'[Мм]арк|[Мм]одел')

    def test_product_photo_caption_does_not_become_a_scheme_but_client_words_still_count(self):
        self.ctx['messages'][0]['body']='В Оренбурге собрать шкаф'
        self.ctx['messages'].append(dict(id='4',direction='in',body='Вот инструкция'))
        approval=dict(self.confirmation(),client_version='2.7.9',observations={'content_kind':'product_photo'})
        self.assertTrue(self.call('personal_media_review',**approval)['ok'])
        out=self.call('preview')
        self.assertNotEqual(out['qualification'].get('instructions',{}).get('status'),'answered')
        self.assertRegex(out['reply'],'инструкц|[Сс]хем')
        self.ctx['messages'].append(dict(id='5',direction='in',body='Да, отдельная схема сборки есть'))
        self.assertEqual(self.call('preview')['qualification']['instructions']['status'],'answered')

    def test_empty_printer_pages_are_already_a_problem_description(self):
        import qualification_state as qs
        for body in ('МФУ иногда печатает пустые листы','МФУ не пропичатывает и пустые листы выкидывает'):
            self.assertEqual(qs.inspect([dict(id='text',direction='in',body=body)])['problem']['status'],'answered')

    def test_upgrade_preserves_legacy_reviews_without_fabricating_visual_facts(self):
        with self.app.store.connect() as db:
            db.execute('CREATE TABLE personal_media_reviews (scope TEXT,chat TEXT,message_id TEXT,signature TEXT,policy TEXT,operator TEXT,reviewed REAL,PRIMARY KEY(scope,chat,message_id,signature,policy))')
            db.execute("INSERT INTO personal_media_reviews VALUES ('old','old','old','old','old','old',0)")
        self.assertTrue(self.call('preview')['needs_operator'])
        with self.app.store.connect() as db:
            self.assertIn('observations', {row[1] for row in db.execute('PRAGMA table_info(personal_media_reviews)')})
            self.assertEqual(db.execute('SELECT observations FROM personal_media_reviews').fetchone()[0], '{}')
        self.assertTrue(self.call('personal_media_review',**self.confirmation())['ok'])

    def test_model_and_kind_cannot_describe_an_ambiguous_multi_image_message(self):
        self.ctx['messages'][-1]['attachments'].append({'kind':'image','url':'https://example.test/other.jpg'})
        approval=dict(self.confirmation(),client_version='2.7.9')
        for observation in ({'model':'Canon G3411'},{'content_kind':'assembly_diagram'}):
            self.assertFalse(self.call('personal_media_review',**approval,observations=observation)['ok'])
        self.assertTrue(self.call('preview')['needs_operator'])

    def visual(self, observations):
        return self.call('personal_media_review', **dict(self.confirmation(), client_version='2.7.14', observations=observations))

    def test_viewed_tv_bands_trigger_owner_refusal_without_a_matrix_diagnosis(self):
        self.ctx.update(dir='kp',accountTitle='Денис КП',itemTitle='Ремонт телевизоров')
        self.ctx['messages']=[dict(id='1',direction='in',body='Здравствуйте, телевизор показывает вот так'),self.ctx['messages'][-1]]
        self.assertTrue(self.visual(dict(content_kind='product_photo',device_kind='tv',visible_symptom='tv_screen_bands'))['ok'])
        out=self.call('preview');self.assertEqual(out['action'],'refuse');self.assertIn('OWNER-TV-BANDS-20261017',out['rule_ids'])
        self.assertNotRegex(out['reply'],r'матриц|\d+.*руб');self.assertFalse(out['auto_enabled'])

    def test_monitor_bands_do_not_become_a_tv_or_confirmed_matrix_repair(self):
        self.ctx.update(dir='kp',accountTitle='Денис КП',itemTitle='Ремонт компьютеров')
        self.ctx['messages']=[dict(id='1',direction='in',body='На мониторе помехи. Меняю кабель HDMI в материнке, помогает ненадолго'),self.ctx['messages'][-1]]
        self.assertTrue(self.visual(dict(content_kind='product_photo',device_kind='monitor',visible_symptom='screen_bands'))['ok'])
        out=self.call('preview');self.assertEqual(out['action'],'question',out['reason']);self.assertNotIn('OWNER-TV-BANDS-20261017',out['rule_ids'])
        self.assertNotRegex(out['reply'],r'не смогу помочь|матриц.*сломан')
        self.assertTrue(any('причина не установлена' in x for x in out['facts']['comment_lines']))

    def test_rj45_fact_survives_and_unanswered_first_price_does_not_skip_to_a_numeric_tariff(self):
        self.ctx.update(dir='kp',accountTitle='Денис КП',itemTitle='Ремонт компьютеров')
        self.ctx['messages']=[dict(id='1',direction='in',body='Сколько стоит обжать коннектор?'),dict(id='2',direction='out',body='Какой у вас кабель?'),dict(id='4',direction='in',body='Серый'),dict(id='5',direction='out',body='Пришлите фото'),self.ctx['messages'][-1]]
        self.assertTrue(self.visual(dict(content_kind='product_photo',device_kind='ethernet_cable',connector_type='RJ45'))['ok'])
        out=self.call('preview');self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'стоимост|цен')
        self.assertNotRegex(out['reply'],r'500|витая.*или.*оптоволок|какой.*кабел')
        self.assertEqual(out['qualification']['cable_type']['status'],'answered')
        self.assertEqual(out['facts']['image_observations'][0]['source'],'reviewed_image')
        self.assertEqual(out['facts']['image_observations'][0]['connector_type'],'RJ45')

    def test_visual_signs_cannot_supply_diagnosis_wrong_device_type_or_label_only_symptoms(self):
        for observation in [dict(content_kind='product_photo',device_kind='monitor',visible_symptom='tv_screen_bands'),
                            dict(content_kind='device_label',device_kind='tv',visible_symptom='screen_bands'),
                            dict(content_kind='product_photo',device_kind='tv',connector_type='RJ45'),
                            dict(content_kind='product_card',device_kind='tv'),
                            dict(content_kind='product_photo',device_kind='tv',visible_symptom='broken_matrix')]:
            self.assertFalse(self.visual(observation)['ok'])
        old=dict(self.confirmation(),client_version='2.7.13',observations=dict(content_kind='product_photo',device_kind='tv'))
        self.assertFalse(self.call('personal_media_review',**old)['ok'])

    def test_conflicting_client_device_and_reviewed_device_require_operator_without_refusal(self):
        self.ctx.update(dir='kp',accountTitle='Денис КП',itemTitle='Ремонт компьютеров')
        self.ctx['messages']=[dict(id='1',direction='in',body='На мониторе полосы'),self.ctx['messages'][-1]]
        self.assertTrue(self.visual(dict(content_kind='product_photo',device_kind='tv',visible_symptom='tv_screen_bands'))['ok'])
        out=self.call('preview');self.assertEqual(out['action'],'handoff');self.assertFalse(out['reply']);self.assertIn('расходится',out['reason'])
        form=self.call('checklist');self.assertTrue(form['hard_block'])

    def test_raw_visual_fields_still_cannot_bypass_review(self):
        self.ctx['messages'][-1].update(media_reviewed=True,media_observation=dict(content_kind='product_photo',device_kind='tv',visible_symptom='tv_screen_bands'))
        out=self.call('preview');self.assertTrue(out['needs_operator']);self.assertNotIn('OWNER-TV-BANDS-20261017',out['rule_ids'])


    def test_error_code_receipt_requires_new_client_and_preserves_source(self):
        self.ctx.update(dir='kp',accountTitle='Иван КП',itemTitle='Настройка приставок')
        self.ctx['messages']=[dict(id='1',direction='in',body='У меня проблема в Xbox'),dict(id='2',direction='out',body='Пришлите фото'),self.ctx['messages'][-1]]
        observation=dict(content_kind='device_message',error_system='xbox_live',error_code='80154058')
        approval=dict(self.confirmation(),client_version='2.7.22',observations=observation)
        self.assertFalse(self.call('personal_media_review',**approval)['ok'])
        self.assertTrue(self.call('personal_media_review',**dict(approval,client_version='2.7.23'))['ok'])
        out=self.call('preview')
        self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'действ.*ошиб')
        self.assertEqual(out['facts']['image_observations'][0]['error_code'],'80154058')
        self.assertEqual(out['facts']['image_observations'][0]['message_id'],'3')
        self.assertFalse(out['facts']['phone_values']);self.assertFalse(out['auto_enabled'])

    def test_raw_error_fields_cannot_replace_a_view_receipt(self):
        self.ctx['messages'][-1].update(media_reviewed=True,media_observation=dict(content_kind='device_message',error_system='xbox_live',error_code='80154058'))
        out=self.call('preview')
        self.assertTrue(out['needs_operator']);self.assertEqual(out['facts']['image_observations'],[])


if __name__ == "__main__":
    unittest.main()
