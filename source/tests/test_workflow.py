import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import personal_workflow as workflow
from assistant_store import Store
from extension_assistant import Assistant, _parse
from test_assistant import context, message


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LEADBOT_PERSONAL_OWNER_ID": "owner", "LEADBOT_PERSONAL_OPERATOR_ID": "george", "LEADBOT_ASSISTANT_WORDING": "reviewed"})
        self.env.start()
        self.app = Assistant(Store(self.tmp.name + "/db"))
        self.base = {"owner": "owner", "browser_session": "browser:tab:1", "operator_id": "george", "mine_count": 0}
        self.call("personal_start")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def call(self, action, **extra):
        if action == "personal_call_confirm" and extra.get("ctx") and "revision" not in extra:
            extra["revision"] = _parse(extra["ctx"])[3]
        return self.app.handle({**self.base, "action": action, **extra})[0]

    @contextmanager
    def auto(self):
        with patch.dict(os.environ, {"LEADBOT_PERSONAL_AUTO_AVAILABLE": "1"}):
            session = self.call("personal_status")
            enabled = self.call("personal_mode", execution_mode="auto", confirmed=True, activation_nonce=session["activation_nonce"], policy_ack=session["policy_version"], client_version="2.7.0")
            self.assertTrue(enabled["auto_enabled"])
            try:
                yield
            finally:
                self.call("personal_mode", execution_mode="review")

    def ctx(self, ready=False, **extra):
        text = "Компьютер Dell Optiplex9020 не включается, я в Чите."
        if ready:
            text += " Адрес: улица Ленина, дом 12, квартира 4. Для связи +7 900 111 22 33. Решение принимаю я. Я оплачу и буду на месте. Меня зовут Иван. Завтра в 14:00 удобно."
        return context([message(text)], accountId="account", assigneeId="george", assignmentKnown=True,
                       conversationStatus="in_progress", botActive=False, hasTransfer=False, channelAssigned=True, **extra)

    def proposal(self, ctx):
        _, _, _, revision = _parse(ctx)
        return {"revision": revision, "dir": "kp", "allowLive": False, "readiness": "ready", "flags": [], "followup": {"telegram_ready": True},
                "lead": {"name": "Иван", "review": True, "problem": "Компьютер не включается.", "phone": "+7 900 111 22 33", "addr": {"street": "улица Ленина", "building": "12", "office": "4"},
                         "partner": "7", "ad_identity": "Денис", "comment": "Компьютер не включается. Объявление: «Денис».",
                         "partner_note": "С1", "service_comment": "https://lead.test/chats/chat-1", "visit_date": (datetime.now(ZoneInfo("Asia/Chita")) + timedelta(days=1)).date().isoformat(), "visit_time": "14:00"},
                "prep": {"ok": True, "cityText": "Чита", "cityId": "1", "applId": "2", "subId": "3", "applRule": True, "subRule": True,
                         "partnerFound": True, "found": [], "unchecked": []}, "territory": {"ok": True, "approval": False},
                "sel": {"cityId": "1", "applId": "2", "subId": "3"}}

    def test_normal_free_then_mine_next_action(self):
        ctx = self.ctx();ctx["assigneeId"] = ""
        self.assertEqual(self.call("personal_plan", ctx=ctx)["step"], "claim")
        ctx["assigneeId"] = "george"
        result = self.call("personal_plan", ctx=ctx)
        self.assertEqual(result["step"], "reply")
        self.assertFalse(result["auto_enabled"])
        self.assertFalse(result["execution_allowed"])

    def neural_draft(self, ctx):
        import json
        prepared = self.call('preview', ctx=ctx, wording_mode='neural_review')
        self.assertTrue(prepared.get('pending_model'), prepared.get('reason'))
        question = json.loads(prepared['model_task']['task'])['decision']['next_question']['question']
        return self.call('finalize', request_id=prepared['request_id'], revision=prepared['revision'],
                         candidate={'reply': question, 'needs_operator': False, 'context_review': dict(
                             last_intent='Клиент просит услугу.', latest_client_meaning=ctx['messages'][-1]['body'],
                             selected_step_fits=True, evidence_ids=[ctx['messages'][-1]['id']],
                             note='Выбранный вопрос соответствует незаполненным данным.')})

    def test_neural_test_draft_cannot_get_an_automatic_send_grant(self):
        ctx = self.ctx()
        with self.auto():
            draft = self.neural_draft(ctx)
            plan = self.call('personal_plan', ctx=ctx)
            result = self.call('personal_authorize', ctx=ctx, operation={
                'kind': 'reply', 'operation_id': plan['operation_id'], 'revision':plan['revision'], 'draft_id': draft['draft_id']})
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 'neural_review_required')

    def test_exact_neural_draft_can_get_one_reviewed_grant_without_enabling_auto(self):
        ctx = self.ctx()
        with patch.dict(os.environ, LEADBOT_PERSONAL_AUTO_AVAILABLE='1'):
            draft = self.neural_draft(ctx)
            plan = self.call('personal_plan', ctx=ctx)
            lease = self.call('personal_status')
            result = self.call('personal_review_authorize', ctx=ctx, confirmed=True,
                               activation_nonce=lease['activation_nonce'], policy_ack=lease['policy_version'],
                               client_version='2.8.7',
                               operation={'kind': 'reply', 'operation_id': plan['operation_id'],
                                          'revision':plan['revision'], 'draft_id': draft['draft_id'], 'reply': draft['reply']})
            self.assertTrue(result['ok'], result)
            self.assertTrue(result['reviewed'])
            self.assertFalse(result['auto_enabled'])

    def test_reviewed_time_offer_cannot_get_a_grant_after_hours_boundary(self):
        ctx = self.ctx(city='Саратов', itemTitle='Ремонт принтеров')
        ctx['messages'] = [message('Принтер Canon MG2540S жуёт бумагу.', mid='job'),
            message('Куда подъехать?', 'out', 'where'), message('Шехурдина 8а, 91', mid='address'),
            message('Напишите, пожалуйста, время', mid='when')]
        with patch.dict(os.environ, LEADBOT_PERSONAL_AUTO_AVAILABLE='1'):
            with patch('assistant_policy._visit_question_now', return_value=datetime.fromisoformat('2026-10-21T19:59:00+04:00')):
                draft = self.call('preview', ctx=ctx, wording_mode='reviewed')
                self.assertTrue(draft['visit_offer'])
                plan = self.call('personal_plan', ctx=ctx)
            lease = self.call('personal_status')
            with patch('assistant_policy._visit_question_now', return_value=datetime.fromisoformat('2026-10-21T20:01:00+04:00')):
                result = self.call('personal_review_authorize', ctx=ctx, confirmed=True,
                    activation_nonce=lease['activation_nonce'], policy_ack=lease['policy_version'],
                    client_version='2.8.7', operation={'kind':'reply', 'operation_id':plan['operation_id'],
                    'revision':plan['revision'], 'draft_id':draft['draft_id'], 'reply':draft['reply']})
            self.assertFalse(result['ok']); self.assertEqual(result['code'], 'time_offer_expired')
            with self.app.store.connect() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_grants'").fetchone()
                self.assertEqual(db.execute('SELECT count(*) FROM workflow_grants').fetchone()[0] if exists else 0, 0)

    def test_map_mismatch_cannot_be_hidden_behind_a_success_flag(self):
        ctx = self.ctx(True)
        proposal = self.proposal(ctx)
        proposal['territory'].update(mismatch=True)
        _, messages, known, revision = _parse(ctx)
        ctx['workflowRevision'] = revision
        result = workflow.check_crm(messages, known, ctx, proposal)
        self.assertFalse(result['ready'])
        self.assertIn('Адрес или город не совпадает с проверкой карты: нужен оператор до выбора филиала', result['reasons'])

    def test_qualified_address_requires_a_matching_house_receipt(self):
        ctx = self.ctx(True)
        ctx['messages'][0]['body'] = ctx['messages'][0]['body'].replace('Адрес:', 'Адрес: мкр Северный,')
        proposal = self.proposal(ctx)
        _, messages, known, revision = _parse(ctx)
        import contact_facts
        facts = contact_facts.collect(messages, known)
        self.assertTrue(facts['address'].get('settlement'))
        proposal['lead']['addr'] = dict(facts['address'])
        ctx['workflowRevision'] = revision
        result = workflow.check_crm(messages, known, ctx, proposal)
        reason = 'Населённый пункт или микрорайон не проверен вместе с улицей и домом'
        self.assertIn(reason, result['reasons'])
        proposal['territory'].update(address_verified=True, checkedAddress=dict(facts['address']))
        result = workflow.check_crm(messages, known, ctx, proposal)
        self.assertNotIn(reason, result['reasons'])
        proposal['territory']['checkedAddress']['building'] = '99'
        self.assertIn(reason, workflow.check_crm(messages, known, ctx, proposal)['reasons'])

    def test_numbered_partner_source_is_preserved_without_allowing_untyped_numbers(self):
        ctx = self.ctx(True, partner='748', origin='№3')
        proposal = self.proposal(ctx)
        proposal['lead'].update(partner='748', partner_note='№3')
        _, messages, known, _ = _parse(ctx)
        result = workflow.check_crm(messages, known, ctx, proposal)
        self.assertNotIn('Не подтверждён источник заявки', result['reasons'])
        for wrong in ('3', '№4', '№3 Белый'):
            proposal['lead']['partner_note'] = wrong
            result = workflow.check_crm(messages, known, ctx, proposal)
            self.assertIn('Не подтверждён источник заявки', result['reasons'])

    def test_completed_qualification_is_prepare_not_unconditional_handoff(self):
        self.assertEqual(self.call("personal_plan", ctx=self.ctx(True))["step"], "prepare_crm")

    def test_known_negative_intercom_requires_new_payload_and_post_read_field(self):
        import contact_facts
        ctx = self.ctx(True)
        ctx['messages'][0]['body'] += ' Домофона нет.'
        proposal = self.proposal(ctx)
        _, messages, known, revision = _parse(ctx)
        ctx['workflowRevision'] = revision
        proposal['lead']['comment'] += '\n' + '\n'.join(contact_facts.collect(messages, known)['comment_lines'])
        reason = 'Наличие домофона в заявке отличается от слов клиента. Обновите расширение или проверьте отметку'
        self.assertIn(reason, workflow.check_crm(messages, known, ctx, proposal)['reasons'])
        proposal['lead']['addr']['has_intercom'] = False
        self.assertNotIn(reason, workflow.check_crm(messages, known, ctx, proposal)['reasons'])
        fields = workflow.CRM_CORE_FIELDS + workflow.required_crm_fields(messages, known)
        self.assertIn('домофон', fields)
        from assistant_store import digest
        from assistant_policy import VERSION
        required = dict(fields=__import__('json').dumps(fields), policy=VERSION, message_revision=digest(messages))
        receipt = dict(fields=fields, crm_request_id='synthetic', diffs=[], warnings=[], policy_version=VERSION, message_revision=digest(messages))
        self.assertTrue(workflow.receipt_verified(required, receipt, 'synthetic', messages))
        receipt['fields'] = [f for f in fields if f != 'домофон']
        self.assertFalse(workflow.receipt_verified(required, receipt, 'synthetic', messages))

    def test_real_author_name_question_recognizes_the_following_answer(self):
        import qualification_state
        for question in ["Вас как зовут?", "А вас как зовут?", "Как могу к вам обращаться?"]:
            rows = [message(question, "out", "ask"), message("Иван", "in", "name")]
            parsed = _parse(context(rows))[1]
            self.assertEqual(qualification_state.inspect(parsed)["client_name"]["value"], "Иван")

    def test_wait_and_all_scope_failures_do_not_claim(self):
        ctx = self.ctx();ctx["messages"].append(message("Модель подскажите?", "out", "m2"))
        self.assertEqual(self.call("personal_plan", ctx=ctx)["step"], "wait")
        for key, value in [("assigneeId", "colleague"), ("channelAssigned", None), ("botActive", True), ("hasTransfer", True), ("conversationStatus", "closed")]:
            ctx = self.ctx();ctx[key] = value
            self.assertFalse(self.call("personal_plan", ctx=ctx)["eligible"])

    def test_no_request_environment_or_operation_can_enable_production(self):
        with patch.dict(os.environ, {"LEADBOT_AUTO_ENABLED": "true"}):
            for body in ({}, {"auto_enabled": True}, {"operation": {"kind": "create_crm"}}):
                out, code = self.app.handle({**self.base, "action": "personal_authorize", **body})
                self.assertEqual(code, 403);self.assertFalse(out["auto_enabled"])

    def test_wrong_owner_and_expired_session_cannot_plan_or_confirm_call(self):
        for action in ["personal_plan", "personal_crm_check", "personal_call_confirm"]:
            self.assertEqual(self.app.handle({**self.base, "owner": "other", "action": action})[1], 403)
        self.call("personal_stop")
        self.assertFalse(self.call("personal_plan", ctx=self.ctx())["ok"])

    def test_missing_call_and_forged_proposal_call_flag_do_not_pass(self):
        ctx = self.ctx(True);p = self.proposal(ctx);p["call_confirmed"] = True
        result = self.call("personal_crm_check", ctx=ctx, proposal=p)
        self.assertTrue(result["ready"], result["reasons"])
        self.assertEqual(result["reasons"], [])

    def test_jivo_uses_actual_partner_and_exact_source_code(self):
        ctx = self.ctx(True)
        ctx.update(channel='jivo', partner='740')
        ctx['messages'][-1]['body'] += '\nМне 32 года.'
        proposal = self.proposal(ctx)
        proposal['lead']['partner'] = '740'
        proposal['lead']['comment'] += '\nВозраст клиента со слов: 32.'
        preview = self.call('preview', ctx=ctx)
        self.assertEqual(preview['lead']['partner'], '740')
        result = self.call('personal_crm_check', ctx=ctx, proposal=proposal)
        self.assertTrue(result['ready'], result['reasons'])
        proposal['lead']['partner'] = '7'
        result = self.call('personal_crm_check', ctx=ctx, proposal=proposal)
        self.assertIn('Не подтверждён партнёр CRM', result['reasons'])
        proposal['lead']['partner'] = '740'
        proposal['lead']['partner_note'] = 'Источник С1 Белый'
        result = self.call('personal_crm_check', ctx=ctx, proposal=proposal)
        self.assertIn('Не подтверждён источник заявки', result['reasons'])

    def test_jivo_pc_requires_confirmed_age_before_creation(self):
        ctx = self.ctx(True)
        ctx['channel'] = 'jivo'
        result = self.call('personal_crm_check', ctx=ctx, proposal=self.proposal(ctx))
        self.assertFalse(result.get('ready', False))
        self.assertRegex(self.call('preview', ctx=ctx)['reply'], 'возраст')
        ctx['messages'][-1]['body'] += '\nМне 17 лет.'
        preview = self.call('preview', ctx=ctx)
        # DOC-L1572 permits the visit with an attending adult. Keep CRM
        # blocked while asking when that person can attend.
        self.assertEqual(preview['action'], 'question')
        self.assertRegex(preview['reason'], '[Нн]есовершеннолетн')
        self.assertRegex(preview['reply'], 'взросл')

    def test_minor_crm_waits_for_adult_confirmation_and_revokes_it_on_absence(self):
        import contact_facts
        ctx = self.ctx(True)
        ctx['messages'][0]['body'] += ' Мне 17 лет.'
        self.assertFalse(self.call('personal_crm_check', ctx=ctx, proposal=self.proposal(ctx)).get('ready', False))
        ctx['messages'] += [message('Кто-то из взрослых будет дома в это время?', direction='out', mid='adult-q'),
                            message('Да', mid='adult-a')]
        proposal = self.proposal(ctx)
        _, messages, known, _ = _parse(ctx)
        proposal['lead']['comment'] += ' ' + ' '.join(contact_facts.crm_comment_lines(contact_facts.collect(messages, known)))
        proposal['revision'] = self.call('personal_plan', ctx=ctx)['revision']
        checked = self.call('personal_crm_check', ctx=ctx, proposal=proposal)
        self.assertTrue(checked.get('ready'), checked)
        ctx['messages'].append(message('Родителей не будет дома', mid='adult-withdrawn'))
        self.assertFalse(self.call('personal_crm_check', ctx=ctx, proposal=self.proposal(ctx)).get('ready', False))

    def test_personal_explicit_call_confirmation_binds_current_revision(self):
        ctx = self.ctx(True)
        self.assertTrue(self.call("personal_call_confirm", ctx=ctx, confirmed=True)["call_confirmed"])
        result = self.call("personal_crm_check", ctx=ctx, proposal=self.proposal(ctx))
        self.assertTrue(result["ready"], result["reasons"]);self.assertFalse(result["execution_allowed"])
        ctx["accountId"] = "another-account"
        result = self.call("personal_crm_check", ctx=ctx, proposal=self.proposal(ctx))
        self.assertTrue(result["ready"])
        _, _, _, revision = _parse(ctx)
        self.assertFalse(workflow.record_call(self.app.store, "owner", self.call("personal_status"), ctx["convId"], revision, False))

    def test_call_confirmation_requires_completed_mine_dialogue(self):
        self.assertFalse(self.call("personal_call_confirm", ctx=self.ctx(), confirmed=True)["ok"])
        ctx = self.ctx(True);ctx["assigneeId"] = ""
        self.assertFalse(self.call("personal_call_confirm", ctx=ctx, confirmed=True)["ok"])

    def test_manual_pause_blocks_claim_reply_call_confirmation_and_crm(self):
        ctx = self.ctx(True);self.call("takeover", ctx=ctx)
        for action in ["screen", "personal_plan", "personal_crm_check", "personal_call_confirm"]:
            out = self.call(action, ctx=ctx, proposal=self.proposal(ctx), confirmed=True)
            self.assertEqual(out["code"], "paused");self.assertFalse(out["eligible"])
        self.call("resume", ctx=ctx)
        self.assertEqual(self.call("personal_plan", ctx=ctx)["step"], "prepare_crm")

    def test_call_receipt_is_scoped_and_expires(self):
        store = self.app.store;s = {"operator_id": "george"}
        self.assertTrue(workflow.record_call(store, "one", s, "chat", "r", True, 100))
        self.assertFalse(workflow.record_call(store, "two", s, "chat", "r", False, 101))
        self.assertFalse(workflow.record_call(store, "one", s, "chat", "changed", False, 101))
        self.assertFalse(workflow.record_call(store, "one", s, "chat", "r", False, 701))

    def test_every_crm_ambiguity_blocks_without_bypasses(self):
        ctx = self.ctx(True);self.call("personal_call_confirm", ctx=ctx, confirmed=True)
        changes = [("revision", "old"), ("dir", "bt"), ("allowLive", True), ("flags", ["agreement"]), ("readiness", "almost")]
        for key, val in changes:
            p = self.proposal(ctx);p[key] = val
            self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"], key)
        for group, key, val in [("lead", "phone", "+7 900 999 00 11"), ("lead", "comment", "missing identity"), ("lead", "partner_note", ""),
                                ("lead", "service_comment", ""), ("lead", "visit_time", ""), ("lead", "partner", "723"),
                                ("prep", "applRule", False), ("prep", "subRule", False), ("prep", "unchecked", [{"dir": "bt"}]),
                                ("prep", "found", [{"id": "old"}]), ("prep", "live", "В работе"), ("prep", "partnerFound", False),
                                ("territory", "approval", True), ("territory", "noMap", True)]:
            p = self.proposal(ctx);p[group][key] = val
            self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"], (group, key))
        p = self.proposal(ctx);p["lead"]["addr"]["building"] = "99"
        self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"])

    def test_crm_comment_must_preserve_the_complete_intercom_code(self):
        ctx = self.ctx(True)
        ctx["messages"][0]["body"] += " Домофон 108#742."
        p = self.proposal(ctx)
        p["lead"]["addr"]["intercom"] = "108#742"
        p["lead"]["addr"]["has_intercom"] = True
        blocked = self.call("personal_crm_check", ctx=ctx, proposal=p)
        self.assertFalse(blocked["ready"])
        self.assertTrue(any("код домофона" in r for r in blocked["reasons"]))
        p["lead"]["comment"] += "\nДомофон: 108#742.\nДомофон есть."
        self.assertTrue(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"])
        p["lead"]["comment"] = p["lead"]["comment"].replace("108#742", "108")
        self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"])

    def test_crm_comment_must_preserve_the_client_landmark(self):
        import contact_facts
        ctx = self.ctx(True)
        ctx["messages"].append(message("Мы находимся на жд вокзале Чита 2 в зале ожидания, отдел Смартфон 159", "in", "venue"))
        p = self.proposal(ctx)
        result = self.call("personal_crm_check", ctx=ctx, proposal=p)
        self.assertFalse(result["ready"])
        self.assertTrue(any("ориентиры" in r for r in result["reasons"]))
        facts = contact_facts.collect(_parse(ctx)[1], _parse(ctx)[2])
        p["lead"]["comment"] += "\n" + "\n".join(facts["comment_lines"])
        self.assertTrue(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"])

    def test_dell_xps_is_not_a_playstation(self):
        ctx = self.ctx();ctx["messages"][0]["body"] = "Компьютер Dell XPS8930 не включается, я в Чите"
        self.assertTrue(self.call("personal_plan", ctx=ctx)["eligible"])
        ctx["messages"][0]["body"] = "Ремонт PS5, не включается, я в Чите"
        self.assertFalse(self.call("personal_plan", ctx=ctx)["eligible"])

    def operation(self, ctx, kind, **extra):
        plan = self.call("personal_plan", ctx=ctx)
        return {"kind": kind, "revision": plan["revision"], "operation_id": plan["operation_id"], **extra}

    def test_dormant_broker_issues_one_short_grant_and_never_reissues_it(self):
        ctx = self.ctx();ctx["assigneeId"] = ""
        op = self.operation(ctx, "claim")
        with self.auto():
            out = self.call("personal_authorize", ctx=ctx, operation=op)
            self.assertTrue(out["execution_allowed"]);self.assertEqual(out["kind"], "claim")
            self.assertEqual(out["operator_id"], "george");self.assertGreater(len(out["permit"]), 30)
            self.app = Assistant(Store(self.tmp.name + "/db"))
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=op)["code"], "already_started")

    def test_dormant_broker_rejects_wrong_kind_revision_and_assignment(self):
        ctx = self.ctx();op = self.operation(ctx, "reply")
        with self.auto():
            for change in [{"kind": "erase"}, {"revision": "old"}, {"operation_id": "invented"}]:
                self.assertFalse(self.call("personal_authorize", ctx=ctx, operation={**op, **change})["ok"])
            ctx["assigneeId"] = "colleague"
            self.assertFalse(self.call("personal_authorize", ctx=ctx, operation=self.operation(ctx, "reply"))["ok"])

    def test_reply_grant_requires_an_actual_fresh_server_draft(self):
        ctx = self.ctx();op = self.operation(ctx, "reply")
        with self.auto():
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=op)["code"], "draft")
            draft = self.call("preview", ctx=ctx)
            self.assertTrue(self.call("personal_authorize", ctx=ctx, operation={**op, "draft_id": draft["draft_id"]})["ok"])

    def test_reply_authorization_independently_rejects_first_draft_without_greeting(self):
        with patch.dict(os.environ, {"LEADBOT_PERSONAL_AUTO_AVAILABLE": "1"}):
            ctx = self.ctx()
            draft = self.call("preview", ctx=ctx)
            bad_reply = "Марку и модель подскажите?"
            op = self.operation(ctx, "reply", draft_id=draft["draft_id"], reply=bad_reply)
            with patch.object(self.app.store, "draft", return_value={**draft, "reply": bad_reply}):
                out = self.call("personal_review_authorize", ctx=ctx, operation=op,
                                **self.review_confirmation())
            self.assertFalse(out["ok"])
            self.assertEqual(out["code"], "greeting")
            self.assertFalse(out["execution_allowed"])

    def test_create_grant_rechecks_snapshot_call_and_all_fields(self):
        ctx = self.ctx(True);p = self.proposal(ctx)
        op = self.operation(ctx, "create_crm", proposal=p, snapshot_hash="wrong")
        with self.auto():
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=op)["code"], "crm_gate")
            self.call("personal_call_confirm", ctx=ctx, confirmed=True)
            gate = self.call("personal_crm_check", ctx=ctx, proposal=p)
            op["snapshot_hash"] = gate["snapshot_hash"]
            self.assertTrue(self.call("personal_authorize", ctx=ctx, operation=op)["ok"])
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=op)["code"], "already_started")

    def test_link_grant_requires_a_prior_creation_and_exact_request_id(self):
        ctx = self.ctx(True);p = self.proposal(ctx)
        with self.auto():
            link = self.operation(ctx, "link_crm", operation_id="link:1234567", crm_request_id="1234567")
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=link)["code"], "receipt")
            self.call("personal_call_confirm", ctx=ctx, confirmed=True)
            gate = self.call("personal_crm_check", ctx=ctx, proposal=p)
            create = self.operation(ctx, "create_crm", proposal=p, snapshot_hash=gate["snapshot_hash"])
            self.assertTrue(self.call("personal_authorize", ctx=ctx, operation=create)["ok"])
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=link)["code"], "crm_verification")
            plan = self.call("personal_plan", ctx=ctx)
            import personal_workflow
            proof = {"crm_request_id": "1234567", "fields": personal_workflow.CRM_CORE_FIELDS + plan["crm_required_fields"], "diffs": [], "warnings": [], "policy_version": plan["policy_version"], "message_revision": plan["message_revision"]}
            self.assertIn("квартира", proof["fields"])
            bad = dict(proof, fields=[f for f in proof["fields"] if f != "квартира"])
            self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=dict(link, verification=bad))["code"], "crm_verification")
            for change in ({"diffs": ["квартира"]}, {"warnings": ["не проверено"]}, {"policy_version": "old"}, {"message_revision": "old"}, {"crm_request_id": "7654321"}):
                self.assertEqual(self.call("personal_authorize", ctx=ctx, operation=dict(link, verification={**proof, **change}))["code"], "crm_verification")
            link["verification"] = proof
            self.assertTrue(self.call("personal_authorize", ctx=ctx, operation=link)["ok"])

    def test_manual_confirmation_cannot_accept_a_new_unreviewed_revision(self):
        ctx = self.ctx(True)
        self.assertEqual(self.call("personal_call_confirm", ctx=ctx, confirmed=True, revision="old")["code"], "stale")

    def test_names_and_visit_questions_are_collected_before_crm(self):
        ctx = self.ctx(True);ctx["messages"][0]["body"] = ctx["messages"][0]["body"].split(" Меня зовут")[0]
        out = self.call("preview", ctx=ctx)
        self.assertRegex(out["reply"].lower(), r"обращ|зовут")
        ctx["messages"] += [message(out["reply"], "out", "q2"), message("Иван", mid="a2")]
        out = self.call("preview", ctx=ctx)
        self.assertIn("время", out["reply"].lower())
        self.assertFalse(out.get("validation"))

    def test_crm_time_is_not_invented_or_accepted_after_a_correction(self):
        ctx = self.ctx(True);self.call("personal_call_confirm", ctx=ctx, confirmed=True)
        for key, value in [("visit_date", "2020-01-01"), ("visit_date", "2026-02-31"), ("visit_time", "14:30"), ("visit_time", "22:00"), ("name", "Пётр"), ("review", False)]:
            p = self.proposal(ctx);p["lead"][key] = value
            self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=p)["ready"], key)
        _, ms, known, _ = _parse(ctx)
        ms[0]["body"] += " Не завтра, а послезавтра."
        self.assertTrue(workflow.visit_check(ms, known, self.proposal(ctx)["lead"], {}))

    def test_malformed_proposals_fail_without_exception_or_transport(self):
        ctx = self.ctx(True)
        for proposal in (None, {}, {"lead": []}, {"lead": {"addr": []}, "prep": {}, "sel": {}, "territory": {}}):
            self.assertFalse(self.call("personal_crm_check", ctx=ctx, proposal=proposal)["ok"])

    def test_last_moment_crm_guard_requires_current_live_issued_grant(self):
        ctx = self.ctx(True);p = self.proposal(ctx)
        revision = self.operation(ctx, "create_crm")["revision"]
        self.assertFalse(self.call("personal_check_started", ctx=ctx, revision=revision)["ok"])
        with self.auto():
            self.assertFalse(self.call("personal_check_started", ctx=ctx, revision=revision)["ok"])

            self.call("personal_call_confirm", ctx=ctx, confirmed=True)
            gate = self.call("personal_crm_check", ctx=ctx, proposal=p)
            operation = self.operation(ctx, "create_crm", proposal=p, snapshot_hash=gate["snapshot_hash"])
            self.assertTrue(self.call("personal_authorize", ctx=ctx, operation=operation)["ok"])
            self.assertTrue(self.call("personal_check_started", ctx=ctx, revision=revision)["execution_allowed"])
            self.call("personal_mode", execution_mode="review")
            lease = self.call("personal_status")
            self.call("personal_mode", execution_mode="auto", confirmed=True, activation_nonce=lease["activation_nonce"], policy_ack=lease["policy_version"], client_version="2.7.0")
            self.assertFalse(self.call("personal_check_started", ctx=ctx, revision=revision)["ok"])
            self.assertFalse(self.call("personal_check_started", ctx=ctx, revision="old")["ok"])
            with self.app.store.connect() as db:
                db.execute("UPDATE workflow_grants SET expires=0")
            self.assertFalse(self.call("personal_check_started", ctx=ctx, revision=revision)["ok"])

    def test_real_statuses_and_server_owned_limit_ignore_historic_backlog(self):
        ctx = self.ctx();ctx["assigneeId"] = "";ctx["conversationStatus"] = "new"
        self.assertTrue(self.call("screen", ctx=ctx, mine_count=999)["eligible"])
        for state in ("new", "in_progress", "waiting_client"):
            ctx["conversationStatus"] = state
            self.assertTrue(self.call("screen", ctx=ctx)["eligible"])
        for state in ("open", "closed", "unknown", ""):
            ctx["conversationStatus"] = state
            self.assertFalse(self.call("screen", ctx=ctx)["eligible"])

    def test_more_than_100_jobs_without_limit_and_completion_tracking(self):
        from copy import deepcopy
        jobs = []
        with self.auto():
            for i in range(101):
                # Capacity is exercised under a live lease, as in the browser:
                # source/plan checks can make this batch outlive the45s lease.
                if i % 10 == 0:
                    heartbeat = self.call("personal_heartbeat")
                    self.assertTrue(heartbeat["active"], heartbeat)
                    self.assertTrue(heartbeat["auto_enabled"], heartbeat)
                ctx = self.ctx();ctx.update(convId="job-"+str(i), assigneeId="", conversationStatus="new")
                jobs.append(ctx)
                authorized = self.call("personal_authorize", ctx=ctx, mine_count=999, operation=self.operation(ctx, "claim"))
                self.assertTrue(authorized["ok"], authorized)
            self.assertEqual(self.call("personal_status")["managed_dialogs"], 101)
            fourth = deepcopy(jobs[0]);fourth["convId"] = "fourth"
            self.assertTrue(self.call("screen", ctx=fourth, mine_count=999)["eligible"])
            closed = deepcopy(jobs[0]);closed["conversationStatus"] = "closed"
            self.call("personal_plan", ctx=closed)
            self.assertEqual(self.call("personal_status")["managed_dialogs"], 100)
            authorized = self.call("personal_authorize", ctx=fourth, operation=self.operation(fourth, "claim"))
            self.assertTrue(authorized["ok"], authorized)
            linked = deepcopy(jobs[1]);linked["crmRequestId"] = "1234567"
            self.call("personal_plan", ctx=linked)
            self.assertEqual(self.call("personal_status")["managed_dialogs"], 100)

    def review_confirmation(self):
        s = self.call('personal_status')
        return dict(confirmed=True, policy_ack=s['policy_version'], activation_nonce=s['activation_nonce'], client_version='2.7.1')

    def test_reviewed_claim_is_single_use_and_never_enables_auto(self):
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '1'}):
            ctx = self.ctx();ctx['assigneeId'] = ''
            approval = self.review_confirmation()
            out = self.call('personal_review_authorize', ctx=ctx, operation=self.operation(ctx,'claim'), **approval)
            self.assertTrue(out['ok']);self.assertTrue(out['reviewed']);self.assertFalse(out['auto_enabled'])
            s = self.call('personal_status');self.assertEqual(s['execution_mode'],'review');self.assertFalse(s['auto_enabled'])
            self.assertNotEqual(s['activation_nonce'],approval['activation_nonce'])
            ctx['convId'] = 'another-chat'
            self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation=self.operation(ctx,'claim'),**approval)['ok'])
            self.assertFalse(self.call('personal_authorize',ctx=ctx,operation=self.operation(ctx,'claim'))['ok'])

    def test_reviewed_reply_rejects_every_unreviewed_or_stale_confirmation(self):
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '1'}):
            ctx = self.ctx();draft = self.call('preview',ctx=ctx)
            op = self.operation(ctx,'reply',draft_id=draft['draft_id'],reply=draft['reply'])
            for bad in [{'confirmed':False},{'activation_nonce':'invalid-code-at-least-twenty'},{'policy_ack':'old'},{'client_version':'2.7.0'}]:
                self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation=op,**{**self.review_confirmation(),**bad})['ok'])
            for bad in [{'reply':'Другой ответ'},{'revision':'old'},{'draft_id':'other'},{'kind':'create_crm'}]:
                self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation={**op,**bad},**self.review_confirmation())['ok'])
            out = self.call('personal_review_authorize',ctx=ctx,operation=op,**self.review_confirmation())
            self.assertTrue(out['ok']);self.assertFalse(out['auto_enabled'])
            self.assertEqual(self.call('personal_review_authorize',ctx=ctx,operation=op,**self.review_confirmation())['code'],'already_started')

    def test_reviewed_crm_guard_requires_exact_grant_and_stops_on_mode_change(self):
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE':'1'}):
            ctx = self.ctx(True);p = self.proposal(ctx);revision = p['revision']
            self.assertFalse(self.call('personal_check_started',ctx=ctx,revision=revision)['ok'])
            gate = self.call('personal_crm_check',ctx=ctx,proposal=p)
            op = self.operation(ctx,'create_crm',proposal=p,snapshot_hash=gate['snapshot_hash'])
            self.assertTrue(self.call('personal_review_authorize',ctx=ctx,operation=op,**self.review_confirmation())['ok'])
            guard = self.call('personal_check_started',ctx=ctx,revision=revision)
            self.assertTrue(guard['ok']);self.assertTrue(guard['reviewed']);self.assertFalse(guard['auto_enabled'])
            self.call('personal_mode',execution_mode='review')
            self.assertFalse(self.call('personal_check_started',ctx=ctx,revision=revision)['ok'])

    def test_max_all_actual_variants_block_drafts_admission_and_both_write_modes(self):
        for channel in ['max','max_bot','max_user','MAX_USER']:
            ctx = self.ctx();ctx['channel'] = channel
            preview = self.call('preview',ctx=ctx)
            self.assertFalse(preview.get('reply'));self.assertTrue(preview['needs_operator'])
            self.assertFalse(self.call('screen',ctx=ctx)['eligible'])
            with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE':'1'}):
                self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation=self.operation(ctx,'reply'),**self.review_confirmation())['ok'])
                with self.auto():
                    self.assertFalse(self.call('personal_authorize',ctx=ctx,operation=self.operation(ctx,'reply'))['ok'])

    def test_reviewed_mode_does_not_bypass_kill_switch_expiry_or_owner(self):
        ctx = self.ctx();op = self.operation(ctx,'reply')
        approval = self.review_confirmation()
        self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation=op,**approval)['ok'])
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE':'1'}):
            self.assertEqual(self.app.handle({**self.base,'owner':'other','action':'personal_review_authorize','ctx':ctx,'operation':op,**approval})[1],403)
            self.call('personal_stop')
            self.assertFalse(self.call('personal_review_authorize',ctx=ctx,operation=op,**approval)['ok'])

    def test_policy_ack_version_matches_the_source_registry(self):
        import assistant_policy
        self.assertEqual(assistant_policy.VERSION, assistant_policy.registry()['version'])

    def test_waiting_for_client_is_not_mislabelled_as_missing_territory(self):
        ctx = self.ctx();ctx['messages'].append(message('Когда вам удобно принять мастера?', 'out', 'last-answer'))
        result = self.call('screen',ctx=ctx)
        self.assertFalse(result['eligible']);self.assertEqual(result['reason'],'Ожидаем ответа клиента')
        self.assertEqual(self.call('personal_plan',ctx=ctx)['step'],'wait')
