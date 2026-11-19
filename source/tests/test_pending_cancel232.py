"""Cancel authority is bound to the old request, not an unchanged client body."""
import copy
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import test_research_control214 as fixtures
import test_client_mixed_pause210 as pause_fixture
import dialogue_lifecycle


class PendingCancel232Tests(unittest.TestCase):
    setUp=fixtures.Admission214Tests.setUp
    provider=fixtures.Admission214Tests.provider
    call=fixtures.Admission214Tests.call
    pending=fixtures.Admission214Tests.pending
    arm=fixtures.Admission214Tests.arm

    def changed_source(self):
        self.body['ctx']['messages'].append(dict(id='new',direction='in',sender_type='client',body='Подождите, уточню.'))

    def test_old_pending_request_can_be_cancelled_after_client_adds_a_message(self):
        self.pending();self.changed_source()
        result,code=self.call('research_cancel')
        self.assertEqual(code,200,result);self.assertEqual(result['research_state'],'cancelled')
        self.assertEqual(self.service.pending_metadata(),[]);self.assertEqual(self.requests,[])

    def test_old_grant_before_job_is_revoked_without_changing_current_source(self):
        value=self.pending();self.arm(value)
        self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        self.changed_source();before=copy.deepcopy(self.body['ctx'])
        result,code=self.call('research_cancel');self.assertEqual(code,200,result)
        self.assertEqual(self.body['ctx'],before);self.assertEqual(self.requests,[])
        with self.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants WHERE deadline>?',(self.service.jobs.clock(),)).fetchone()[0],0)

    def test_foreign_author_session_request_or_revision_cannot_cancel_the_pending_request(self):
        self.pending()
        for field,value in [('browser_session','other-device'),('request_id','other-request'),('revision','other-revision')]:
            result,code=self.call('research_cancel',**{field:value})
            self.assertEqual(code,403,result);self.assertEqual(len(self.service.pending_metadata()),1)
        self.assertEqual(self.requests,[])

    def test_cancel_racing_admission_leaves_no_usable_later_grant(self):
        value=self.pending();entered=threading.Event();release=threading.Event();cancelling=threading.Event()
        admit=self.service.jobs.admit;cancel=self.service._cancel_unsubmitted
        def gated_admission(*args,**kwargs):
            if not entered.is_set():
                entered.set()
                if not release.wait(3):raise RuntimeError('Test did not release admission')
            return admit(*args,**kwargs)
        def observed_cancel(*args,**kwargs):
            cancelling.set();return cancel(*args,**kwargs)
        self.service.jobs.admit=gated_admission;self.service._cancel_unsubmitted=observed_cancel
        with ThreadPoolExecutor(max_workers=2)as pool:
            admitted=pool.submit(self.service.admit_pending,value['binding_hash'],max_calls=2,seconds=300)
            self.assertTrue(entered.wait(3))
            cancelled=pool.submit(self.call,'research_cancel')
            self.assertTrue(cancelling.wait(3));release.set()
            self.assertTrue(admitted.result(timeout=5));result,code=cancelled.result(timeout=5)
        self.assertEqual(code,200,result);self.assertEqual(self.requests,[])
        with self.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants WHERE deadline>?',(self.service.jobs.clock(),)).fetchone()[0],0)


class PresentPause232Tests(unittest.TestCase):
    def test_current_first_person_action_can_explain_a_brief_request_to_wait(self):
        for action in ('уточняю','проверяю','ищу','смотрю'):
            result=dialogue_lifecycle.short_client_pause([pause_fixture.row('Минутку, '+action+'.')],now=pause_fixture.NOW)
            self.assertEqual(result['status'],'waiting',action)
            self.assertEqual(result['purpose_quote'],action)

    def test_pending_action_does_not_supply_result_or_extend_the_original_clock(self):
        m=pause_fixture.row('Минутку, проверяю комплектность.')
        a=dialogue_lifecycle.short_client_pause([m],now=pause_fixture.NOW)
        b=dialogue_lifecycle.short_client_pause([m],now=pause_fixture.NOW+timedelta(seconds=61))
        self.assertEqual(a['status'],'waiting');self.assertEqual(b['status'],'elapsed')
        self.assertEqual(a['anchor_at'],b['anchor_at'])

    def test_question_foreign_action_negation_and_completed_answer_do_not_become_pause(self):
        for text in ('Минутку, вы проверяете?', 'Сосед сказал: «Минутку, уточняю».',
                     'Минутку, не проверяю.', 'Минутку, всё уже проверил. Комплект полный.'):
            self.assertEqual(dialogue_lifecycle.short_client_pause([pause_fixture.row(text)],now=pause_fixture.NOW)['status'],'not_applicable',text)


if __name__=='__main__':unittest.main()
