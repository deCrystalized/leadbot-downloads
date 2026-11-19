"""Bounded volatile observer proofs. Nothing here persists or extends a proof.

Only the trusted service records freshly verified identity. An existing job
may renew that identity before expensive context assembly; it still must
revalidate the whole original context and binding before every worker use.
Every worker use must run the original verifier again (including challenge
revocation and expiry). A process restart has no proofs and needs a fresh
observer; job input and audit never contain them.
"""
import threading
import time


class ObserverProofs:
    def __init__(self, clock, limit=128):
        self.clock=clock
        self.limit=limit
        self._entries={}
        self._gaps={}
        self._anchors={}
        self._lock=threading.Condition()

    @staticmethod
    def _key(body):
        return tuple(str(body.get(k)or'') for k in ('owner','request_id','revision','browser_session','operator_id'))

    def remember(self, body, binding, identity, *, authority='full_context'):
        if authority not in ('full_context','identity_only_existing_job'):
            raise ValueError('Unknown observer authority')
        expiry=identity.get('exp')
        issued=identity.get('iat')
        if (type(expiry)is not int or type(issued)is not int
                or not 0<expiry-issued<=45 or not self.clock()<expiry or issued>self.clock()+3
                or not isinstance(body.get('identity_proof'),str) or not body.get('browser_session')):
            return
        key=self._key(body)
        with self._lock:
            self._entries={k:v for k,v in self._entries.items()if v['expires']>self.clock()}
            self._anchors={k:v for k,v in self._anchors.items()if v['deadline']>self.clock()}
            self._gaps={k:v for k,v in self._gaps.items()if k in self._entries or k in self._anchors}
            if key not in self._entries and len(self._entries)>=self.limit:
                evicted=next(iter(self._entries))
                self._entries.pop(evicted)
                self._gaps.pop(evicted,None)
            self._entries[key]=dict(proof=body['identity_proof'],expires=expiry,binding=binding,
                                    authority=authority)
            if key in self._anchors:self._anchors[key]['proof_expiry']=expiry
            if self._gaps.get(key,{}).get('proof')!=body['identity_proof']:
                self._gaps.pop(key,None)
            self._lock.notify_all()

    def anchor(self, body, binding, identity, *, job, deadline, launch=None):
        """Volatile exact-job identity, not a long-lived signed credential."""
        expiry,issued=identity.get('exp'),identity.get('iat')
        if (type(expiry)is not int or type(issued)is not int or not 0<expiry-issued<=45
                or not self.clock()<expiry or issued>self.clock()+3
                or type(deadline)not in(int,float) or not self.clock()<deadline<=self.clock()+300
                or not body.get('browser_session') or not identity.get('principal_id')):
            return
        key=self._key(body)
        with self._lock:
            self._anchors={k:v for k,v in self._anchors.items()if v['deadline']>self.clock()}
            if key not in self._anchors and len(self._anchors)>=self.limit:
                old=next(iter(self._anchors));self._anchors.pop(old);self._entries.pop(old,None);self._gaps.pop(old,None)
            self._anchors[key]=dict(key=key,job=job,binding=binding,principal=identity['principal_id'],deadline=deadline,launch=launch,proof_expiry=expiry)

    def wait_budget(self, original):
        with self._lock:
            anchor=self._anchors.get(self._key(original))
            # A 30s extension alarm can straddle proof expiry. This permits
            # waiting for a NEW valid signature, never using the expired one.
            return 35.0 if anchor and anchor['deadline']>self.clock()and anchor['proof_expiry']<=self.clock()+5 else 5.0

    def session_candidates(self, body, identity):
        with self._lock:
            self._anchors={k:v for k,v in self._anchors.items()if v['deadline']>self.clock()}
            return [dict(v)for k,v in self._anchors.items()
                    if k[0]==str(body.get('owner')or'') and k[3]==body.get('browser_session')
                    and k[4]==identity.get('operator_id') and v['principal']==identity.get('principal_id')]

    def body(self, original):
        with self._lock:
            value=self._entries.get(self._key(original))
            if value and value['expires']>self.clock():
                return dict(original,identity_proof=value['proof']),value['binding']
            if value:
                self._entries.pop(self._key(original),None)
            anchor=self._anchors.get(self._key(original))
            return original,anchor['binding']if anchor and anchor['deadline']>self.clock()else None

    def wait_for_observer(self, original, seconds):
        # Nonce rotation can invalidate the old proof just before the fresh
        # signed observer arrives. Wait without accepting the invalid proof
        # or performing another model/action step; caller bounds the wait by
        # the original job deadline and verifies the new proof again.
        key=self._key(original);old=original.get('identity_proof')
        with self._lock:
            if key in self._entries or self._anchors.get(key,{}).get('deadline',0)>self.clock():
                gap=self._gaps.get(key)
                if not gap or gap['proof']!=old:
                    gap=dict(proof=old,until=time.monotonic()+seconds)
                    self._gaps[key]=gap
                # Several final guards can encounter the same revoked proof.
                # They share one finite gap, rather than restarting the grace
                # after a failed model step or while preserving its result.
                remaining=min(seconds,max(0.0,gap['until']-time.monotonic()))
                self._lock.wait_for(lambda:bool(self._entries.get(key))and self._entries[key]['proof']!=old
                                    and self._entries[key]['expires']>self.clock(),timeout=remaining)
        return self.body(original)

    def discard(self, owner, request):
        with self._lock:
            self._entries={k:v for k,v in self._entries.items()if k[:2]!=(owner,request)}
            self._gaps={k:v for k,v in self._gaps.items()if k[:2]!=(owner,request)}
            self._anchors={k:v for k,v in self._anchors.items()if k[:2]!=(owner,request)}
            self._lock.notify_all()
