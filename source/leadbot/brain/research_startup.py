"""Trusted startup factory; never configured by a browser or key autodetection.

The serving process must explicitly install this after approved dependencies
and source guards are supplied. A factory is not a paid-call admission. The
existing server currently leaves the registry disabled unless so configured.
"""
from dataclasses import dataclass
from pathlib import Path

import research_runtime
from experienced_dialogues import digest
from research_http import HTTPTransport
from research_pipeline import Corpus, models_for
from research_workflow import ResearchService


@dataclass(frozen=True)
class HTTPStartup:
    directory: Path
    key_file: Path
    shared_lock: Path
    enabled: bool = False
    network_enabled: bool = False
    profile: str = 'sol_only'
    allowed_cids: tuple = ()
    proposal_enabled: bool = False
    intake_form_enabled: bool = False
    owner_auto_enabled: bool = False
    auto_session_call_limit: int = 128
    native_execution_enabled: bool = False
    native_actions_enabled: bool = False
    native_office_enabled: bool = False
    native_notifications_enabled: bool = False
    native_crm_only_enabled: bool = False
    unique_replies_enabled: bool = False
    price_wording_enabled: bool = False

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.network_enabled) is not bool or type(self.proposal_enabled) is not bool or type(self.intake_form_enabled)is not bool
                or type(self.native_execution_enabled)is not bool or self.native_execution_enabled and not self.enabled
                or type(self.native_actions_enabled)is not bool
                or self.native_actions_enabled and (not self.native_execution_enabled or not self.owner_auto_enabled)
                or type(self.native_office_enabled)is not bool
                or self.native_office_enabled and (not self.native_actions_enabled or not self.intake_form_enabled)
                or type(self.native_notifications_enabled)is not bool
                or self.native_notifications_enabled and not self.native_office_enabled
                or type(self.native_crm_only_enabled)is not bool
                or type(self.unique_replies_enabled)is not bool
                or type(self.price_wording_enabled)is not bool
                or self.price_wording_enabled and (not self.proposal_enabled or self.profile != 'sol_only')
                or self.native_crm_only_enabled and (not self.native_office_enabled or self.native_notifications_enabled)
                or type(self.owner_auto_enabled)is not bool or type(self.auto_session_call_limit)is not int
                or not 4<=self.auto_session_call_limit<=4096
                or self.owner_auto_enabled and (not self.enabled or not self.network_enabled or self.profile!='sol_only')
                or any(not isinstance(p,Path) or not p.is_absolute() for p in
                       (self.directory,self.key_file,self.shared_lock))
                or not isinstance(self.allowed_cids,tuple)
                or any(not isinstance(cid,str) or not cid or len(cid)>200 for cid in self.allowed_cids)
                or len(set(self.allowed_cids))!=len(self.allowed_cids)
                or self.enabled and not self.allowed_cids):
            raise ValueError('Exact trusted startup paths, flags and source identities required')
        models_for(self.profile)


def configure_http(settings, *, corpus_factory=None, source_guard=None, identity=None,
                   media_resolver=None, schedule=None, connection_factory=None,native_context=None,native_schedule=None):
    if not isinstance(settings,HTTPStartup):
        raise ValueError('Only trusted typed startup settings are accepted')
    if not settings.enabled:
        research_runtime.configure(None)
        return dict(configured=False,network_enabled=False)
    if not callable(corpus_factory) or not callable(source_guard):
        raise ValueError('Approved corpus factory and development source guard are required')
    if settings.owner_auto_enabled and native_context is None:
        raise ValueError('Owner auto requires the authenticated native source dependency')
    if settings.native_execution_enabled and (native_context is None or identity is not None):
        raise ValueError('Native execution requires separate trusted current-source and Run authority')
    # Metadata identities checked BEFORE construction/hash or body access.
    source_guard(list(settings.allowed_cids))
    def corpus():
        source_guard(list(settings.allowed_cids))
        result=corpus_factory()
        if not isinstance(result,Corpus) or result.allowed!=set(settings.allowed_cids):
            raise ValueError('Startup corpus no longer matches approved source identities')
        return result
    def factory(store):
        options=dict(enabled=settings.network_enabled,profile=settings.profile)
        if connection_factory is not None:options['connection_factory']=connection_factory
        transport=HTTPTransport(settings.key_file,**options)
        return ResearchService(settings.directory/digest(str(Path(store.path).resolve())),
            shared_lock=settings.shared_lock,corpus_factory=corpus,request=transport,
            profile=settings.profile,identity=identity,media_resolver=media_resolver,schedule=schedule,
            proposal_enabled=settings.proposal_enabled,native_context=native_context,intake_form_enabled=settings.intake_form_enabled,
            owner_auto_enabled=settings.owner_auto_enabled,auto_session_call_limit=settings.auto_session_call_limit,
            native_crm_only_enabled=settings.native_crm_only_enabled,
            unique_replies_enabled=settings.unique_replies_enabled,
            price_wording_enabled=settings.price_wording_enabled)
    research_runtime.configure(factory)
    if settings.native_execution_enabled:
        from assistant_store import Store
        import native_execution,operator_identity
        store=Store()
        base=research_runtime.service(store)
        native_execution.configure(native_execution.Gateway(settings.directory/'native-execution',
            key=operator_identity.key,app_factory=native_execution.NativeApplications(store,base),schedule=native_schedule,
            actions_enabled=settings.native_actions_enabled,office_enabled=settings.native_office_enabled,
            notifications_enabled=settings.native_notifications_enabled))
    return dict(configured=True,network_enabled=settings.network_enabled,profile=settings.profile,
                authority='factory_only_no_grant_or_action',owner_auto_available=settings.owner_auto_enabled,
                native_server_run_available=settings.native_execution_enabled)
