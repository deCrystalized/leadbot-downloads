"""Fresh server-run identity from the authenticated LeadChat reader.

This grants no model call, delivery or CRM operation. The research controller
still owns finite admissions and every existing source/action validation.
"""
import hashlib
import json
import uuid

from source_protocol import SourceError


class NativeAuthority:
    def __init__(self, client, *, owner, principal_id, current_versions):
        try:
            valid = isinstance(principal_id, str) and str(uuid.UUID(principal_id)) == principal_id
        except (ValueError, TypeError, AttributeError):
            valid = False
        if (not valid or not isinstance(owner, str) or not owner or not callable(current_versions)
                or not callable(getattr(client, 'run_authority', None))):
            raise SourceError('Trusted native owner and version reader required')
        self.client = client
        self.owner = owner
        self.principal_id = principal_id
        self.current_versions = current_versions

    def current(self, body):
        if (not isinstance(body, dict) or body.get('owner') != self.owner
                or not isinstance(body.get('native_run'), dict)
                or set(body.get('native_run', {})) != {'run_id', 'generation', 'operator_id'}
                or any(k in body for k in ('identity_proof', 'browser_session'))):
            raise SourceError('Separate native run authority required')
        run = body['native_run']
        actor = dict(principal_id=self.principal_id, operator_id=run['operator_id'])
        live = self.client.run_authority(run['run_id'], run['generation'], actor)
        versions = self.current_versions()
        if (not isinstance(versions, (tuple, list)) or len(versions) != 4
                or live['versions'] != list(versions)):
            raise SourceError('Native runtime, policy, map or reviewed memory changed')
        return live

    def identity(self, body):
        live = self.current(body)
        return dict(principal_id=live['principal_id'], operator_id=live['operator_id'],
                    execution_origin='leadchat_native_run', run_id=live['run_id'],
                    generation=live['generation'], mode=live['mode'])

    def launch_binding(self, body, *, require_auto=False):
        live = self.current(body)
        if require_auto and live['mode'] != 'auto':
            raise SourceError('Native rehearsal does not authorize automatic execution')
        # Launch versions fence a result, never create a new source-turn key.
        value = [self.owner, live['principal_id'], live['operator_id'], live['run_id'],
                 live['generation'], live['mode'], live['versions']]
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def auto_binding(self, body):
        return self.launch_binding(body, require_auto=True)
