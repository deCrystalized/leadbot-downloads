import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from assistant_store import Store
import operator_identity as identity
import personal_assistant as personal
import assistant_policy
from extension_assistant import Assistant

KEY = 'public-unit-test-key-203-not-a-production-credential'
ACTOR = '11111111-1111-4111-8111-111111111111'
ADMIN = '22222222-2222-4222-8222-222222222222'


class OperatorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name + '/db')
        self.env = patch.dict(os.environ, {'LEADBOT_ACTOR_PROOF_KEY': KEY,
            'LEADBOT_PERSONAL_OWNER_ID': 'owner', 'LEADBOT_PERSONAL_OPERATOR_ID': 'george',
            'LEADBOT_PERSONAL_AUTO_AVAILABLE': '1'})
        self.env.start()
        self.body = {'operator_id': ACTOR, 'browser_session': 'device:tab:203'}
        self.challenge = identity.challenge(self.store, 'owner', self.body, 100)
        self.payload = {'v': 1, 'aud': 'leadbot-browser-operator', 'principal_id': ADMIN,
            'operator_id': ACTOR, 'principal_name': 'Administrator', 'operator_name': 'Operator',
            'role': 'admin', 'nonce': self.challenge['nonce'], 'sid': self.body['browser_session'],
            'iat': 100, 'exp': 145}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def proof(self, data=None, raw=None):
        raw = raw or json.dumps(data or self.payload, sort_keys=True, separators=(',', ':'))
        encoded = base64.urlsafe_b64encode(raw.encode()).rstrip(b'=')
        sig = base64.urlsafe_b64encode(hmac.new(KEY.encode(), encoded, hashlib.sha256).digest()).rstrip(b'=')
        return (encoded + b'.' + sig).decode()

    def body_with_proof(self, **extra):
        return {**self.body, 'identity_proof': self.proof(), **extra}

    def test_native_protocol_separates_author_and_principal_and_never_auto_starts(self):
        out = personal.session(self.store, 'owner', 'personal_start', self.body_with_proof(), now=101)
        self.assertTrue(out['active'])
        self.assertTrue(out['delegated'])
        self.assertEqual(out['principal_id'], ADMIN)
        self.assertEqual(out['operator_id'], ACTOR)
        self.assertEqual(out['owner_name'], 'Operator')
        self.assertFalse(out['auto_enabled'])
        self.assertNotIn(KEY, json.dumps(out))
        self.assertNotIn(self.proof(), json.dumps(out))

    def test_deployed_admin_requirement_preserves_review_but_denies_unattested_auto(self):
        with patch.dict(os.environ, {'LEADBOT_REQUIRE_ADMIN_AUTO':'1'}):
            body = {**self.body, 'operator_id':'george'}
            legacy = personal.session(self.store, 'owner', 'personal_start', body, now=101)
            self.assertTrue(legacy['active']);self.assertFalse(legacy['auto_available'])
            denied = personal.session(self.store, 'owner', 'personal_mode', {**body,
                'execution_mode':'auto','confirmed':True,'client_version':'2.8.18',
                'policy_ack':assistant_policy.VERSION,'activation_nonce':legacy['activation_nonce']}, now=102)
            self.assertFalse(denied['ok']);self.assertEqual(denied['code'],'admin_required')
            personal.session(self.store,'owner','personal_stop',body,now=103)
            admin = personal.session(self.store,'owner','personal_start',self.body_with_proof(),now=104)
            enabled = personal.session(self.store,'owner','personal_mode',{**self.body_with_proof(),
                'execution_mode':'auto','confirmed':True,'client_version':'2.8.18',
                'policy_ack':assistant_policy.VERSION,'activation_nonce':admin['activation_nonce']},now=105)
            self.assertTrue(enabled['auto_enabled'])

    def test_wrong_signatures_unsigned_json_and_jwt_are_rejected(self):
        for proof in (self.proof() + 'x', json.dumps(self.payload), 'eyJhbGciOiJIUzI1NiJ9.body.sig', '', None):
            with self.subTest(proof_type=type(proof).__name__):
                self.assertIsNone(identity.verify(self.store, 'owner', {**self.body, 'identity_proof': proof}, 101))

    def test_role_actor_principal_nonce_audience_and_fields_fail_closed(self):
        changes = [{'role': 'manager'}, {'operator_id': ADMIN}, {'principal_id': 'arbitrary-name'},
                   {'nonce': 'wrong'}, {'aud': 'leadchat-jwt'}, {'iat': True}, {'exp': 1000},
                   {'extra_admin': True}, {'operator_name': []}, {'sid': 'another:device:tab'}]
        for change in changes:
            with self.subTest(change=change):
                self.assertIsNone(identity.verify(self.store, 'owner',
                    self.body_with_proof(identity_proof=self.proof({**self.payload, **change})), 101))

    def test_expired_future_or_cross_owner_and_cross_browser_are_rejected(self):
        for now in (95, 145, 146):
            self.assertIsNone(identity.verify(self.store, 'owner', self.body_with_proof(), now))
        self.assertIsNone(identity.verify(self.store, 'other-owner', self.body_with_proof(), 101))
        self.assertIsNone(identity.verify(self.store, 'owner', self.body_with_proof(browser_session='other:tab:203'), 101))

    def test_new_challenge_invalidates_previous_binding(self):
        identity.challenge(self.store, 'owner', self.body, 101)
        self.assertIsNone(identity.verify(self.store, 'owner', self.body_with_proof(), 102))

    def test_duplicate_json_fields_are_rejected_even_if_signature_valid(self):
        raw = json.dumps(self.payload)[:-1] + ', "role":"admin"}'
        self.assertIsNone(identity.verify(self.store, 'owner',
            self.body_with_proof(identity_proof=self.proof(raw=raw)), 101))

    def test_key_absent_does_not_grant_admin_from_body_flags(self):
        with patch.dict(os.environ, {'LEADBOT_ACTOR_PROOF_KEY': ''}):
            self.assertFalse(identity.challenge(self.store, 'owner', self.body, 101)['ok'])
            self.assertIsNone(identity.verify(self.store, 'owner', self.body_with_proof(), 101))
            out = personal.session(self.store, 'owner', 'personal_start', {**self.body, 'role': 'admin'}, now=101)
            self.assertFalse(out['ok'])

    def test_legacy_operator_cannot_access_delegated_session(self):
        personal.session(self.store, 'owner', 'personal_start', self.body_with_proof(), now=101)
        legacy = {**self.body, 'operator_id': 'george'}
        self.assertFalse(personal.session(self.store, 'owner', 'personal_status', legacy, now=102)['active'])
        self.assertFalse(personal.session(self.store, 'owner', 'personal_stop', legacy, now=102)['ok'])

    def test_other_admin_or_actor_cannot_inherit_auto_lease(self):
        start = personal.session(self.store, 'owner', 'personal_start', self.body_with_proof(), now=101)
        activation = {**self.body_with_proof(), 'execution_mode': 'auto', 'confirmed': True,
                      'policy_ack': assistant_policy.VERSION, 'client_version': '2.8.18',
                      'activation_nonce': start['activation_nonce']}
        self.assertTrue(personal.session(self.store, 'owner', 'personal_mode', activation, now=102)['auto_enabled'])
        other = {**self.payload, 'principal_id': '33333333-3333-4333-8333-333333333333'}
        response = personal.session(self.store, 'owner', 'personal_status',
            self.body_with_proof(identity_proof=self.proof(other)), now=103)
        self.assertFalse(response['active'])
        self.assertFalse(response['auto_enabled'])

    def test_stop_reconnect_requires_new_explicit_activation(self):
        first = personal.session(self.store, 'owner', 'personal_start', self.body_with_proof(), now=101)
        personal.session(self.store, 'owner', 'personal_stop', self.body_with_proof(), now=102)
        second = personal.session(self.store, 'owner', 'personal_start', self.body_with_proof(), now=103)
        self.assertFalse(second['auto_enabled'])
        self.assertNotEqual(first['activation_nonce'], second['activation_nonce'])
        self.assertGreater(second['mode_epoch'], first['mode_epoch'])

    def test_admin_drafts_and_cache_are_bound_to_actual_principal_not_just_a_chat(self):
        now = int(time.time())
        challenge = identity.challenge(self.store, 'owner', self.body, now)
        data = {**self.payload, 'nonce':challenge['nonce'], 'iat':now, 'exp':now+45}
        app = Assistant(self.store)
        ctx = dict(convId='synthetic-actor203',dir='kp',city='Чита',channel='avito',partner='7',
            accountTitle='Иван КП',accountId='synthetic-account',itemTitle='Компьютерный мастер',
            adIdentity='Иван',origin='С1',messages=[dict(id='client',direction='in',body='Компьютер не включается, я в Чите.')])
        first_body = {**self.body, 'owner':'owner','action':'preview','ctx':ctx,'wording_mode':'reviewed',
                      'identity_proof':self.proof(data)}
        first, status = app.handle(first_body)
        self.assertEqual(status,200)
        self.assertEqual(first['operator_binding'],[ADMIN,ACTOR])
        other = {**data, 'principal_id':'33333333-3333-4333-8333-333333333333'}
        second_body = {**first_body,'identity_proof':self.proof(other)}
        second, status = app.handle(second_body)
        self.assertEqual(status,200)
        self.assertNotEqual(first['request_id'],second['request_id'])
        denied, _ = app.handle({**second_body,'action':'validate','draft_id':first['draft_id']})
        self.assertFalse(denied['ok'])
        legacy = {k:v for k,v in first_body.items() if k!='identity_proof'}
        denied, _ = app.handle({**legacy,'action':'validate','draft_id':first['draft_id']})
        self.assertFalse(denied['ok'])


if __name__ == '__main__':
    unittest.main()
