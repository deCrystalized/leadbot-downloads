"""Finite, restartable native archive synchronization; no model/customer actions.

The catalog is a daily full scan, not a timestamp feed. Content hashes detect
same-ID ASR edits. Private observation revisions are monotonic. A prepared page
is fsynced in SQLite before publication and replayed exactly after a crash.
"""
import fcntl
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager, closing
from pathlib import Path

from research_index import Header, Page, SourceExcluded, source_hash
from source_protocol import SourceError
from research_publication import Holds


class NativeExporter:
    def __init__(self, client, index, directory, *, shared_lock, clock=time.time,preflight=None):
        self.client,self.index,self.directory,self.shared_lock,self.clock=client,index,Path(directory),Path(shared_lock),clock
        if preflight is not None and not callable(preflight):raise SourceError('Trusted source preflight required')
        self.preflight=preflight
        if (not self.directory.is_absolute() or not self.shared_lock.is_absolute()
                or any(p.is_symlink() for p in (self.directory,*self.directory.parents,self.shared_lock,*self.shared_lock.parents))):
            raise SourceError('Private trusted exporter paths required')
        self.shared_lock.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock_parent=self.shared_lock.parent.stat()
        if lock_parent.st_uid!=os.getuid() or lock_parent.st_mode&0o022:
            raise SourceError('Shared provider lock needs an owned non-writable parent')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700);self.directory.chmod(0o700)
        if self.directory.stat().st_uid!=os.getuid():raise SourceError('Exporter owner mismatch')
        self.path=self.directory/'scan.sqlite3'
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd)
        if self.path.stat().st_uid!=os.getuid() or self.path.stat().st_nlink!=1:raise SourceError('Private scan journal required')
        self.path.chmod(0o600)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS seen(run TEXT,cid TEXT,PRIMARY KEY(run,cid));
                CREATE TABLE IF NOT EXISTS observed(cid TEXT PRIMARY KEY,fingerprint TEXT,revision INTEGER);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,event TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS prepared(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT);''')
            initial_scan: dict[str, object] = dict(
                run=None, page=[], after=None, complete=False, phase='scan',
                processed=0, last_completed=0, error=None,
            )
            # Another worker may advance the scan while this journal is opening.
            db.execute(
                'INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING',
                ('scan', json.dumps(initial_scan, sort_keys=True)),
            )

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            db.row_factory=sqlite3.Row
            with db:yield db

    @staticmethod
    def _get(db,key,default=None):
        row=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _put(db,key,value):
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,sort_keys=True,ensure_ascii=False)))

    def state(self):
        with self.db() as db:
            scan=self._get(db,'scan');pending=db.execute('SELECT count(*) FROM observed WHERE fingerprint LIKE ? ',('pending:%',)).fetchone()[0]
        return dict(scan,indexed=self.index.state()['records'],pending_original_or_source=int(pending),
                    authority='raw_unreviewed_examples',weights_trained=False,full_pool_verified=False)

    def _old(self,cid):
        with self.index.connect(True) as db:
            row=db.execute('''SELECT s.header,a.cid IS NOT NULL AS classified
                FROM sources s LEFT JOIN observed_history_admission a
                    ON a.cid=s.cid AND a.source_hash=s.source_hash
                WHERE s.cid=?''',(cid,)).fetchone()
            tomb=db.execute('SELECT revision FROM tombstones WHERE cid=?',(cid,)).fetchone()
        return (json.loads(row['header']) if row else None), (tomb[0] if tomb else 0), bool(row and row['classified'])

    def _advance(self,db,scan):
        scan['page']=scan['page'][1:];scan['processed']+=1;self._put(db,'scan',scan)

    def _plan(self,cid,scan):
        old,tomb,classified=self._old(cid)
        try:
            header=self.client.header(cid)
        except SourceExcluded:
            header=dict(cid=cid,excluded=True)
        reason=None
        if header.get('excluded'):reason='excluded'
        elif header.get('deleted'):reason='unobserved_or_deleted'
        elif header.get('pending') or header.get('identity_complete') is not True or not header.get('message_count'):
            reason='pending:original_or_complete_source'
        fingerprint=(reason or 'body')+':'+str(header.get('source_sha256') or self.index.guard_version())
        with self.db() as db:
            observed=db.execute('SELECT fingerprint,revision FROM observed WHERE cid=?',(cid,)).fetchone()
            prior=max(observed['revision'] if observed else 0,old.get('source_revision',0) if old else 0,tomb)
            revision=prior if observed and observed['fingerprint']==fingerprint else prior+1
            if reason and old is None:
                db.execute('INSERT OR REPLACE INTO observed VALUES(?,?,?)',(cid,fingerprint,revision))
                db.execute('INSERT INTO events(event,payload) VALUES(?,?)',(reason,json.dumps(dict(cid=cid))))
                self._advance(db,scan);return
            if not reason and old and observed and observed['fingerprint']==fingerprint:
                if classified:
                    self._advance(db,scan);return
                # Re-observe pre-upgrade rows through the ordinary trusted reader.
                revision=prior+1
        if reason:
            value=None
            item=Header(cid,revision,old['client_group'],tuple(old['phone_hashes']),tuple(old['media_hashes']),
                '',op='delete',identity_keys=tuple(old.get('identity_keys',())))
        else:
            source=self.client.history(header)
            value=dict(cid=cid,source_revision=revision,client_group=source['client_group'],
                phone_hashes=source['phone_hashes'],media_hashes=source['media_hashes'],
                identity_keys=source['identity_keys'],messages=source['messages'],
                metadata={**source['metadata'],'native_source_sha256':header['source_sha256'],
                          'export_observed_at':self.clock(),'authority':'unreviewed_native_example'})
            item=Header(cid,revision,source['client_group'],tuple(source['phone_hashes']),tuple(source['media_hashes']),
                source_hash(value),identity_keys=tuple(source['identity_keys']))
            self.index._record(item,value)  # Bounded full-source validation BEFORE preparing a commit.
        state=self.index.state()
        plan=dict(header=vars(item),source=value,expected_version=state['version'],after=state['cursor'],
            batch_id='native-'+scan['run']+'-'+str(scan['processed']),
            next_cursor='native:'+scan['run']+':'+str(scan['processed']),fingerprint=fingerprint,reason=reason)
        with self.db() as db:
            db.execute('INSERT INTO prepared VALUES(1,?)',(json.dumps(plan,ensure_ascii=False,sort_keys=True),))
            db.execute('INSERT INTO events(event,payload) VALUES(?,?)',('prepared',json.dumps(dict(cid=cid,revision=revision,source_hash=item.source_sha256))))

    def _publish(self,scan,*,after_publish=None):
        with self.db() as db:
            row=db.execute('SELECT value FROM prepared WHERE id=1').fetchone()
        if row is None:return True
        plan=json.loads(row[0]);data=plan['header']
        for name in ('phone_hashes','media_hashes','identity_keys'):data[name]=tuple(data.get(name,()))
        item=Header(**data)
        fd=os.open(self.shared_lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return False
            if Holds(self.shared_lock,clock=self.clock).active_jobs():return False
            page=Page(self.index.source_instance,plan['batch_id'],plan['after'],plan['next_cursor'],(item,))
            self.index.apply(page,lambda _:plan['source'],expected_version=plan['expected_version'])
            if after_publish:after_publish()
        finally:os.close(fd)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO observed VALUES(?,?,?)',(item.cid,plan['fingerprint'],item.source_revision))
            db.execute('DELETE FROM prepared WHERE id=1')
            db.execute('INSERT INTO events(event,payload) VALUES(?,?)',('published',json.dumps(dict(cid=item.cid,revision=item.source_revision,reason=plan['reason']))))
            self._advance(db,scan)
        return True

    def run(self,*,max_cases=100,max_seconds=60,force=False,after_publish=None):
        if type(max_cases)is not int or not 1<=max_cases<=1000 or type(max_seconds)not in (int,float) or not 0<max_seconds<=300:
            raise SourceError('Finite source synchronization budget required')
        fd=os.open(self.directory/'scan.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        deadline=time.monotonic()+max_seconds
        checking_protection=False
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return dict(self.state(),busy=True)
            with self.db() as db:scan=self._get(db,'scan')
            if scan['error']:raise SourceError('Source synchronization needs inspection before resuming')
            starting = scan['run'] is None
            if starting and not force and self.clock()-scan['last_completed']<86400:
                return dict(self.state(), not_due=True)
            # Revalidate protection before consuming any persisted work or
            # admitting a new catalog page.
            if self.preflight is not None:
                checking_protection = True
                self.preflight(max(0, deadline-time.monotonic()))
                checking_protection = False
            if starting:
                scan.update(run=secrets.token_hex(12),page=[],after=None,complete=False,phase='scan',processed=0)
                with self.db() as db:self._put(db,'scan',scan)
            processed=0
            while processed<max_cases and time.monotonic()<deadline:
                with self.db() as db:prepared=db.execute('SELECT 1 FROM prepared').fetchone()
                if prepared:
                    if not self._publish(scan,after_publish=after_publish):return dict(self.state(),waiting_for_model_lock=True)
                    processed+=1;continue
                if not scan['page']:
                    if scan['phase']=='prune':
                        scan.update(run=None,last_completed=self.clock(),phase='scan',after=None,complete=False)
                        with self.db() as db:self._put(db,'scan',scan)
                        break
                    if scan['complete']:
                        with self.db() as db:seen={r[0] for r in db.execute('SELECT cid FROM seen WHERE run=?',(scan['run'],))}
                        with self.index.connect(True) as db:existing={r[0] for r in db.execute('SELECT cid FROM sources')}
                        scan.update(page=sorted(existing-seen),phase='prune')
                        with self.db() as db:self._put(db,'scan',scan)
                        continue
                    page=self.client.catalog(scan['after'],100)
                    scan.update(page=page['cids'],after=page['next'],complete=page['complete'])
                    with self.db() as db:
                        db.executemany('INSERT OR IGNORE INTO seen VALUES(?,?)',((scan['run'],cid) for cid in scan['page']))
                        self._put(db,'scan',scan)
                    continue
                cid=scan['page'][0]
                if scan['phase']=='prune':
                    # A missing catalog observation removes the cached example;
                    # it is not a claim that a customer/CRM record was deleted.
                    old,tomb,_=self._old(cid)
                    if old:
                        item=Header(cid,max(old['source_revision'],tomb)+1,old['client_group'],tuple(old['phone_hashes']),
                            tuple(old['media_hashes']),'',op='delete',identity_keys=tuple(old.get('identity_keys',())))
                        state=self.index.state()
                        plan=dict(header=vars(item),source=None,expected_version=state['version'],after=state['cursor'],
                            batch_id='native-'+scan['run']+'-'+str(scan['processed']),next_cursor='native:'+scan['run']+':'+str(scan['processed']),
                            fingerprint='unobserved:'+scan['run'],reason='not_observed_in_catalog_scan')
                        with self.db() as db:db.execute('INSERT INTO prepared VALUES(1,?)',(json.dumps(plan,sort_keys=True),))
                    else:
                        with self.db() as db:self._advance(db,scan)
                    continue
                self._plan(cid,scan);processed+=1
            return self.state()
        except Exception as exc:
            # No implicit retry/partial-success claim after a common transport,
            # protection or publication fault. Prepared bytes remain recoverable.
            if 'scan' in locals() and not scan.get('error'):
                self.index.source_unavailable(protection=checking_protection)
                scan['error']=type(exc).__name__
                with self.db() as db:self._put(db,'scan',scan)
            raise
        finally:os.close(fd)
