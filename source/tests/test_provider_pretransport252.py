"""No paid request after a stop/source change during pretransport fsync."""
import unittest
from unittest.mock import patch

from research_jobs import JobError,JobNotStarted
import test_research_jobs203 as fixtures


class ProviderPretransport252Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DurableResearchTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def check_stop(self, mutate):
        f=self.f
        original=f.jobs._save
        def save_then_change(path,raw):
            original(path,raw)
            if path.name.endswith('.request.json'):
                mutate()
        with patch.object(f.jobs,'_save',side_effect=save_then_change):
            with self.assertRaises(JobError) as stopped:
                f.reader()(f.payload(),120)
        self.assertEqual(f.calls,[])
        self.assertIsInstance(stopped.exception,JobNotStarted)
        state=f.jobs.status('owner',f.job)
        self.assertEqual(state['calls_spent'],1)  # Reserved, not a received bill.
        self.assertEqual(state['steps'][0]['state'],'not_started')
        self.assertFalse(state['steps'][0]['acknowledged'])
        self.assertFalse(f.jobs._file(f.job,'0.raw').exists())
        with self.assertRaises(JobNotStarted):
            f.reader()(f.payload(),120)
        self.assertEqual(f.calls,[])

    def test_cancel_while_saving_original_request_prevents_transport(self):
        self.check_stop(lambda:self.f.jobs.cancel('owner',self.f.job))

    def test_new_source_while_saving_original_request_prevents_transport(self):
        self.check_stop(lambda:self.f.current.update(revision='r2'))

    def test_original_deadline_while_saving_request_prevents_transport(self):
        self.check_stop(lambda:setattr(self.f,'now',1301))

    def test_series_stop_while_saving_request_prevents_transport(self):
        self.check_stop(lambda:self.f.jobs.stop_series('owner'))
