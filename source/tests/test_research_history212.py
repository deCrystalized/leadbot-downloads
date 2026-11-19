import copy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import test_research_pipeline218 as fixture
from experienced_dialogues import create_index,Reader,digest
from research_pipeline import Corpus,ResearchError
from research_history import HistoryCorpus,private_history
from research_index import DailyIndex,Header,Page,source_hash


class Identities:
    def __init__(self):self.blocked=set()
    def check(self):return 'identity-publication'
    def header(self,cid):
        if cid in self.blocked:return None
        return dict(cid=cid,client_group='native-'+cid,phone_hashes=[],media_hashes=[])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name).resolve();self.identities=Identities()
        records=[fixture.ResearchTests.record(self,cid) for cid in ('old-a','old-b')]
        path=self.directory/'approved.sqlite3';create_index(path,records,approved_cids=['old-a','old-b'])
        self.approved=Corpus(Reader(path),[],allowed_cids=['old-a','old-b'],guard=lambda _:None,versions=lambda:'v')
        self.index=DailyIndex(self.directory/'raw',source_instance='native',guard=lambda _:True,guard_version=lambda:'a'*64)
        self.rows=fixture.ResearchTests.record(self,'native-c')['messages']
        self.rows[1]['author']='Мамонтов Георгий'
        self.current=fixture.context();self.current.update(client_group='current-group',phone_hashes=[],media_hashes=[])

    def seed(self,rows=None,group='native-group',phones=None,media=None):
        source=dict(cid='native-c',source_revision=1,client_group=group,phone_hashes=phones or[],media_hashes=media or[],
                    messages=rows if rows is not None else self.rows,metadata=dict(names=['Анна']))
        h=Header('native-c',1,group,tuple(phones or()),tuple(media or()),source_hash(source),identity_keys=('b'*64,))
        state=self.index.state();self.index.apply(Page('native','batch',state['cursor'],'cursor',(h,)),lambda _:source,expected_version=state['version'])

    def corpus(self):return HistoryCorpus(self.approved,self.index,self.identities)
    def search(self,corpus):return corpus.call('search_history',dict(query='шкаф крепёж купить',direction='mnc'),self.current)

    def test_approved_and_full_raw_history_have_distinct_authority(self):
        self.seed();corpus=self.corpus();result=self.search(corpus)
        self.assertEqual(len(result['hits']),3)
        raw=corpus.call('read_history',dict(case_id='native-c'),self.current)
        self.assertTrue(raw['full_case_read']);self.assertFalse(raw['manual_review_verified'])
        self.assertFalse(raw['weights_trained']);self.assertFalse(raw['proves_current_customer_facts'])
        self.assertEqual(len(raw['messages']),len(self.rows));self.assertNotIn('89995550000',str(raw))

    def test_current_group_phone_and_media_are_not_teacher_candidates(self):
        self.seed(phones=['d'*64],media=['c'*64])
        # The current trusted native reference identity is exclusion-only.
        self.current['media_hashes']=['c'*64]
        self.assertNotIn('native-c',[h['case_id']for h in self.search(self.corpus())['hits']])

    def test_assistant_reply_under_employee_name_is_not_experienced_human(self):
        self.rows[1]['client_message_id']='lcp:bot-operation'
        self.seed();result=self.search(self.corpus())
        self.assertNotIn('native-c',[h['case_id']for h in result['hits']])

    def test_pending_or_unconfirmed_staff_delivery_is_not_teacher(self):
        self.rows[1]['delivery']='pending'
        self.seed();self.assertNotIn('native-c',[h['case_id']for h in self.search(self.corpus())['hits']])

    def test_native_identity_guard_excludes_approved_alias_before_body_load(self):
        self.identities.blocked.add('old-a')
        corpus=self.corpus();loaded=[];original=corpus._body
        def body(row):loaded.append(row['cid']);return original(row)
        corpus._body=body
        self.search(corpus);self.assertNotIn('old-a',loaded)

    def test_stale_publication_cannot_be_used_by_previous_job(self):
        corpus=self.corpus();self.seed()
        with self.assertRaises(ResearchError):self.search(corpus)

    def test_unavailable_raw_snapshot_is_not_silently_presented_as_zero_matches(self):
        self.index.source_unavailable();corpus=self.corpus()
        result=self.search(corpus)
        self.assertFalse(result['raw_archive_available'])
        self.assertEqual(result['raw_archive_reason'],'source_sync_unavailable')
        self.assertFalse(result['full_pool_verified'])

    def test_protection_failure_blocks_approved_fallback_and_old_lesson_access(self):
        corpus=self.corpus();self.index.source_unavailable(protection=True)
        with self.assertRaises(ResearchError):self.corpus()
        with self.assertRaises(ResearchError):self.search(corpus)
        with self.assertRaises(ResearchError):corpus.filter_lessons([],self.current)

    def test_raw_case_must_be_found_before_full_model_read(self):
        self.seed();corpus=self.corpus()
        with self.assertRaises(ResearchError):corpus.call('read_history',dict(case_id='native-c'),self.current)

    def test_role_and_asr_projection_are_not_manual_audio_or_system_client_facts(self):
        rows=[dict(id='s',direction='system',sender_type='avito',body='Системное событие'),
              dict(id='b',direction='out',sender_type='operator',client_message_id='lcp:x',body='Схема есть?'),
              dict(id='v',direction='in',sender_type='client',body='',voice_transcript='Секунду.',voice_transcript_status='done')]
        out=private_history(dict(messages=rows,metadata={}))
        self.assertEqual([m['source_role']for m in out],['service','bot','client'])
        self.assertEqual(out[2]['voice_transcript'],'Секунду.')
        self.assertEqual(out[2]['transcript_origin'],'existing_ASR_not_listened_audio')

    def test_raw_lookup_validates_unhashable_model_arguments(self):
        for value in ([],{},None):
            with self.subTest(value=value),self.assertRaises(ResearchError):
                self.corpus().call('read_history',dict(case_id=value),self.current)

    def test_owner_lesson_exact_record_can_remain_but_raw_does_not_promote_itself(self):
        corpus=self.corpus();record=dict(id='owner',case_id='owner-rule',action='Не обещать материалы')
        corpus.reviewed_lesson_metadata={'owner':dict(record=copy.deepcopy(record),
            review=dict(source_kind='owner_correction',content_sha256=digest(record)))}
        self.assertEqual(corpus.filter_lessons([record],self.current),[record])
        self.assertEqual(corpus.filter_lessons([dict(record,action='Материалы есть')],self.current),[])
        self.assertEqual(corpus.filter_lessons([dict(id='raw',case_id='native-c')],self.current),[])

    def test_historical_lesson_needs_native_approved_identity_and_other_client(self):
        corpus=self.corpus();cid='2b681c82-99cc-43f5-8f05-a677a0910802';corpus.allowed.add(cid)
        record=dict(id='lesson',case_id=cid,action='Уточнить неизвестное')
        corpus.reviewed_lesson_metadata={'lesson':dict(record=record,
            review=dict(source_kind='reviewed_staff_case',content_sha256=digest(record)))}
        self.assertEqual(corpus.filter_lessons([record],self.current),[record])
        self.current['client_group']='native-'+cid
        self.assertEqual(corpus.filter_lessons([record],self.current),[])
        self.current['client_group']='other';self.identities.blocked.add(cid)
        self.assertEqual(corpus.filter_lessons([record],self.current),[])

    def test_native_mode_bypasses_legacy_example_search_and_filters_lessons(self):
        from extension_assistant import Assistant
        archive=Mock();snapshot=SimpleNamespace(archive=archive,version='v',archive_version='a',knowledge_version='k',
            lessons=lambda *a,**kw:[dict(id='old')])
        corpus=Mock();corpus.filter_lessons.return_value=[]
        service=SimpleNamespace(native_context=object(),corpus_factory=lambda:corpus)
        assistant=Assistant.__new__(Assistant);assistant.research=service
        result=assistant.experience_context(snapshot,self.current['messages'],dict(direction='mnc',title='Шкаф'),
            dict(next_question=dict(kind='scheme')),dict(),self.current['dialogue_id'],
            dict(sourceSnapshotSha256='h',sourceClientGroup='c',sourcePhoneHashes=[],sourceMediaHashes=[]))
        archive.search.assert_not_called();corpus.filter_lessons.assert_called_once()
        self.assertEqual(result['examples'],[]);self.assertEqual(result['lessons'],[])
        self.assertTrue(result['legacy_archive_search_bypassed'])


if __name__=='__main__':unittest.main()
