"""Explicit process-owned API configuration, with no automatic paid admission.

An absent/disabled config leaves the existing provider untouched. An invalid
enabled config stops startup instead of silently falling back to another model.
No HTTP handler accepts this file, its paths, or a network-enable flag.
"""
import os
import hashlib
from pathlib import Path

from research_sources import ApprovedSources, SourceConfigurationError, private_file, strict_json
from research_startup import HTTPStartup, configure_http


def configure_server(path=None, **dependencies):
    if path is None:
        return configure_http(HTTPStartup(Path('/disabled/research'), Path('/disabled/key'),
                                          Path('/disabled/lock')))
    raw = private_file(path, limit=32_000)
    value = strict_json(raw)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value.get('schema') not in (1,2) or type(value.get('enabled')) is not bool:
        raise SourceConfigurationError('Trusted API configuration schema required')
    if value['enabled'] is False:
        if set(value) != {'schema', 'enabled'}:
            raise SourceConfigurationError('Disabled configuration accepts no provider fields')
        return configure_server()
    fields = {'schema', 'enabled', 'network_enabled', 'profile', 'directory', 'key_file',
              'shared_lock', 'sources_manifest', 'sources_sha256', 'proposal_enabled'}
    if 'intake_form_enabled'in value:fields.add('intake_form_enabled')
    for optional in ('owner_auto_enabled','auto_session_call_limit','native_execution_enabled','native_actions_enabled',
                     'native_office_enabled','native_notifications_enabled','native_crm_only_enabled',
                     'unique_replies_enabled','price_wording_enabled'):
        if optional in value:fields.add(optional)
    if value['schema']==2:
        fields |= {'native_url','native_protection','native_protection_sha256',
                   'native_identity_map','native_identity_map_sha256'}
        if 'native_history_scope' in value:fields.add('native_history_scope')
    if set(value) != fields:
        raise SourceConfigurationError('Unexpected trusted API configuration field')
    history_scope=value.get('native_history_scope','approved_and_unreviewed')
    if type(history_scope) is not str or history_scope not in (
            'approved_only','approved_and_unreviewed','approved_and_all_observed'):
        raise SourceConfigurationError('Exact trusted native history scope required')
    paths = {}
    for field in ('directory', 'key_file', 'shared_lock', 'sources_manifest') + (('native_protection','native_identity_map') if value['schema']==2 else ()):
        if not isinstance(value[field], str) or not value[field]:
            raise SourceConfigurationError('Absolute trusted API paths required')
        paths[field] = Path(value[field])
        if not paths[field].is_absolute():
            raise SourceConfigurationError('Absolute trusted API paths required')
    expected = hashlib.sha256(raw).hexdigest()
    def control():
        if hashlib.sha256(private_file(path, limit=32_000)).hexdigest() != expected:
            raise SourceConfigurationError('API control changed; existing admission revoked')
    sources = ApprovedSources(paths['sources_manifest'], value['sources_sha256'], control=control)
    settings = HTTPStartup(paths['directory'], paths['key_file'], paths['shared_lock'],
        enabled=True, network_enabled=value['network_enabled'], profile=value['profile'],
        allowed_cids=tuple(sorted(sources.allowed)), proposal_enabled=value['proposal_enabled'],
        intake_form_enabled=value.get('intake_form_enabled',False),
        owner_auto_enabled=value.get('owner_auto_enabled',False),auto_session_call_limit=value.get('auto_session_call_limit',128),
        native_execution_enabled=value.get('native_execution_enabled',False),
        native_actions_enabled=value.get('native_actions_enabled',False),
        native_office_enabled=value.get('native_office_enabled',False),
        native_notifications_enabled=value.get('native_notifications_enabled',False),
        native_crm_only_enabled=value.get('native_crm_only_enabled',False),
        unique_replies_enabled=value.get('unique_replies_enabled',False),
        price_wording_enabled=value.get('price_wording_enabled',False))
    # Startup checks the actual immutable publication once; every research job
    # constructs a fresh checked corpus and fences subsequent source changes.
    sources.corpus()
    corpus_factory=sources.corpus
    if value['schema']==2:
        from native_context import NativeContext
        from research_history import ApprovedIdentities,HistoryCorpus
        client,index=source_components(value,control=control)
        identities=ApprovedIdentities(paths['native_identity_map'],value['native_identity_map_sha256'],
                                     index.protection,sources.allowed)
        def corpus_factory():return HistoryCorpus(sources.corpus(),index,identities,
            raw_history_enabled=history_scope!='approved_only',
            raw_history_selection='all_observed' if history_scope=='approved_and_all_observed' else 'experienced_humans')
        corpus_factory()  # Fail closed before publishing the new factory.
        if 'native_context' in dependencies:
            raise SourceConfigurationError('Native source binding cannot be overridden')
        dependencies['native_context']=NativeContext(client,paths['directory']/'native-current')
    result = configure_http(settings, corpus_factory=corpus_factory,
                            source_guard=sources.guard, **dependencies)
    return dict(result, source_count=len(sources.allowed), source_authority=(
                ('approved_and_guarded_observed_staff_and_bot_history' if history_scope=='approved_and_all_observed'
                 else 'approved_and_guarded_unreviewed_native_history' if history_scope=='approved_and_unreviewed'
                 else 'approved_history_with_native_identity_guards_only') if value['schema']==2 else 'approved_history_not_raw_pool'),
                manual_root_required=True, automatic_grants=settings.owner_auto_enabled,
                automatic_scope='fresh_authenticated_owner_started_auto_only' if settings.owner_auto_enabled else None)


def source_components(value,*,control=lambda:None):
    """Read-only worker dependencies; never creates an API provider or grant."""
    from source_protection import SourceProtection
    from native_sources import NativeSources
    from research_index import DailyIndex
    import operator_identity
    if value.get('schema')!=2 or value.get('enabled') is not True:
        raise SourceConfigurationError('Explicit native source configuration required')
    control()
    protection=SourceProtection(Path(value['native_protection']),value['native_protection_sha256'])
    client=NativeSources(value['native_url'],key=operator_identity.key,
        header_guard=lambda header:(control(),protection.header(header))[1],
        cid_guard=lambda cids:(control(),protection.cids(cids))[1])
    def preflight(seconds=240):
        control()
        # This capability returns identity headers only. It does not call
        # client.history/image or admit any protected body to the consumer.
        return protection.verify_current_metadata(lambda cids,left:client._call('headers',dict(cids=cids),seconds=left)['headers'],seconds=seconds)
    client.protection_preflight=preflight
    index=DailyIndex(Path(value['directory'])/'native-history',source_instance='leadchat-native-reader-v1',
        guard=lambda header:(control(),protection.header(header))[1],
        guard_version=lambda:(control(),protection.version())[1])
    index.protection=protection
    return client,index


def configure_from_environment():
    name = os.environ.get('LEADBOT_RESEARCH_CONFIG')
    result=configure_server(Path(name) if name else None)
    path=os.environ.get('LEADBOT_RESEARCH_CONTROL_SOCKET')
    if path:
        if not result.get('configured'):raise SourceConfigurationError('Control socket requires an explicit API factory')
        import atexit,research_runtime
        from research_control import Server,Controller
        global _root_control
        _root_control=Server(Path(path),Controller(research_runtime.configured_services)).start()
        atexit.register(_root_control.close)
    return result
