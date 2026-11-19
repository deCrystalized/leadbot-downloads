"""Private process-owner controller. No browser/model/action authority.

Fresh observer proofs stay inside ResearchService memory. A controller can
arm only exact binding hashes and a finite call budget, then admit or decide
the existing durable jobs. No customer operation or auto switch is exposed.
"""
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time

from research_openai import strict_loads

MAX_BYTES=32768


class Controller:
    def __init__(self,services,*,clock=time.time):
        self.services=services;self.clock=clock
        self.remaining=0;self.deadline=0;self.allowed=set();self.lock=threading.Lock()
        self.epochs={}

    @staticmethod
    def job_services(services):
        # Native actor views intentionally share the exact durable jobs/raw
        # directory. Decisions must identify that job once, while pending
        # admission discovery still visits every view's own identity cache.
        seen=set();result=[]
        for service in services:
            path=str(service.jobs.directory.resolve())
            if path not in seen:
                seen.add(path);result.append(service)
        return result

    def handle(self,value):
        if not isinstance(value,dict) or not isinstance(value.get('op'),str):raise ValueError('Exact controller command required')
        op=value['op'];services=list(self.services())
        if op!='arm' and any(self.epochs.get(id(s),s.control_failure_epoch)!=s.control_failure_epoch for s in services):
            with self.lock:self.allowed.clear();self.remaining=0;self.deadline=0
        if op=='pending' and set(value)=={'op'}:
            rows=[v for s in services for v in s.pending_metadata()]
            return dict(ok=True,pending=rows[:20],pending_total=len(rows),has_more=len(rows)>20,
                        calls_remaining=self.remaining,deadline=self.deadline,can_send_or_create=False)
        if op=='jobs' and set(value)=={'op','owner'} and isinstance(value['owner'],str) and value['owner']:
            rows=[]
            for service in self.job_services(services):
                with service.jobs.connect() as db:
                    for row in db.execute('SELECT jobs.id,grants.binding,jobs.state,jobs.result_hash,jobs.calls_spent '
                                          "FROM jobs JOIN grants ON grants.id=jobs.grant_id WHERE json_extract(grants.binding,'$.owner')=? ORDER BY jobs.updated DESC LIMIT 20",
                                          (value['owner'],)):
                        binding=json.loads(row['binding'])
                        if binding['owner']==value['owner']:
                            rows.append(dict(job=row['id'],state=row['state'],result_sha256=row['result_hash'],
                                calls_spent=row['calls_spent'],binding=binding,directory=str(service.jobs.directory)))
            return dict(ok=True,jobs=rows[:20],can_send_or_create=False)
        if op=='arm' and set(value)=={'op','bindings','max_calls','seconds'}:
            hashes=value['bindings'];calls=value['max_calls'];seconds=value['seconds']
            if (not isinstance(hashes,list) or not 1<=len(hashes)<=20 or len(hashes)!=len(set(hashes))
                    or any(not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in hashes)
                    or type(calls)is not int or not 1<=calls<=20 or type(seconds)is not int or not 1<=seconds<=1800):
                raise ValueError('Finite exact controller campaign required')
            current={v['binding_hash'] for s in services for v in s.pending_metadata()}
            if not set(hashes)<=current:raise ValueError('Campaign source is no longer pending')
            with self.lock:
                self.allowed=set(hashes);self.remaining=calls;self.deadline=self.clock()+seconds
                self.epochs={id(s):s.control_failure_epoch for s in services}
            return dict(ok=True,calls_remaining=calls,deadline=self.deadline,auto_enabled=False)
        if op=='admit' and set(value)=={'op','binding_hash','max_calls','seconds'}:
            binding=value['binding_hash'];calls=value['max_calls'];seconds=value['seconds']
            if type(calls)is not int or not 1<=calls<=20 or type(seconds)is not int or not 1<=seconds<=300:
                raise ValueError('Finite per-job admission required')
            with self.lock:
                if self.clock()+seconds>self.deadline or binding not in self.allowed or calls>self.remaining:
                    raise ValueError('No armed exact call budget')
                targets=[s for s in services if any(v['binding_hash']==binding for v in s.pending_metadata())]
                if len(targets)!=1:raise ValueError('Pending source identity is ambiguous or expired')
                grant=targets[0].admit_pending(binding,max_calls=calls,seconds=seconds)
                self.remaining-=calls;self.allowed.remove(binding)
            return dict(ok=True,grant_id=grant,calls_remaining=self.remaining,can_send_or_create=False)
        if op=='decide' and set(value)=={'op','owner','job','result_sha256','accepted','reviewer'}:
            if type(value['accepted'])is not bool or not isinstance(value['reviewer'],str) or not value['reviewer'].strip():
                raise ValueError('Exact manual decision required')
            targets=[]
            for service in self.job_services(services):
                try:service.jobs.status(value['owner'],value['job'])
                except ValueError:continue
                targets.append(service)
            if len(targets)!=1:raise ValueError('Exact owned job required')
            targets[0].jobs.decide(value['job'],value['result_sha256'],accepted=value['accepted'],reviewer=value['reviewer'])
            if not value['accepted']:
                with self.lock:self.allowed.clear();self.remaining=0;self.deadline=0
            return dict(ok=True,state='accepted' if value['accepted'] else 'denied',can_send_or_create=False)
        if op=='stop' and set(value)=={'op','owner'} and isinstance(value['owner'],str) and value['owner']:
            with self.lock:self.allowed.clear();self.remaining=0;self.deadline=0
            for service in self.job_services(services):service.jobs.stop_series(value['owner'])
            return dict(ok=True,calls_remaining=0,can_send_or_create=False)
        raise ValueError('Unadmitted controller operation or fields')


def peer_uid(connection):
    if hasattr(socket,'SO_PEERCRED'):
        return struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))[1]
    if hasattr(connection,'getpeereid'):return connection.getpeereid()[0]
    raise ValueError('Verified local peer credentials unavailable')


class Server:
    def __init__(self,path,controller):
        self.path=Path(path);self.controller=controller;self.socket=None;self.lock_fd=None;self.stop_event=threading.Event()

    def start(self):
        path=self.path
        if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('Private absolute controller socket required')
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        parent=path.parent.stat()
        if parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)!=0o700:
            raise ValueError('Private controller directory required')
        self.lock_fd=os.open(str(path)+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(self.lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)!=0o600):
            os.close(self.lock_fd);self.lock_fd=None
            raise ValueError('Private controller lock required')
        fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if path.exists():
            info=path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Foreign controller path')
            path.unlink()  # Exclusive process lock proves the old cooperating server is gone.
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.socket.bind(str(path));path.chmod(0o600);self.inode=path.stat().st_ino
        self.socket.listen(4);self.socket.settimeout(1)
        self.thread=threading.Thread(target=self._serve,name='research-root-control',daemon=True);self.thread.start()
        return self

    def _serve(self):
        while not self.stop_event.is_set():
            try:connection,_=self.socket.accept()
            except socket.timeout:continue
            except OSError:return
            with connection:
                connection.settimeout(5)
                try:
                    if peer_uid(connection)!=os.getuid():raise ValueError('Controller peer owner mismatch')
                    raw=b''
                    while not raw.endswith(b'\n'):
                        block=connection.recv(min(4096,MAX_BYTES+1-len(raw)))
                        if not block or len(raw)+len(block)>MAX_BYTES:raise ValueError('Incomplete/oversized controller frame')
                        raw+=block
                    if b'\n' in raw[:-1]:raise ValueError('Exactly one controller frame required')
                    value=self.controller.handle(strict_loads(raw))
                    result=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()+b'\n'
                    if len(result)>MAX_BYTES:raise ValueError('Bounded controller result required')
                except Exception:
                    result=b'{"ok":false,"code":"controller_rejected","can_send_or_create":false}\n'
                try:connection.sendall(result)
                except OSError:pass

    def close(self):
        self.stop_event.set()
        if self.socket is not None:self.socket.close()
        if self.path.exists() and self.path.lstat().st_ino==getattr(self,'inode',None):self.path.unlink()
        if self.lock_fd is not None:os.close(self.lock_fd);self.lock_fd=None
