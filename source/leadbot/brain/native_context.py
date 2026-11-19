"""Current native source/original binding after the existing actor gate.

Browser message text/URLs are never the authority for this opt-in integration.
Source snapshots are private immutable evidence; no token or signing header is
written here. Fresh metadata and native permissions are checked on every gate.
"""
import copy
import os
import threading
import time
import secrets
from pathlib import Path

from experienced_dialogues import digest
from source_protocol import SourceError, encode, sha


class NativeContext:
    def __init__(self, client, directory, *, clock=time.time):
        self.client, self.clock = client, clock
        self.directory=Path(directory)
        if not self.directory.is_absolute() or any(p.is_symlink() for p in (self.directory,*self.directory.parents)):
            raise SourceError('Private current source directory required')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.directory.stat().st_uid!=os.getuid():raise SourceError('Private source owner mismatch')
        self.directory.chmod(0o700)
        self.snapshots={};self.bindings={};self.lock=threading.Lock()

    def _save(self, owner, header, source):
        raw=encode(dict(header=header,source=source))
        name=digest([owner,header['cid'],header['source_sha256']])+'.json'
        target=self.directory/name
        temporary=self.directory/('.source-'+secrets.token_hex(16))
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb',closefd=False) as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
        finally:os.close(fd)
        try:
            try:os.link(temporary,target,follow_symlinks=False)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes()!=raw:
                    raise SourceError('Immutable source evidence changed')
        finally:temporary.unlink()
        fd=os.open(self.directory,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def prepare(self, body, identity):
        if not isinstance(body.get('ctx'),dict) or not body.get('owner'):
            raise SourceError('Current owner and complete source context required')
        actor={k:identity[k] for k in ('principal_id','operator_id')}
        cid=body['ctx'].get('convId')
        if not isinstance(cid,str) or not cid:
            raise SourceError('Exact current conversation required')
        header=self.client.header(cid,actor)
        if header.get('deleted') or header.get('pending'):raise SourceError('Complete current source unavailable')
        key=(body['owner'],cid,header['source_sha256'],actor['principal_id'],actor['operator_id'])
        with self.lock:source=copy.deepcopy(self.snapshots.get(key))
        if source is None:
            source=self.client.history(header,actor)
            if not isinstance(source.get('messages'),list) or not source['messages']:
                raise SourceError('Complete current native source required')
            self._save(body['owner'],header,source)
            with self.lock:
                if len(self.snapshots)>=128:self.snapshots.pop(next(iter(self.snapshots)))
                self.snapshots[key]=copy.deepcopy(source)
        ctx=copy.deepcopy(body['ctx'])
        ctx['messages']=copy.deepcopy(source['messages'])
        metadata=source.get('metadata') or {}
        for key,field in (('assigneeId','assignee_id'),('claimedById','claimed_by_id'),
                          ('crmRequestId','crm_request_id'),('conversationStatus','status'),
                          ('itemTitle','title'),('accountId','account_id'),('channel','channel')):
            if field in metadata:ctx[key]=metadata[field]
        ctx.update(sourceAvailable=True,historyComplete=True,
                   sourceClientGroup=header['client_group'],
                   sourcePhoneHashes=list(header['phone_hashes']),
                   sourceMediaHashes=list(header['media_hashes']),
                   sourceSnapshotSha256=header['source_sha256'])
        # The actor-scoped header read rechecks current admin/author and
        # account take permission in the native reader. Browser booleans are
        # not evidence of either assignment or access to this source.
        ctx['assignmentKnown']=all(k in metadata for k in ('assignee_id','claimed_by_id'))
        ctx['channelAssigned']=metadata.get('channel')=='avito'
        ctx['botActive']=metadata.get('bot_active')
        ctx['hasTransfer']=bool(metadata['transfer_to_id']) if 'transfer_to_id' in metadata else None
        if 'account_title' in metadata:
            ctx.update(accountTitle=metadata['account_title'],partner=metadata.get('partner',''),
                       origin=metadata.get('origin',''),clientName=metadata.get('client_name',''))
            guessed=next((direction for label,direction in (('МНЧ','mnc'),('КП','kp'),('БТ','bt'))
                          if label in metadata['account_title'].upper()),'')
            if body.get('wording_mode')=='neural_auto' or ctx.get('dirBasis')!='operator':
                ctx.update(dir=guessed,dirBasis='account' if guessed else '')
            item=metadata.get('item') or {}
            ctx.update(itemTitle=item.get('title') or metadata.get('title',''),itemUrl=item.get('url') or '',
                       city=item.get('city_name') or '',cityRaw=item.get('city_name') or '',tz=item.get('city_tz') or '')
            linked=(metadata.get('phone_source_conversation_id')==cid or
                    metadata.get('client_link_confidence')=='confirmed') and not metadata.get('client_link_conflict')
            ctx.update(cardPhone=metadata.get('client_phone','') if linked else '',
                       link=dict(confidence=metadata.get('client_link_confidence',''),conflict=metadata.get('client_link_conflict') is True))
            # Address/LPR/visit are not verified by reading the current client
            # card. Use full source messages and the existing explicit guards.
            ctx.update(cardAddress={},cardAddressVerified=False)
        # A browser cannot turn these returned metadata into source authority:
        # each later gate repeats this authenticated native observation.
        result=dict(body,ctx=ctx)
        return result,header,actor

    def bind(self, owner, cid, revision, header, actor):
        key=(owner,cid,revision)
        with self.lock:
            self.bindings={k:v for k,v in self.bindings.items() if v['expires']>self.clock()}
            if len(self.bindings)>=128 and key not in self.bindings:self.bindings.pop(next(iter(self.bindings)))
            self.bindings[key]=dict(header=copy.deepcopy(header),actor=copy.deepcopy(actor),expires=self.clock()+45)

    def resolver(self, scope, descriptor):
        key=tuple(scope[k] for k in ('owner_id','dialogue_id','revision'))
        with self.lock:binding=copy.deepcopy(self.bindings.get(key))
        if not binding or binding['expires']<=self.clock():
            raise SourceError('Original image requires a fresh source/actor observation')
        result=self.client.image(binding['header'],descriptor,binding['actor'])
        # Native service rechecks full source after image IO, and the media
        # layer compares byte/MIME/hash against the original admitted pixels.
        return dict(scope,message_id=descriptor['message_id'],media_id=descriptor['media_id'],
                    attachment_hash=descriptor['attachment_hash'],**result)

    def image_digest(self, header, actor, descriptor):
        """Current authenticated original, not a browser hash or cached caption."""
        value=self.client.image(header,descriptor,actor)
        import hashlib
        if not isinstance(value.get('data'),bytes) or hashlib.sha256(value['data']).hexdigest()!=value.get('sha256'):
            raise SourceError('Original pixel digest is not verified')
        return value['sha256']
