"""Bounded, revision-pinned public download. No dataset code is executed."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import requests
from .store import digest
from .corpus import rows
from .consolidation import atomic_json

DATASET = 'McAuley-Lab/Amazon-Reviews-2023'
TERMS = 'https://huggingface.co/datasets/' + DATASET + '/discussions/1'


def normalize(records, *, revision, category, offset=0):
    items, seen, order = {}, set(), []
    for index, record in enumerate(records, offset):
        text = record.get('text')
        iid = record.get('parent_asin') or record.get('asin')
        if not iid or not isinstance(text, str) or not text.strip():
            raise ValueError(f'Invalid product/text at source row {index}; no silent skip.')
        rid = 'amazon-' + digest([category, revision, index, text])[:24]
        if rid in seen:
            raise ValueError('Duplicate source record.')
        seen.add(rid)
        order.append(rid)
        item = items.setdefault(str(iid), dict(id=str(iid), title='Amazon product ' + str(iid), reviews=[]))
        # Reviewer identifiers, image URLs and profiles are deliberately excluded.
        item['reviews'].append(dict(id=rid, text=text, language='unknown',
                                   provenance=dict(source_row=index, source_text_hash=digest(text),
                                                   asin=record.get('asin'), timestamp=record.get('timestamp'),
                                                   rating=record.get('rating'), verified_purchase=record.get('verified_purchase'))))
    body = dict(schema_version='pilon-corpus-v1', synthetic=False, items=list(items.values()), source_order=order,
                provenance=dict(dataset=DATASET, revision=revision, category=category, offset=offset,
                                selection='contiguous prefix/slice; not a representative benchmark',
                                terms_url=TERMS, downloaded_at=datetime.now(timezone.utc).isoformat()))
    rows(body)
    body['provenance']['content_hash'] = digest(body['items'])
    return body


def download(output, *, limit=20, offset=0, category='Home_and_Kitchen', revision=None, session=None):
    if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
        raise ValueError('Use 1–100 reviews and offset 0–10000 for a bounded experiment.')
    if not re.fullmatch(r'[A-Za-z_]+', category):
        raise ValueError('Invalid category.')
    path = Path(output)
    if path.exists():
        raise ValueError('Output already exists; choose a new path to preserve provenance.')
    session = session or requests.Session()
    if revision is None:
        response = session.get('https://huggingface.co/api/datasets/' + DATASET, timeout=(10, 45))
        response.raise_for_status()
        revision = response.json()['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Expected an immutable 40-character dataset revision.')
    url = f'https://huggingface.co/datasets/{DATASET}/resolve/{revision}/raw/review_categories/{category}.jsonl'
    records, total = [], 0
    # Close as soon as the slice is obtained; never fetch the complete category.
    with session.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        response.encoding = 'utf-8'
        for index, line in enumerate(response.iter_lines(chunk_size=16384)):
            total += len(line)
            if total > 32 * 1024 * 1024:
                raise ValueError('Download exceeded 32 MiB; stopped before writing.')
            if index < offset:
                continue
            if line:
                records.append(json.loads(line))
            else:
                raise ValueError('Unexpected empty row; refusing to shift source offsets.')
            if len(records) == limit:
                break
    if len(records) != limit:
        raise ValueError('Source ended before the requested slice.')
    body = normalize(records, revision=revision, category=category, offset=offset)
    atomic_json(path, body)
    return body
