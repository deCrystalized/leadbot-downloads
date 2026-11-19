"""Additional frozen semantic reply boundaries; synthetic fixtures only."""
import unittest
import test_printer_stated_scope617_625 as _base

class PrinterReplyBoundaryTests(unittest.TestCase):
    setUp=_base.PrinterNativeTests.setUp
    prepare=_base.PrinterNativeTests.prepare
    finish=_base.PrinterNativeTests.finish
    def test_cover_operation_does_not_authorize_a_conversion_claim(self):
        out,task,c=self.prepare(_base.rows(_base.ADF))
        c['reply']='Это переделка типа принтера. '+c['reply']
        final=self.finish(out,c);self.assertFalse(final['reply'])
        self.assertIn('unrequested_printer_component_job',final['validation'])
    def test_dried_ink_does_not_authorize_cartridge_or_ciss_jobs(self):
        for claim in ['Нужно заменить картридж.','Нужно установить СНПЧ.']:
            out,task,c=self.prepare(_base.rows(_base.INK,('out','Марку и модель?'),'L366 Epson'))
            c['reply']=claim+' '+c['reply'];final=self.finish(out,c)
            self.assertFalse(final['reply']);self.assertIn('unrequested_printer_component_job',final['validation'])
    def test_negated_inference_is_not_a_component_order(self):
        out,task,c=self.prepare(_base.rows(_base.INK,('out','Марку и модель?'),'L366 Epson'))
        c['reply']='Засохшая краска не означает замену картриджа. '+c['reply']
        final=self.finish(out,c);self.assertEqual(final['validation'],[]);self.assertTrue(final['reply'])
