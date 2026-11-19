"""Approved history plus guarded raw native examples, with distinct authority.

No raw example becomes a reviewed lesson. The trusted selection mode chooses
experienced humans or labelled observed history; current client evidence and
privacy guards apply to both, and source length never supplies relevance.
"""
import copy
import hashlib
import json
import re
import uuid

from experienced_dialogues import digest
from research_sources import private_file, strict_json
from research_index import SourceExcluded
from research_pipeline import (Corpus, ResearchError, _client, _observed_replies, _private_body,
    _retrieval_facets, _requested_facets, _search_terms, _retrieval_rows,
    _COMMON_SEARCH, _BROAD_SEARCH, _role)
from source_protocol import SourceError

EXPERTS = {'Мамонтов Георгий','Скороход Илья','Востриков Глеб','Казахбаев Зухратдин'}


class ApprovedIdentities:
    def __init__(self,path,expected,protection,allowed):
        self.path,self.expected,self.protection,self.allowed=path,expected,protection,set(allowed)
        self.check()

    def check(self):
        raw=private_file(self.path,limit=12*1024*1024)
        if hashlib.sha256(raw).hexdigest()!=self.expected:raise SourceError('Approved source identities changed')
        value=strict_json(raw)
        if (not isinstance(value,dict) or value.get('schema')!=1 or set(value.get('approved_cids',()))!=self.allowed
                or set(value.get('headers',{}))!=self.allowed
                or value.get('protection_version')!=self.protection.version()
                or value.get('semantic_review_credit')!=0):
            raise SourceError('Exact identity-only approved source publication required')
        self.value=value
        return self.expected

    def header(self,cid):
        self.check()
        row=self.value['headers'][cid]
        if row.get('cid')!=cid or 'messages' in row:raise SourceError('Identity header is not source text')
        if row.get('deleted') or row.get('pending'):return None
        try:self.protection.header(row)
        except SourceExcluded:return None
        return row


def _bot(row):
    return (row.get('sender_type') in ('bot','assistant')
            or str(row.get('client_message_id')or'').startswith('lcp:'))


def _privacy_names(value):
    if value is None:return []
    if isinstance(value,str):return [value] if value else []
    if not isinstance(value,(list,tuple)) or any(not isinstance(name,str) for name in value):
        raise ResearchError('Typed history name metadata required')
    return list(value)


def private_history(source):
    rows=source['messages'];names=_privacy_names(source.get('metadata',{}).get('names',[]))
    rendered=[];run=[];hidden=set()
    for index,row in enumerate(rows+[{}]):
        text=str(row.get('body')or row.get('voice_transcript')or'')
        if _client(row) and re.fullmatch(r'[\d\s()+_.\-]+',text):run.append(index)
        else:
            if len(''.join(re.sub(r'\D','',str(rows[i].get('body')or rows[i].get('voice_transcript')or''))for i in run)) in (10,11):hidden.update(run)
            run=[]
    for index,row in enumerate(rows):
        body,redacted=_private_body(row.get('body')or row.get('text'),names)
        asr,asr_redacted=_private_body(row.get('voice_transcript'),names)
        if index in hidden:body='[часть номера скрыта]';asr='[часть номера скрыта]' if asr else '';redacted=True
        role=('service' if row.get('direction')in('system','note')or row.get('sender_type')in('system','avito')
              else 'bot' if _bot(row) else _role(row))
        rendered.append(dict(source_message_id=str(row.get('id')or'position-'+str(index+1)),position=index+1,
            source_role=role,
            delivery=row.get('delivery_status')or row.get('delivery')or'unknown',body=body,
            voice_transcript=asr,voice_transcript_status=row.get('voice_transcript_status')or'',
            transcript_origin='existing_ASR_not_listened_audio' if asr else None,
            assistant_generated=_bot(row),redacted=redacted or asr_redacted))
    return rendered


class HistoryCorpus(Corpus):
    def __init__(self,approved,index,identities,*,raw_history_enabled=True,raw_history_selection='experienced_humans'):
        if (type(raw_history_enabled) is not bool
                or type(raw_history_selection) is not str
                or raw_history_selection not in ('experienced_humans','all_observed')
                or raw_history_selection=='all_observed' and not raw_history_enabled):
            raise ResearchError('Explicit raw history capability required')
        # The approved factory makes a fresh Corpus per job. Reuse its native
        # source/rule/review machinery instead of creating another tool API.
        self.__dict__.update(approved.__dict__)
        # Source data may be shared; search/read authority belongs to this
        # wrapper and job, never to a previously used approved instance.
        self.hits,self.reads,self.searched,self.rule_reads={},{},set(),{}
        self.native_index,self.native_identities=index,identities
        self.raw_history_enabled=raw_history_enabled
        self.raw_history_selection=raw_history_selection
        self.native_version=index.state()['version']
        self.raw_hits={}
        self._revision_redaction_names={}
        self.initial=self.stamp()

    def stamp(self):
        state=self.native_index.state()
        if state.get('protection_unavailable'):
            raise ResearchError('Current source protection is unavailable; approved fallback is forbidden')
        return digest([super().stamp(),state['version'],self.native_identities.check(),
                       self.raw_history_enabled,self.raw_history_selection])

    def _catalog(self):
        result=[]
        for row in super()._catalog():
            identity=self.native_identities.header(row['cid'])
            if identity is None:continue
            if (self.raw_history_enabled and self.raw_history_selection=='all_observed'
                    and getattr(self,'_observed_current',None) is not None
                    and self.native_index.state()['healthy']):
                gate=self.native_index.reference_header(row['cid'],expected_version=self.native_version,
                                                       current=self._observed_current)
                if gate['present'] and not gate['eligible']:continue
            value=dict(row);metadata=json.loads(value['metadata'])
            metadata['phone_hashes']=sorted(set(metadata.get('phone_hashes',()))|set(identity['phone_hashes']))
            metadata['media_hashes']=identity['media_hashes']
            value.update(client_group=identity['client_group'],metadata=json.dumps(metadata,ensure_ascii=False))
            result.append(value)
        return result

    def _body(self,row):
        if self.native_identities.header(row['cid']) is None:raise ResearchError('Approved source identity revoked')
        return super()._body(row)

    def filter_lessons(self,records,current):
        """Filter existing approved memory; never promote raw history here."""
        self.check()
        result=[]
        phones,media=self._current_exclusions(current)
        check_observed=self.raw_history_enabled and self.raw_history_selection=='all_observed'
        for record in records:
            saved=getattr(self,'reviewed_lesson_metadata',{}).get(record.get('id'))
            if not saved or saved['record']!=record or not isinstance(saved.get('review'),dict):continue
            review=saved['review']
            if review.get('content_sha256')!=digest(record):continue
            if review.get('source_kind')=='owner_correction':
                result.append(record);continue
            cid=record.get('case_id')
            try:uuid.UUID(cid)
            except (ValueError,TypeError,AttributeError):continue
            if cid not in self.allowed:continue
            header=self.native_identities.header(cid)
            if (header is None or cid in (current.get('dialogue_id'),str(current.get('dialogue_id')).removeprefix('historical-root-'))
                    or header['client_group']==current.get('client_group')
                    or set(header['phone_hashes'])&phones or set(header['media_hashes'])&media):continue
            if check_observed:
                if not self.native_index.state()['healthy']:
                    continue
                gate=self.native_index.reference_header(cid,expected_version=self.native_version,
                                                        current=self._current_scope(current))
                if gate['present'] and not gate['eligible']:
                    continue
            result.append(record)
        self.check()
        return result

    def _current_scope(self,current):
        if not isinstance(current.get('dialogue_id'),str):
            raise ResearchError('Exact current dialogue identity required')
        phones,media=self._current_exclusions(current)
        return {'cid':current['dialogue_id'].removeprefix('historical-root-'),'client_group':current.get('client_group') or '',
                'phone_hashes':tuple(sorted(phones)),'media_hashes':tuple(sorted(media))}

    def _approved_revision_visible(self,cid,current):
        if cid not in self.allowed:
            return True
        identity=self.native_identities.header(cid)
        native=self._current_scope(current)
        return bool(identity is not None and cid!=native['cid']
            and identity['client_group']!=native['client_group']
            and not set(identity['phone_hashes'])&set(native['phone_hashes'])
            and not set(identity['media_hashes'])&set(native['media_hashes']))

    def ready(self,current):
        if not self.raw_history_enabled or self.raw_history_selection!='all_observed':
            return super().ready(current)
        scope=self.scope(current)
        hits={hit.get('native_source_cid',hit['case_id']) for hit in self.hits.get(scope,{}).values()}
        read={row.get('native_source_cid',row['case_id']) for row in self.reads.get(scope,{}).values()}
        return (scope in self.searched and bool(self.rule_reads.get(scope))
                and len(read&hits)>=min(2,len(hits)))

    def call(self,name,arguments,current):
        if not isinstance(arguments,dict):return super().call(name,arguments,current)
        if self.raw_history_enabled and self.raw_history_selection=='all_observed':
            self._observed_current=self._current_scope(current)
        scope=self.scope(current)
        previous_hits=dict(self.hits.get(scope,{}))
        if (self.raw_history_enabled and name=='read_history' and set(arguments)=={'case_id'} and isinstance(arguments.get('case_id'),str)
                and arguments['case_id'] in self.raw_hits.get(scope,{})):
            self.check();reference=arguments['case_id']
            hit=self.raw_hits[scope][reference]
            cid=hit.get('native_source_cid',reference)
            if not self._approved_revision_visible(cid,current):
                raise ResearchError('Approved source identity excludes this observed revision')
            value=self.native_index.read(cid,expected_version=self.native_version,current=self._current_scope(current))['source']
            if digest(value)!=hit['source_sha256']:raise ResearchError('Raw example changed after search')
            rendered_source=value
            names=self._revision_redaction_names.get(scope,{}).get(reference,[])
            if names:
                metadata=dict(value.get('metadata',{}))
                metadata['names']=[*_privacy_names(metadata.get('names',[])),*names]
                rendered_source=dict(value,metadata=metadata)
            result=dict(case_id=reference,source_sha256=hit['source_sha256'],full_case_read=True,
                messages=private_history(rendered_source),representation='full ordered source with explicit privacy redactions',
                authority='unreviewed historical example; current primary overrides it',source_direction_label='unverified',
                historical_route_verified=False,manual_review_verified=False,original_media_reviewed=False,
                proves_current_customer_facts=False,proves_call_or_order=False,weights_trained=False)
            if hit.get('source_provenance') is not None:
                result.update(source_provenance=hit['source_provenance'],
                    historical_errors_possible=True,automatic_lesson_promotion=False)
            for key in ('native_source_cid','native_source_revision','source_snapshot_kind',
                        'same_cid_approved_message_sha256'):
                if key in hit:result[key]=hit[key]
            self.check()
            self.reads.setdefault(scope,{})[reference]=copy.deepcopy(result)
            return copy.deepcopy(result)
        result=super().call(name,arguments,current)
        if (name=='read_history' and self.raw_history_enabled and self.raw_history_selection=='all_observed'):
            result.update(source_snapshot_kind='published_approved_archive',native_source_cid=arguments['case_id'],
                          native_source_revision=None)
            self.reads.setdefault(scope,{})[arguments['case_id']]=copy.deepcopy(result)
            return result
        if name!='search_history':return result
        if not self.raw_history_enabled:
            return dict(result,raw_archive_available=False,raw_archive_reason='approved_only_trusted_scope',
                        full_pool_verified=False)
        state=self.native_index.state()
        if not state['healthy']:
            return dict(result,raw_archive_available=False,raw_archive_reason='source_sync_unavailable',
                        full_pool_verified=False)
        if self.raw_history_selection=='all_observed':
            return self._observed_search(arguments,current,result,previous_hits,state)
        required=_requested_facets(arguments['query'],current['messages'],arguments['direction'])
        focus=set(_search_terms(arguments['query']))-_COMMON_SEARCH-_BROAD_SEARCH
        found=self.native_index.search(arguments['query'],expected_version=self.native_version,
            current=self._current_scope(current),limit=20,rank_mode='identity',match_mode='any')
        hits=list(result['hits'])
        for hit in found['hits']:
            cid=hit['cid']
            if cid in self.allowed or len(hits)>=3:continue
            source=self.native_index.read(cid,expected_version=self.native_version,current=self._current_scope(current))['source']
            rows=source['messages']
            if not any(_role(row)=='staff' and not _bot(row) and row.get('author') in EXPERTS
                       and (row.get('delivery_status')or row.get('delivery'))in('delivered','read') for row in rows):continue
            analysis=[dict(row,sender_type='bot')if _bot(row) else row for row in rows]
            facets=_retrieval_facets(analysis,arguments['direction'])
            if not required.issubset(facets):continue
            words=set().union(*(_search_terms(m.get('body')or m.get('voice_transcript')or'')
                                for m in _retrieval_rows(analysis) if _client(m)))-_COMMON_SEARCH
            if focus and not focus.intersection(words):continue
            added=dict(case_id=cid,source_sha256=digest(source),matched_facets=sorted(required),
                facet_evidence_ids={k:facets[k]for k in sorted(required)},semantic_match_verified=False,
                source_direction_label='unverified',historical_route_verified=False,
                source_authority='unreviewed_native_example',manual_review_verified=False)
            hits.append(added);self.raw_hits.setdefault(scope,{})[cid]=added
        self.hits.setdefault(scope,{}).update({hit['case_id']:hit for hit in hits})
        return dict(result,hits=hits,raw_archive_available=True,raw_records=state['records'],
                    raw_records_are_not_reviewed_lessons=True,full_pool_verified=False)

    def _observed_search(self,arguments,current,result,previous_hits,state):
        """Search the protected full index; bound body IO and disclose its limit."""
        scope=self.scope(current)
        required=_requested_facets(arguments['query'],current['messages'],arguments['direction'])
        focus=set(_search_terms(arguments['query']))-_COMMON_SEARCH-_BROAD_SEARCH
        wanted=set(_search_terms(arguments['query']))-_COMMON_SEARCH
        ranked=[]
        redaction_names={}
        def score(rows):
            words=set().union(*(_search_terms(m.get('body')or m.get('voice_transcript')or'')
                for m in _retrieval_rows(rows) if _client(m)))-_COMMON_SEARCH
            if focus and not focus.intersection(words):return None
            return len(wanted&words)/max(1,len(wanted))
        approved={row['cid']:row for row in self._catalog()}
        for hit in result['hits']:
            if hit['case_id'] not in approved:
                raise ResearchError('Approved source identity changed during ranking')
            rows=self._body(approved[hit['case_id']])
            value=score(rows)
            if value is not None:ranked.append((value,True,True,True,hit['case_id'],hit))
        seen:list[str]=[]
        examined=0;exhausted=False
        while len(seen)<100:
            found=self.native_index.search(arguments['query'],expected_version=self.native_version,
                current=self._current_scope(current),limit=min(20,100-len(seen)),
                rank_mode='bm25',match_mode='any',exclude_cids=tuple(seen),observed_only=True)
            page=found['hits']
            if not page:
                exhausted=True
                break
            for hit in page:
                cid=hit['cid']
                if cid in seen:raise ResearchError('Raw history pagination did not advance')
                seen.append(cid)
                if not self._approved_revision_visible(cid,current):continue
                source=self.native_index.read(cid,expected_version=self.native_version,
                    current=self._current_scope(current))['source'];examined+=1
                previous_sha=None
                reference=cid
                if cid in self.allowed:
                    old=approved.get(cid)
                    if old is None:raise ResearchError('Approved source disappeared during revision lookup')
                    previous_sha=old['source_sha256']
                    if digest(source['messages'])==previous_sha:continue
                    reference='observed-revision-'+digest([cid,source['source_revision'],digest(source)])
                    redaction_names[reference]=_privacy_names(json.loads(old['metadata']).get('names',[]))
                rows=source['messages']
                observed=_observed_replies(rows)
                if not observed or not any(_client(m) for m in rows):continue
                human=any(_role(m)=='staff' and not _bot(m) for m in observed)
                expert=any(not _bot(m) and m.get('author')in EXPERTS for m in observed)
                bot=any(_bot(m) for m in observed)
                analysis=[];asr_used=False
                for original in rows:
                    row=dict(original)
                    if _bot(row):row['sender_type']='bot'
                    if _client(row) and not str(row.get('body')or row.get('text')or'').strip():
                        transcript=row.get('voice_transcript')
                        if row.get('voice_transcript_status')=='done' and isinstance(transcript,str):
                            row['body']=transcript;asr_used=asr_used or bool(transcript.strip())
                        else:row['voice_transcript']=''
                    analysis.append(row)
                facets=_retrieval_facets(analysis,arguments['direction'])
                if not required.issubset(facets):continue
                value=score(analysis)
                if value is None:continue
                provenance={'delivered_human_staff':human,'delivered_bot':bot,
                    'experienced_human_observed':expert,'manual_review_verified':False,
                    'historical_errors_possible':True,'automatic_lesson_promotion':False,
                    'existing_ASR_used_for_retrieval':asr_used}
                added={'case_id':reference,'source_sha256':digest(source),'matched_facets':sorted(required),
                    'facet_evidence_ids':{k:facets[k]for k in sorted(required)},'semantic_match_verified':False,
                    'source_direction_label':'unverified','historical_route_verified':False,
                    'source_authority':'guarded_unreviewed_observed_history','manual_review_verified':False,
                    'source_provenance':provenance}
                if previous_sha is not None:
                    added.update(native_source_cid=cid,native_source_revision=source['source_revision'],
                        source_snapshot_kind='observed_native_revision',same_cid_approved_message_sha256=previous_sha)
                    provenance['reviewed_cid_does_not_review_this_revision']=True
                ranked.append((value,False,expert,human,reference,added))
        ranked.sort(key=lambda item:(-item[0],-item[1],-item[2],-item[3],item[4]))
        hits=[]
        alternate_versions=[]
        source_cids=set()
        for _,_,_,_,_,hit in ranked:
            cid=hit.get('native_source_cid',hit['case_id'])
            if cid in source_cids:
                alternate_versions.append(hit)
                continue
            source_cids.add(cid)
            hits.append(hit)
            if len(hits)==3:
                break
        hits=(hits+alternate_versions)[:3]
        selected={h['case_id']:h for h in hits}
        if len(selected)!=len(hits):raise ResearchError('Ambiguous observed history reference')
        self.hits[scope]={**previous_hits,**copy.deepcopy(selected)}
        self.raw_hits.setdefault(scope,{}).update(copy.deepcopy({cid:h for cid,h in selected.items()if cid not in self.allowed}))
        self._revision_redaction_names.setdefault(scope,{}).update(copy.deepcopy({
            key:names for key,names in redaction_names.items()if key in selected}))
        self.check()
        return dict(result,hits=hits,raw_archive_available=True,raw_records=state['records'],
            raw_records_are_not_reviewed_lessons=True,full_pool_verified=False,
            raw_history_selection=self.raw_history_selection,candidate_headers_examined=len(seen),
            candidate_bodies_examined=examined,candidate_scan_limit=100,search_exhausted=exhausted,
            search_truncated=not exhausted,ranking='client lexical coverage; reviewed/human preference on ties; not semantic proof')
