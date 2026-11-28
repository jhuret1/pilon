"""Optional local product-source index, separate from Benchmark's observed schema.

FTS5 shortlists descriptions; it neither extracts facts nor establishes absence.
No relevance labels, query/product pairs, remote calls or fabricated categories.
"""
import csv
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from time import perf_counter


def _hash(path):
    digest = sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def index_descriptions(csv_path, database, *, encoding='utf-8'):
    """Create a fingerprinted FTS index; an existing mismatched index is rejected."""
    database = Path(database)
    source_hash = _hash(csv_path)
    if database.exists():
        with closing(sqlite3.connect(database)) as db:
            manifest = json.loads(db.execute('SELECT value FROM metadata WHERE key=?', ('manifest',)).fetchone()[0])
            if manifest['source_sha256'] != source_hash or manifest['encoding'] != encoding:
                raise ValueError('Description source changed; choose a new index path')
            if db.execute('SELECT count(*) FROM documents').fetchone()[0] != manifest['documents']:
                raise ValueError('Incomplete description index')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Corrupt description index')
        return manifest
    database.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=database.name+'.', suffix='.tmp', dir=database.parent)
    os.close(fd)
    started = perf_counter()
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript('''
                CREATE TABLE documents (rowid INTEGER PRIMARY KEY, product_id TEXT UNIQUE NOT NULL,
                                        text TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE VIRTUAL TABLE search USING fts5(text, content='documents', content_rowid='rowid');
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            count = skipped = 0
            with Path(csv_path).open(encoding=encoding, newline='') as source:
                reader = csv.DictReader(source)
                if not {'product_uid','product_description'} <= set(reader.fieldnames or []):
                    raise ValueError('Expected Home Depot product descriptions')
                for row in reader:
                    pid, text = row['product_uid'], row['product_description']
                    if not pid.strip() or not text.strip():
                        skipped += 1
                        continue
                    digest = sha256(text.encode('utf-8')).hexdigest()
                    old = db.execute('SELECT sha256 FROM documents WHERE product_id=?', (pid,)).fetchone()
                    if old:
                        if old[0] != digest:
                            raise ValueError('Conflicting description for product '+pid)
                        continue
                    db.execute('INSERT INTO documents(product_id,text,sha256) VALUES (?,?,?)', (pid,text,digest))
                    count += 1
            db.execute("INSERT INTO search(search) VALUES ('rebuild')")
            if _hash(csv_path) != source_hash:
                raise ValueError('Description source changed during indexing')
            manifest = dict(dataset='Home Depot', source_file=Path(csv_path).name,
                            source_sha256=source_hash, encoding=encoding, documents=count, skipped_rows=skipped,
                            method='sqlite_fts5_bm25', purpose='source_shortlisting_only',
                            elapsed_seconds=perf_counter()-started, relevance_labels_used=False)
            db.execute('INSERT INTO metadata VALUES (?,?)', ('manifest',json.dumps(manifest)))
        os.replace(temporary, database)
        return manifest
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def route_assets(database, phrases, *, limit=30):
    """Find bounded source candidates. Unselected products remain unassessed."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Source shortlist limit must be between 1 and 500')
    if not isinstance(phrases, list) or not phrases or any(not isinstance(p,str) or not p.strip() for p in phrases):
        raise ValueError('Source routing requires search phrases')
    cleaned = [' '.join(re.findall(r'[^\W_]+', p, re.UNICODE)) for p in phrases]
    if any(not p for p in cleaned):
        raise ValueError('Empty searchable source phrase')
    query = ' OR '.join('"'+p+'"' for p in cleaned)
    started = perf_counter()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        manifest = json.loads(db.execute('SELECT value FROM metadata WHERE key=?', ('manifest',)).fetchone()[0])
        matched = db.execute('SELECT count(*) FROM search WHERE search MATCH ?', (query,)).fetchone()[0]
        rows = db.execute('''SELECT d.product_id,d.text,d.sha256,bm25(search) AS rank
                            FROM search JOIN documents d ON d.rowid=search.rowid
                            WHERE search MATCH ? ORDER BY rank,d.product_id LIMIT ?''', (query,limit)).fetchall()
    records = [dict(id='home_depot_description_'+r['product_id']+'_'+r['sha256'][:16],
                    product_id=r['product_id'], role='catalog', source='home_depot_product_description',
                    category='Home Depot', asset_type='text', text=r['text'], content_sha256=r['sha256'],
                    source_file=manifest['source_file'], source_sha256=manifest['source_sha256'],
                    retrieval_score=-r['rank']) for r in rows]
    routing = dict(method='sqlite_fts5_bm25', phrases=phrases, indexed_assets=manifest['documents'],
                   matching_assets=matched, selected_assets=len(records),
                   unassessed_outside_shortlist=manifest['documents']-len(records),
                   selected_record_ids=[r['id'] for r in records], limit=limit,
                   selection_recall='not_measured', elapsed_seconds=perf_counter()-started,
                   source_sha256=manifest['source_sha256'])
    return records, routing
