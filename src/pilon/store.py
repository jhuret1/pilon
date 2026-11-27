import hashlib
import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Paused(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, data TEXT NOT NULL, fingerprint TEXT NOT NULL, batch TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, cache_key TEXT NOT NULL, stage TEXT NOT NULL,
                status TEXT NOT NULL, reserved REAL NOT NULL, cost REAL, started REAL NOT NULL, elapsed_ms REAL,
                request TEXT NOT NULL, response TEXT, error TEXT, UNIQUE(run_id,cache_key));
            CREATE INDEX IF NOT EXISTS calls_run ON calls(run_id);
            CREATE TABLE IF NOT EXISTS review_results(run_id TEXT NOT NULL, review_index INTEGER NOT NULL,
                phase TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,review_index));
            CREATE TABLE IF NOT EXISTS vectors(content_id TEXT PRIMARY KEY, signature TEXT NOT NULL,
                model TEXT NOT NULL, data BLOB NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def import_corpus(self, body):
        items = body.get('items') if isinstance(body, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError('Un lot doit contenir de 1 à 100 items dans le champ items.')
        batch = 'lot-' + digest(items)[:10]
        added = skipped = 0
        with self.db() as db:
            for item in items:
                if not isinstance(item, dict) or not item.get('id'):
                    raise ValueError('Identifiant de item manquant.')
                lid = str(item['id'])
                reviews = item.get('reviews')
                if not isinstance(reviews, list) or not reviews or len(reviews) > 2000:
                    raise ValueError('Chaque item doit avoir de 1 à 2 000 reviews.')
                seen = set()
                for review in reviews:
                    if not isinstance(review, dict) or not review.get('id') or not isinstance(review.get('text'), str) or not review['text'].strip():
                        raise ValueError('Review invalide : id et texte non vide requis.')
                    if str(review['id']) in seen:
                        raise ValueError('Identifiant de review dupliqué dans un item.')
                    seen.add(str(review['id']))
                    if len(review['text']) > 50000:
                        raise ValueError('Review de plus de 50 000 caractères : import refusé sans troncature.')
                canonical = {**item, 'id': lid}
                fp = digest(canonical)
                old = db.execute('SELECT fingerprint FROM items WHERE id=?', (lid,)).fetchone()
                if old:
                    if old['fingerprint'] != fp:
                        raise ValueError('Un item existant a un contenu différent : aucun écrasement automatique.')
                    skipped += 1
                else:
                    db.execute('INSERT INTO items VALUES(?,?,?,?)', (lid, dumps(canonical), fp, batch))
                    added += 1
        return {'added': added, 'skipped': skipped, 'batch': batch}

    def items(self):
        with self.db() as db:
            return [{**json.loads(r['data']), 'batch': r['batch']} for r in db.execute('SELECT * FROM items ORDER BY rowid')]

    def runs(self):
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM runs ORDER BY rowid DESC')]

    def run(self, rid):
        with self.db() as db:
            row = db.execute('SELECT data FROM runs WHERE id=?', (rid,)).fetchone()
            if not row:
                raise ValueError('Expérience introuvable.')
            return json.loads(row['data'])

    def save(self, run):
        with self.db() as db:
            current = db.execute('SELECT data FROM runs WHERE id=?', (run['id'],)).fetchone()
            if current:
                old = json.loads(current['data'])
                # A user pause wins over a worker checkpoint.
                if old['status'] == 'paused' and run['status'] == 'running':
                    run['status'] = 'paused'
            db.execute('UPDATE runs SET data=? WHERE id=?', (dumps(run), run['id']))

    def set_status(self, rid, status):
        with self.db() as db:
            row = db.execute('SELECT data FROM runs WHERE id=?', (rid,)).fetchone()
            if not row:
                raise ValueError('Expérience introuvable.')
            data = json.loads(row['data'])
            if data['status'] == 'completed':
                raise ValueError('Cette expérience est terminée.')
            if status == 'running':
                uncertain = db.execute("SELECT count(*) FROM calls WHERE run_id=? AND status!='succeeded' AND NOT (status='failed' AND cost=0 AND error LIKE 'OpenRouter HTTP 429%')", (rid,)).fetchone()[0]
                if uncertain:
                    raise ValueError('Un appel interrompu ou échoué nécessite un examen. Créez une nouvelle expérience pour réessayer ; aucune relance payante silencieuse.')
            data['status'] = status
            data['error'] = None
            db.execute('UPDATE runs SET data=? WHERE id=?', (dumps(data), rid))

    def create(self, config, rows, request_key, facts):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 100:
            raise ValueError('Identifiant de lancement invalide.')
        fp = digest({'config': config, 'rows': rows, 'facts': facts})
        with self.db() as db:
            old = db.execute('SELECT * FROM runs WHERE request_key=?', (request_key,)).fetchone()
            if old:
                if old['fingerprint'] != fp:
                    raise ValueError('Cet identifiant correspond à un autre lancement.')
                return json.loads(old['data'])
            rid = uuid.uuid4().hex[:12]
            data = {'id': rid, 'created': time.time(), 'status': 'queued', 'phase': 'extraction', 'config': config,
                    'input_hash': digest(rows), 'snapshot_hash': digest(facts), 'rows': rows, 'processed': 0,
                    'extractions': [], 'facts': [], 'base_facts': facts, 'groups_done': 0, 'error': None}
            db.execute('INSERT INTO runs VALUES(?,?,?,?)', (rid, request_key, fp, dumps(data)))
            return data

    def reserve(self, rid, cache_key, stage, amount, payload):
        with self.db() as db:
            previous = db.execute('SELECT * FROM calls WHERE run_id=? AND (cache_key=? OR cache_key GLOB ?) ORDER BY id DESC',
                                  (rid, cache_key, cache_key + ':retry:*')).fetchall()
            old = previous[0] if previous else None
            if old:
                if old['status'] == 'succeeded':
                    return old['id'], json.loads(old['response'])
                if old['status'] != 'failed' or old['cost'] != 0 or not (old['error'] or '').startswith('OpenRouter HTTP 429'):
                    raise Paused('Appel antérieur non confirmé ; relance automatique désactivée.')
                # Explicit resume only; preserve each uncharged rate-limit attempt.
                cache_key += ':retry:' + str(len(previous))
            run = json.loads(db.execute('SELECT data FROM runs WHERE id=?', (rid,)).fetchone()['data'])
            if run['status'] != 'running':
                raise Paused('Expérience en pause.')
            used = db.execute('SELECT coalesce(sum(coalesce(cost,reserved)),0) FROM calls WHERE run_id=?', (rid,)).fetchone()[0]
            if used + amount > run['config']['budget']:
                raise Paused('Budget réservé épuisé. Les résultats déjà obtenus sont conservés.')
            cur = db.execute('INSERT INTO calls(run_id,cache_key,stage,status,reserved,started,request) VALUES(?,?,?,?,?,?,?)',
                             (rid, cache_key, stage, 'pending', amount, time.time(), dumps(payload)))
            return cur.lastrowid, None

    def finish_call(self, cid, response, elapsed, error=None, uncharged=False):
        cost = (response or {}).get('usage', {}).get('cost')
        if isinstance(cost, bool) or not isinstance(cost, (float, int)) or not math.isfinite(cost) or cost < 0:
            cost = None
        if uncharged:
            cost = 0
        with self.db() as db:
            db.execute('UPDATE calls SET status=?,cost=?,elapsed_ms=?,response=?,error=? WHERE id=?',
                       ('failed' if error else 'succeeded', cost, elapsed, dumps(response) if response else None, error, cid))

    def calls(self, rid):
        with self.db() as db:
            return [{**dict(r), 'request': json.loads(r['request']), 'response': json.loads(r['response']) if r['response'] else None}
                    for r in db.execute('SELECT * FROM calls WHERE run_id=? ORDER BY id', (rid,))]

    def calls_brief(self,rid):
        # Never load large raw embedding responses just to refresh the dashboard.
        with self.db() as db:
            rows=db.execute('''SELECT id,run_id,stage,status,reserved,cost,started,elapsed_ms,error,
                json_extract(request,'$.model') AS model, json_extract(response,'$.model') AS actual_model,
                json_extract(response,'$.usage') AS usage FROM calls WHERE run_id=? ORDER BY id''',(rid,)).fetchall()
        return [{**dict(r),'request':{'model':r['model']},
                 'response':{'model':r['actual_model'],'usage':json.loads(r['usage'] or '{}')}} for r in rows]

    def recover(self):
        for run in self.runs():
            if run['status'] in ('running', 'queued'):
                run['status'] = 'interrupted'
                run['error'] = 'Serveur redémarré : reprise explicite nécessaire.'
                self.save(run)

    def review_result(self, rid, index):
        with self.db() as db:
            row = db.execute('SELECT * FROM review_results WHERE run_id=? AND review_index=?', (rid,index)).fetchone()
            return {'phase':row['phase'], 'extractions':json.loads(row['data'])} if row else None

    def save_review(self, rid, index, phase, extractions, run=None):
        """Commit the review and ontology checkpoint in one transaction."""
        with self.db() as db:
            old = db.execute('SELECT phase FROM review_results WHERE run_id=? AND review_index=?',(rid,index)).fetchone()
            if old and old['phase']=='completed' and phase!='completed':
                return
            db.execute('INSERT OR REPLACE INTO review_results VALUES(?,?,?,?)',(rid,index,phase,dumps(extractions)))
            if run is not None:
                current = json.loads(db.execute('SELECT data FROM runs WHERE id=?',(rid,)).fetchone()['data'])
                if current['status']=='paused':
                    run['status']='paused'
                db.execute('UPDATE runs SET data=? WHERE id=?',(dumps(run),rid))

    def extractions(self, rid):
        with self.db() as db:
            rows = db.execute("SELECT data FROM review_results WHERE run_id=? AND phase='completed' ORDER BY review_index",(rid,)).fetchall()
        return [e for row in rows for e in json.loads(row['data'])]

    def put_vector(self, text, vector, model='baai/bge-m3|1024|l2|float32'):
        import numpy as np
        v = np.asarray(vector,dtype='<f4')
        if v.shape != (1024,) or not np.isfinite(v).all() or not .99 < np.linalg.norm(v) < 1.01:
            raise ValueError('Vecteur BGE invalide.')
        cid = digest([model,text])
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO vectors VALUES(?,?,?,?)',(cid,text,model,v.tobytes()))
        return cid

    def vector(self, cid):
        import numpy as np
        with self.db() as db:
            row=db.execute('SELECT data FROM vectors WHERE content_id=?',(cid,)).fetchone()
        return np.frombuffer(row['data'],dtype='<f4').copy() if row else None
