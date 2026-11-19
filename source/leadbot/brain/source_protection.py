"""Pinned identity-only protection metadata, not access to final source bodies."""
import hashlib
import re
import time
from types import MappingProxyType

from research_sources import private_file, strict_json
from research_index import SourceExcluded
from source_protocol import SourceError


class SourceProtection:
    def __init__(self, path, expected):
        self.path, self.expected = path, expected
        self._read()

    def _read(self):
        raw = private_file(self.path, limit=12*1024*1024)
        checksum = hashlib.sha256(raw).hexdigest()
        if checksum != self.expected:
            raise SourceError('Source protection changed; existing access revoked')
        # Keep every current-file permission/race/hash check above. Only the
        # expensive parsing and validation of exactly the same pinned bytes
        # is reused, within this instance. Callers cannot mutate the result.
        cached = getattr(self, '_validated', None)
        if cached is not None and cached[0] == checksum:
            return cached[1]
        value = strict_json(raw)
        fields = {'schema','final_holdout_size','source_final_manifest_sha256',
                  'protected_cids','protected_identity_keys','protected_media_refs','media_reference_scan_complete'}
        if (not isinstance(value,dict) or set(value)!=fields or value['schema']!=1
                or value['final_holdout_size']!=1000 or len(value['protected_cids'])<1000
                or value['media_reference_scan_complete'] is not True):
            raise SourceError('Complete pinned protection metadata required')
        for key in ('protected_cids','protected_identity_keys','protected_media_refs'):
            items=value[key]
            if (not isinstance(items,list) or len(items)!=len(set(items))
                    or any(not isinstance(x,str) or not x or len(x)>200 for x in items)
                    or key!='protected_cids' and any(not re.fullmatch('[a-f0-9]{64}',x) for x in items)):
                raise SourceError('Invalid protection metadata identity')
        if not re.fullmatch('[a-f0-9]{64}',value['source_final_manifest_sha256']):
            raise SourceError('Pinned final metadata identity required')
        snapshot = dict(value)
        snapshot['protected_cids'] = tuple(value['protected_cids'])
        snapshot['protected_identity_keys'] = frozenset(value['protected_identity_keys'])
        snapshot['protected_media_refs'] = frozenset(value['protected_media_refs'])
        immutable = MappingProxyType(snapshot)
        self._validated = (checksum, immutable)
        return immutable

    def version(self):
        self._read()
        return self.expected

    def verify_current_metadata(self,read_headers,*,seconds=240):
        """Protected bodies stay unopened; new aliases revoke a raw scan."""
        if type(seconds)not in(int,float) or not 0<seconds<=300:
            raise SourceError('Finite protection metadata deadline required')
        deadline=time.monotonic()+seconds
        pinned=self._read();ids=pinned['protected_cids']
        keys=set(pinned['protected_identity_keys']);media=set(pinned['protected_media_refs'])
        observed=0
        for pos in range(0,len(ids),25):
            left=deadline-time.monotonic()
            if left<=0:raise SourceError('Protected metadata verification exceeded its deadline')
            batch=list(ids[pos:pos+25]);rows=read_headers(batch,left)
            if not isinstance(rows,list) or len(rows)!=len(batch):
                raise SourceError('Protected metadata freshness is unavailable')
            for cid,row in zip(batch,rows):
                if not isinstance(row,dict) or row.get('cid')!=cid or row.get('pending'):
                    raise SourceError('Protected metadata freshness is unavailable')
                if row.get('deleted'):continue
                if (not row.get('identity_keys') or not set(row['identity_keys'])<=keys
                        or not set(row.get('media_hashes',()))<=media):
                    raise SourceError('Protected source aliases changed; update protection before raw access')
                observed+=1
        self.version()
        if time.monotonic()>deadline:raise SourceError('Protected metadata verification exceeded its deadline')
        return dict(protected_headers_observed=observed,source_bodies_read=0,originals_read=0)

    def cids(self, values):
        protected=self._read()
        if not isinstance(values,list) or any(not isinstance(x,str) or not x for x in values):
            raise SourceError('Exact source CID list required')
        if set(values).intersection(protected['protected_cids']):
            raise SourceExcluded('Protected source identity; no development body access')
        return True

    def header(self, header):
        protected=self._read()
        if hasattr(header,'identity_keys'):
            header=vars(header)
        if not isinstance(header,dict) or not isinstance(header.get('cid'),str):
            raise SourceError('Trusted full source identity header required')
        self.cids([header['cid']])
        keys=header.get('identity_keys')
        if (not isinstance(keys,(list,tuple)) or not keys
                or any(not isinstance(x,str) or not re.fullmatch('[a-f0-9]{64}',x) for x in keys)):
            raise SourceError('Full identity-only source keys required before body')
        if (set(keys).intersection(protected['protected_identity_keys'])
                or header.get('client_group') in protected['protected_identity_keys']
                or set(header.get('media_hashes',())).intersection(protected['protected_media_refs'])):
            raise SourceExcluded('Protected source alias; no development body access')
        return True
