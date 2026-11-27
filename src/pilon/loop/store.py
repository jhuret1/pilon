"""Local durable jobs, fenced leases and content-addressed stage checkpoints."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


class LeaseLost(RuntimeError):
    pass


def _duration(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
        raise ValueError('Lease duration must be finite and positive')


class Queue:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                    owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL, error TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS checkpoints (
                    job_id TEXT NOT NULL, stage TEXT NOT NULL, input_hash TEXT NOT NULL,
                    output_hash TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(job_id,stage));
                CREATE TABLE IF NOT EXISTS stage_cache (
                    input_hash TEXT PRIMARY KEY, output_hash TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
        finally:
            db.close()

    def enqueue(self, model, records, *, options=None, synthetic=False):
        payload = dict(model=deepcopy(model), records=deepcopy(list(records)), options=options or {}, synthetic=synthetic)
        fp = fingerprint(payload)
        now = time.time()
        with self.db() as db:
            old = db.execute("SELECT id FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
            if old:
                return old["id"]
            jid = "job_" + fp[:20]
            db.execute("INSERT INTO jobs(id,fingerprint,payload,status,stage,created,updated) VALUES(?,?,?,'queued','benchmark',?,?)",
                       (jid, fp, canonical(payload), now, now))
            self._event(db, jid, "enqueued", dict(input_hash=fp))
        return jid

    def _event(self, db, jid, kind, detail):
        db.execute("INSERT INTO events(job_id,at,kind,detail) VALUES(?,?,?,?)", (jid,time.time(),kind,canonical(detail)))

    def claim(self, *, owner=None, lease_seconds=60, job_id=None, now=None):
        _duration(lease_seconds)
        now = time.time() if now is None else now
        if type(now) not in (int,float) or not math.isfinite(now) or not math.isfinite(now+lease_seconds):
            raise ValueError('Lease timestamps must be finite')
        owner = owner or uuid.uuid4().hex
        with self.db() as db:
            sql = "SELECT * FROM jobs WHERE (status='queued' OR (status='running' AND lease_until<?))"
            params = [now]
            if job_id:
                sql += " AND id=?"; params.append(job_id)
            row = db.execute(sql+" ORDER BY created,id LIMIT 1",params).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',owner=?,lease_until=?,attempts=attempts+1,updated=?,error=NULL WHERE id=?",
                       (owner, now+lease_seconds, now, row["id"]))
            self._event(db,row["id"],"lease_reclaimed" if row["status"]=='running' else "claimed",dict(owner=owner))
            # Snapshot ownership before releasing the transaction. A later reclaim
            # must never give this worker its successor's fencing token.
            claimed=self._get(db,row['id'])
        return claimed

    @staticmethod
    def _fence(db, jid, owner):
        row = db.execute("SELECT owner,status,lease_until FROM jobs WHERE id=?",(jid,)).fetchone()
        if (not row or row['status']!='running' or row['owner']!=owner
                or row['lease_until'] is None or not math.isfinite(row['lease_until'])
                or row['lease_until'] < time.time()):
            raise LeaseLost("Worker lease expired or was reassigned; refusing stale writes")

    def heartbeat(self, jid, owner, lease_seconds=60):
        _duration(lease_seconds)
        with self.db() as db:
            self._fence(db,jid,owner)
            db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=?",(time.time()+lease_seconds,time.time(),jid))

    def get(self, jid):
        with self.db() as db:
            return self._get(db,jid)

    @staticmethod
    def _get(db,jid):
        row = db.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
        if not row:
            raise ValueError("Unknown background job")
        out = dict(row)
        out['payload']=json.loads(out['payload'])
        out['result']=json.loads(out['result']) if out['result'] else None
        out['events']=[dict(sequence=r['sequence'],at=r['at'],kind=r['kind'],detail=json.loads(r['detail']))
                       for r in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY sequence",(jid,))]
        return out

    def jobs(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT id,status,stage,created,updated,attempts,error FROM jobs ORDER BY created DESC,id")]

    def checkpoint(self, jid, stage):
        with self.db() as db:
            row = db.execute("SELECT * FROM checkpoints WHERE job_id=? AND stage=?",(jid,stage)).fetchone()
            if not row:
                return None
            data = json.loads(row['data'])
            if fingerprint(data) != row['output_hash']:
                raise ValueError("Corrupt stage checkpoint; explicit repair required")
            return dict(input_hash=row['input_hash'],data=data)

    def cached(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM stage_cache WHERE input_hash=?",(key,)).fetchone()
            if not row:
                return None
            result = json.loads(row['data'])
            if fingerprint(result)!=row['output_hash']:
                raise ValueError("Corrupt stage cache")
            return result

    def save_stage(self, jid, owner, stage, input_hash, result, *, cache_hit=False):
        data, output_hash = canonical(result), fingerprint(result)
        with self.db() as db:
            self._fence(db,jid,owner)
            old = db.execute("SELECT input_hash,output_hash FROM checkpoints WHERE job_id=? AND stage=?",(jid,stage)).fetchone()
            if old and (old['input_hash']!=input_hash or old['output_hash']!=output_hash):
                raise ValueError("Cannot overwrite a completed stage with different content")
            db.execute("INSERT OR IGNORE INTO checkpoints VALUES(?,?,?,?,?)",(jid,stage,input_hash,output_hash,data))
            db.execute("INSERT OR IGNORE INTO stage_cache VALUES(?,?,?)",(input_hash,output_hash,data))
            db.execute("UPDATE jobs SET stage=?,updated=? WHERE id=?",(stage,time.time(),jid))
            self._event(db,jid,'stage_reused' if cache_hit else 'stage_completed',dict(stage=stage,output_hash=output_hash))

    def finish(self, jid, owner, result, *, stage='projection'):
        if stage not in ('benchmark', 'projection'):
            raise ValueError('Invalid final stage')
        with self.db() as db:
            self._fence(db,jid,owner)
            db.execute("UPDATE jobs SET status='completed',stage=?,result=?,updated=?,owner=NULL,lease_until=NULL WHERE id=?",
                       (stage,canonical(result),time.time(),jid))
            self._event(db,jid,'completed',dict(published=False))

    def fail(self, jid, owner, error, *, retryable=False):
        with self.db() as db:
            self._fence(db,jid,owner)
            db.execute("UPDATE jobs SET status=?,error=?,updated=?,owner=NULL,lease_until=NULL WHERE id=?",
                       ('queued' if retryable else 'failed',str(error)[:500],time.time(),jid))
            self._event(db,jid,'interrupted' if retryable else 'failed',dict(error_type=type(error).__name__))

    def retry(self, jid):
        with self.db() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()
            if not row or row['status']!='failed':
                raise ValueError("Only failed jobs can be explicitly retried")
            db.execute("UPDATE jobs SET status='queued',error=NULL,updated=? WHERE id=?",(time.time(),jid))
            self._event(db,jid,'retry_requested',{})

    def event(self, jid, kind, detail):
        with self.db() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=?",(jid,)).fetchone():
                raise ValueError("Unknown job")
            self._event(db,jid,kind,detail)
