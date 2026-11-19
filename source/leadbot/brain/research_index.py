"""Guarded incremental raw-history cache, never automatic approved knowledge.

No exporter/network/scheduler is implicit. Identity headers from a trusted
exporter must be complete and checked before loading a body. An actual pool,
its identity completeness and the model-facing privacy adapter need separate
acceptance. This core only publishes validated local pages atomically.
"""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing, contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path

from experienced_dialogues import terms
from research_pipeline import _client, _observed_replies


MAX_PAGE = 100
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_PAGE_BYTES = 20 * 1024 * 1024
SCHEMA = 'raw_daily_history_v1'


class IndexFailure(ValueError):
    pass


class IndexConflict(IndexFailure):
    pass


class IndexBusy(IndexFailure):
    pass


class SourceExcluded(ValueError):
    """An explicit identity exclusion, distinct from unavailable protection."""


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def source_hash(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def _sha(value):
    return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) is not None


@dataclass(frozen=True)
class Header:
    cid: str
    source_revision: int
    client_group: str
    phone_hashes: tuple
    media_hashes: tuple
    source_sha256: str
    op: str = 'upsert'
    identity_complete: bool = True
    identity_keys: tuple = ()

    def validate(self):
        if (not isinstance(self.cid,str) or not self.cid or len(self.cid)>200
                or type(self.source_revision) is not int or self.source_revision<1
                or not isinstance(self.client_group,str) or not self.client_group or len(self.client_group)>200
                or self.op not in ('upsert','delete') or self.identity_complete is not True
                or any(not isinstance(items,tuple) or len(items)!=len(set(items)) or any(not _sha(x) for x in items)
                       for items in (self.phone_hashes,self.media_hashes,self.identity_keys))
                or self.op=='upsert' and not _sha(self.source_sha256)
                or self.op=='delete' and self.source_sha256!='' and not _sha(self.source_sha256)):
            raise IndexFailure('Complete trusted source identity header required')


@dataclass(frozen=True)
class Page:
    source_instance: str
    batch_id: str
    after: str | None
    next_cursor: str
    headers: tuple
    complete: bool = True


class DailyIndex:
    def __init__(self,directory,*,source_instance,guard,guard_version):
        if (not isinstance(source_instance,str) or not source_instance or len(source_instance)>200
                or not callable(guard) or not callable(guard_version)):
            raise IndexFailure('Trusted exporter identity and protection callbacks required')
        self.directory=Path(directory).absolute()
        if any(p.is_symlink() for p in [self.directory,*self.directory.parents]):
            raise IndexFailure('Private index directory cannot use symlinks')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.directory.stat().st_uid!=os.getuid():raise IndexFailure('Index owner mismatch')
        self.directory.chmod(0o700)
        self.path=self.directory/'daily.sqlite3'
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
                raise IndexFailure('Invalid private index file')
        finally:os.close(fd)
        self.path.chmod(0o600)
        self.source_instance,self.guard,self.guard_version=source_instance,guard,guard_version
        epoch=self._epoch()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(cid TEXT PRIMARY KEY,revision INTEGER NOT NULL,
                    source_hash TEXT NOT NULL,header TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observed_history_admission(
                    cid TEXT PRIMARY KEY, source_hash TEXT NOT NULL,
                    eligible INTEGER NOT NULL CHECK(eligible IN (0,1)));
                CREATE TABLE IF NOT EXISTS tombstones(cid TEXT PRIMARY KEY,revision INTEGER NOT NULL,reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,manifest TEXT NOT NULL,summary TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(cid UNINDEXED,text);
                CREATE TABLE IF NOT EXISTS failures(sequence INTEGER PRIMARY KEY,batch_id TEXT,manifest TEXT,category TEXT);''')
            db.execute('BEGIN IMMEDIATE')
            defaults=dict(schema=SCHEMA,source_instance=source_instance,cursor=None,generation=0,
                data_version=source_hash([SCHEMA,source_instance]),guard_version=epoch,healthy=True,pending_source_update=False,
                protection_unavailable=False)
            for key,value in defaults.items():
                db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',(key,encoded(value)))
            actual={row['key']:json.loads(row['value']) for row in db.execute('SELECT * FROM meta')}
            if actual['schema']!=SCHEMA or actual['source_instance']!=source_instance:
                raise IndexFailure('Index schema or trusted source instance changed')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='source_fts_refs'").fetchone() is None:
                db.execute('''CREATE TABLE source_fts_refs(
                    cid TEXT PRIMARY KEY, source_hash TEXT NOT NULL, fts_rowid INTEGER NOT NULL)''')
                # Old indexes have no row references. Ambiguous rows keep the
                # existing CID deletion path until an ordinary update replaces them.
                db.execute('''INSERT INTO source_fts_refs
                    SELECT f.cid,s.source_hash,min(f.rowid) FROM source_fts f
                    JOIN sources s ON s.cid=f.cid
                    GROUP BY f.cid,s.source_hash HAVING count(*)=1''')

    @contextmanager
    def connect(self,readonly=False):
        target=self.path.resolve().as_uri()+'?mode=ro' if readonly else str(self.path)
        with closing(sqlite3.connect(target,uri=readonly,timeout=3)) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA busy_timeout=3000')
            if not readonly:db.execute('PRAGMA synchronous=FULL')
            with db:yield db

    def _epoch(self):
        try:value=self.guard_version()
        except Exception:raise IndexFailure('Identity protection is unavailable') from None
        if not _sha(value):raise IndexFailure('Verified protection version required')
        return value

    def _allowed(self,header):
        header.validate()
        try:result=self.guard(header)
        except SourceExcluded:return False
        except Exception:raise IndexFailure('Identity protection is unavailable') from None
        if result is False:return False
        if result is not True:raise IndexFailure('Explicit source admission required')
        return True

    def _state(self,db):
        values={row['key']:json.loads(row['value']) for row in db.execute('SELECT * FROM meta')}
        values['records']=db.execute('SELECT count(*) FROM sources').fetchone()[0]
        values['version']=source_hash(values)
        values.update(authority='unreviewed_history_not_policy_or_lesson',full_pool_verified=False,
                      weights_trained=False)
        return values

    def state(self):
        with self.connect(True) as db:return self._state(db)

    def _fresh(self,state,expected_version):
        if state['version']!=expected_version:raise IndexConflict('Published index version changed')
        if not state['healthy'] or self._epoch()!=state['guard_version']:
            raise IndexFailure('Index needs verified synchronization or protection refresh')

    def _header(self,raw):
        value=json.loads(raw)
        value['phone_hashes']=tuple(value['phone_hashes']);value['media_hashes']=tuple(value['media_hashes'])
        value['identity_keys']=tuple(value.get('identity_keys', ()))
        header=Header(**value);header.validate();return header

    @contextmanager
    def writer(self):
        fd=os.open(self.directory/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise IndexBusy('The existing index publisher is active') from None
            yield
        finally:os.close(fd)

    def _failed(self,page,manifest):
        with self.connect() as db:
            db.execute("UPDATE meta SET value='false' WHERE key='healthy'")
            if page.headers:
                db.execute("UPDATE meta SET value='true' WHERE key='pending_source_update'")
            db.execute('INSERT INTO failures(batch_id,manifest,category) VALUES(?,?,?)',
                       (page.batch_id,manifest,'source_or_publication_failed'))

    def source_unavailable(self,*,protection=False):
        """Keep the last snapshot but fence reads after an exporter failure."""
        if type(protection)is not bool:raise IndexFailure('Exact protection failure flag required')
        with self.writer(), self.connect() as db:
            db.execute("UPDATE meta SET value='false' WHERE key='healthy'")
            db.execute("UPDATE meta SET value='true' WHERE key='pending_source_update'")
            if protection:db.execute("UPDATE meta SET value='true' WHERE key='protection_unavailable'")
            db.execute('INSERT INTO failures(batch_id,manifest,category) VALUES(?,?,?)',
                       ('native-export', '', 'native_source_observation_failed'))

    def _record(self,header,value):
        if not isinstance(value,dict) or source_hash(value)!=header.source_sha256:
            raise IndexFailure('Original source hash mismatch; no repair')
        if (value.get('cid')!=header.cid or type(value.get('source_revision')) is not int
                or value.get('source_revision')!=header.source_revision
                or value.get('client_group')!=header.client_group
                or value.get('phone_hashes')!=list(header.phone_hashes)
                or value.get('media_hashes')!=list(header.media_hashes)):
            raise IndexFailure('Source identities differ from admitted header')
        rows=value.get('messages')
        if not isinstance(rows,list) or not rows or len(rows)>5000 or any(not isinstance(m,dict) for m in rows):
            raise IndexFailure('A complete bounded original history is required')
        raw=encoded(value)
        if len(raw.encode())>MAX_SOURCE_BYTES:raise IndexFailure('Complete source exceeds budget; nothing truncated')
        text=[]
        for row in rows:
            if _client(row):
                body=row.get('body') or row.get('text') or ''
                transcript=row.get('voice_transcript') or ''
                if not isinstance(body,str) or not isinstance(transcript,str):raise IndexFailure('Invalid source text')
                text.append(body+' '+transcript)
        return raw,' '.join(terms(' '.join(text),limit=None))

    @staticmethod
    def _delete_fts(db,cid):
        ref=db.execute('''SELECT r.fts_rowid FROM source_fts_refs r
            JOIN sources s ON s.cid=r.cid AND s.source_hash=r.source_hash WHERE r.cid=?''',
            (cid,)).fetchone()
        # The old writer can leave a stale rowid after rollback. A matching
        # source version and CID are both required for the targeted deletion.
        if ref is None or db.execute('DELETE FROM source_fts WHERE rowid=? AND cid=?',
                (ref['fts_rowid'],cid)).rowcount!=1:
            db.execute('DELETE FROM source_fts WHERE cid=?',(cid,))

    def apply(self,page,load_body,*,expected_version,before_publish=None):
        if (not isinstance(page,Page) or page.source_instance!=self.source_instance
                or not isinstance(page.batch_id,str) or not page.batch_id or len(page.batch_id)>200
                or not callable(load_body)):
            raise IndexFailure('Trusted complete source page required')
        manifest=source_hash(asdict(page))
        with self.writer():
            with self.connect(True) as db:
                state=self._state(db)
                prior=db.execute('SELECT * FROM batches WHERE id=?',(page.batch_id,)).fetchone()
                if prior:
                    if prior['manifest']!=manifest:raise IndexConflict('Immutable batch identity changed')
                    return dict(json.loads(prior['summary']),replayed=True,state=state)
                if state['version']!=expected_version or page.after!=state['cursor']:
                    raise IndexConflict('Stale publication or watermark; no rewind')
            try:
                if (page.complete is not True or not isinstance(page.headers,tuple) or len(page.headers)>MAX_PAGE
                        or not isinstance(page.next_cursor,str) or not page.next_cursor or len(page.next_cursor)>512
                        or bool(page.headers) and page.next_cursor==page.after
                        or any(not isinstance(h,Header) for h in page.headers)
                        or len({h.cid for h in page.headers})!=len(page.headers)):
                    raise IndexFailure('Truncated, duplicate or unbounded source page')
                if state['pending_source_update'] and not page.headers:
                    raise IndexFailure('An empty page cannot certify recovery of a failed source update')
                for header in page.headers:header.validate()
                epoch=self._epoch();operations={};total=0
                counts=dict(upserted=0,deleted=0,excluded=0,stale=0,unchanged=0,protection_revoked=0)
                with self.connect(True) as db:
                    if epoch!=state['guard_version']:
                        for row in db.execute('SELECT cid,header FROM sources'):
                            header=self._header(row['header'])
                            if not self._allowed(header):
                                operations[header.cid]=(header,None,None,False,'excluded')
                                counts['protection_revoked']+=1
                    for header in page.headers:
                        admitted=self._allowed(header)
                        old=db.execute('SELECT revision,source_hash,header FROM sources WHERE cid=?',(header.cid,)).fetchone()
                        tomb=db.execute('SELECT revision FROM tombstones WHERE cid=?',(header.cid,)).fetchone()
                        revision=max(old['revision'] if old else 0,tomb['revision'] if tomb else 0)
                        if header.source_revision<revision or tomb and header.source_revision==tomb['revision'] and header.op=='upsert':
                            counts['stale']+=1;continue
                        if not admitted:
                            operations[header.cid]=(header,None,None,False,'excluded');counts['excluded']+=1;continue
                        if header.source_revision==revision:
                            if tomb and header.op=='delete':counts['unchanged']+=1;continue
                            if (old and header.op=='upsert' and old['source_hash']==header.source_sha256
                                    and old['header']==encoded(asdict(header))):
                                counts['unchanged']+=1;continue
                            raise IndexConflict('Same source revision has conflicting contents')
                        if header.op=='delete':
                            operations[header.cid]=(header,None,None,False,'deleted');counts['deleted']+=1;continue
                        value=load_body(header)
                        raw,text=self._record(header,value);total+=len(raw.encode())
                        if total>MAX_PAGE_BYTES:raise IndexFailure('Complete page exceeds budget; nothing cropped')
                        eligible=any(_client(row) for row in value['messages']) and bool(_observed_replies(value['messages']))
                        operations[header.cid]=(header,raw,text,eligible,'upsert');counts['upserted']+=1
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if self._state(db)['version']!=state['version'] or self._epoch()!=epoch:
                        raise IndexConflict('Source/protection changed before publication')
                    changes=[]
                    for cid,(header,raw,text,eligible,kind) in operations.items():
                        self._delete_fts(db,cid)
                        if kind=='upsert':
                            db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)',
                                (cid,header.source_revision,header.source_sha256,encoded(asdict(header)),raw))
                            fts_rowid=db.execute('INSERT INTO source_fts VALUES(?,?)',(cid,text)).lastrowid
                            db.execute('INSERT OR REPLACE INTO source_fts_refs VALUES(?,?,?)',
                                (cid,header.source_sha256,fts_rowid))
                            db.execute('INSERT OR REPLACE INTO observed_history_admission VALUES(?,?,?)',
                                (cid,header.source_sha256,int(eligible)))
                            db.execute('DELETE FROM tombstones WHERE cid=?',(cid,))
                        else:
                            current=db.execute('SELECT revision FROM sources WHERE cid=?',(cid,)).fetchone()
                            old=db.execute('SELECT revision FROM tombstones WHERE cid=?',(cid,)).fetchone()
                            highest=max(header.source_revision,current[0] if current else 0,old[0] if old else 0)
                            db.execute('DELETE FROM sources WHERE cid=?',(cid,))
                            db.execute('DELETE FROM source_fts_refs WHERE cid=?',(cid,))
                            db.execute('DELETE FROM observed_history_admission WHERE cid=?',(cid,))
                            db.execute('INSERT OR REPLACE INTO tombstones VALUES(?,?,?)',(cid,highest,kind))
                        changes.append([cid,header.source_revision,header.source_sha256,kind])
                    data_version=(source_hash([state['data_version'],changes,epoch])
                                  if changes or epoch!=state['guard_version'] else state['data_version'])
                    updates=dict(cursor=page.next_cursor,generation=state['generation']+1,
                                 data_version=data_version,guard_version=epoch,healthy=True,pending_source_update=False)
                    for key,value in updates.items():db.execute('UPDATE meta SET value=? WHERE key=?',(encoded(value),key))
                    if before_publish:before_publish()
                    if self._epoch()!=epoch:
                        raise IndexConflict('Protection changed at the final publication boundary')
                    summary=dict(**counts,replayed=False,published_data_version=data_version)
                    db.execute('INSERT INTO batches VALUES(?,?,?)',(page.batch_id,manifest,encoded(summary)))
                return dict(summary,state=self.state())
            except Exception:
                # Keep published rows/cursor; fence reads until a verified
                # recovery. Never include exporter exception text or a body.
                self._failed(page,manifest)
                raise IndexFailure('Index synchronization failed; old publication retained but unavailable') from None

    def _scope(self,current):
        if (not isinstance(current,dict) or set(current)-{'cid','client_group','phone_hashes','media_hashes'}
                or not isinstance(current.get('cid'),str) or not current['cid']
                or len(current['cid'])>200
                or current.get('client_group') is not None and not isinstance(current['client_group'],str)
                or any(not isinstance(current.get(k,()),(list,tuple)) or any(not _sha(x) for x in current.get(k,()))
                       for k in ('phone_hashes','media_hashes'))):
            raise IndexFailure('Exact current identity scope required')
        return current

    def _visible(self,header,current):
        return (header.cid!=current['cid'] and header.client_group!=current.get('client_group')
                and not set(header.phone_hashes)&set(current.get('phone_hashes',()))
                and not set(header.media_hashes)&set(current.get('media_hashes',())) and self._allowed(header))

    def search(self,query,*,expected_version,current,limit=5,rank_mode='bm25',match_mode='all',
               exclude_cids=(),observed_only=False):
        current=self._scope(current)
        if (not isinstance(query,str) or not query.strip() or len(query)>600
                or type(limit) is not int or not 1<=limit<=20 or rank_mode not in ('bm25','identity')
                or match_mode not in ('all','any') or type(observed_only) is not bool
                or not isinstance(exclude_cids,tuple) or len(exclude_cids)>100
                or any(not isinstance(cid,str) or not cid or len(cid)>200 for cid in exclude_cids)
                or len(set(exclude_cids))!=len(exclude_cids)):raise IndexFailure('Bounded search required')
        excluded=set(exclude_cids)
        wanted=terms(query,limit=None)
        if not wanted or len(wanted)>30:raise IndexFailure('Search terms exceed explicit budget')
        match=(' AND ' if match_mode=='all' else ' OR ').join('"'+word+'"' for word in wanted)
        with self.connect(True) as db:
            db.execute('BEGIN')
            state=self._state(db);self._fresh(state,expected_version)
            order='score,s.cid' if rank_mode=='bm25' else 's.cid'
            source_sql='''SELECT s.cid,s.header,bm25(source_fts) AS score FROM source_fts
                JOIN sources s ON s.cid=source_fts.cid'''
            where=' WHERE source_fts MATCH ?'
            if observed_only:
                # Old revisions without an admission verdict retain the guarded
                # body check until the exporter observes them again.
                source_sql+=''' LEFT JOIN observed_history_admission a
                    ON a.cid=s.cid AND a.source_hash=s.source_hash'''
                where+=' AND (a.cid IS NULL OR a.eligible=1)'
            rows=db.execute(source_sql+where+' ORDER BY '+order,(match,))
            hits=[]
            for row in rows:
                header=self._header(row['header'])
                if self._visible(header,current) and header.cid not in excluded:
                    hits.append(dict(cid=header.cid,source_revision=header.source_revision,source_sha256=header.source_sha256,
                                     semantic_match_verified=False,historical_route_verified=False))
                    if len(hits)==limit:break
            self._fresh(state,expected_version)
        return dict(hits=hits,state=state,full_histories_read=False,full_pool_verified=False)

    def reference_header(self,cid,*,expected_version,current):
        """Admission only, including tombstones; never load source payload."""
        current=self._scope(current)
        if not isinstance(cid,str) or not cid or len(cid)>200:
            raise IndexFailure('Exact source identity required')
        with self.connect(True) as db:
            db.execute('BEGIN')
            state=self._state(db);self._fresh(state,expected_version)
            row=db.execute('SELECT header FROM sources WHERE cid=?',(cid,)).fetchone()
            if row is not None:
                header=self._header(row['header'])
                result={'present':True,'eligible':self._visible(header,current),
                        'source_revision':header.source_revision,'tombstone':False}
            else:
                tomb=db.execute('SELECT revision FROM tombstones WHERE cid=?',(cid,)).fetchone()
                result={'present':tomb is not None,'eligible':False if tomb is not None else None,
                        'source_revision':tomb['revision'] if tomb is not None else None,'tombstone':tomb is not None}
            self._fresh(state,expected_version)
        return result

    def read(self,cid,*,expected_version,current):
        current=self._scope(current)
        if not isinstance(cid,str) or not cid or len(cid)>200:raise IndexFailure('Exact source identity required')
        with self.connect(True) as db:
            db.execute('BEGIN')
            state=self._state(db);self._fresh(state,expected_version)
            row=db.execute('SELECT header FROM sources WHERE cid=?',(cid,)).fetchone()
            if not row:raise IndexFailure('Source is absent or revoked')
            header=self._header(row['header'])
            if not self._visible(header,current):raise IndexFailure('Source is excluded for this current identity')
            # Metadata admission precedes even loading the stored JSON body.
            raw=db.execute('SELECT payload FROM sources WHERE cid=?',(cid,)).fetchone()[0]
            value=json.loads(raw);self._record(header,value);self._fresh(state,expected_version)
        return dict(source=value,state=state,authority='unreviewed_history_not_policy_or_lesson',
                    full_text_read=True,original_media_reviewed=False,semantic_match_verified=False,
                    historical_route_verified=False,weights_trained=False)
