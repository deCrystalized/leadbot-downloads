"""Preserve a price quotation by exact source ID, not a coincident number."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from assistant_store import Store
import research_form


class FormQuoteSource252Tests(unittest.TestCase):
    def stage(self, later):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(str(Path(directory)/'db'))
            quote=dict(id='price',direction='out',body='Работа — от 1000 рублей. Вас устраивает стоимость?')
            payload=dict(chat_id='synthetic',revision='revision',known={},facts={},messages=[
                dict(id='request',direction='in',body='Настроить компьютер.'),quote,
                dict(id='accept',direction='in',body='Да, устраивает.'),
                dict(id='later',direction='out',body=later)])
            value=dict(summary='Настроить компьютер.',works=[dict(status='requested',subject='Компьютер',
                evidence=[dict(quote='Настроить компьютер.')])])
            lead=dict(ad_identity='Синтетическое объявление',phone='synthetic',addr={'building':'1'},
                      visit_date='2099-01-01',visit_time='12:00',name='Иван',city='Чита')
            with patch.object(research_form,'_base_lead',return_value=lead):
                out=research_form.stage(store,'scope',payload,{'form':value},'job','binding')
            return out['form_extraction']['lead']['comment'],quote['body']

    def test_later_intercom_digits_cannot_replace_price_quote(self):
        comment,quote=self.stage('Уточните код домофона 1000, пожалуйста.')
        self.assertIn('Озвучка в переписке: «'+quote+'».',comment)
        self.assertNotIn('код домофона',comment)

    def test_later_device_model_digits_cannot_replace_price_quote(self):
        comment,quote=self.stage('Это модель HP1000?')
        self.assertIn('Озвучка в переписке: «'+quote+'».',comment)
        self.assertNotIn('HP1000',comment)

    def test_missing_exact_quote_source_stops_instead_of_selecting_matching_digits(self):
        with patch.object(research_form.assistant_prices,'consent',return_value={'amount':1000,'message_id':'missing'}):
            with self.assertRaisesRegex(ValueError,'quoted price source missing'):
                self.stage('Код домофона 1000.')
