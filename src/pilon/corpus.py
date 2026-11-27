"""Public data contract. Source strings and source order are never normalized away."""
import json
from pathlib import Path
from .store import digest


def load(path):
    body = json.loads(Path(path).read_text(encoding='utf-8'))
    return body


def rows(body):
    if not isinstance(body, dict) or body.get('schema_version') != 'pilon-corpus-v1':
        raise ValueError('Expected schema_version=pilon-corpus-v1.')
    result, item_ids, review_ids = [], set(), set()
    items = body.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('Expected 1–100 items in this alpha batch.')
    for item in items:
        iid = str(item.get('id', ''))
        if not iid or iid in item_ids:
            raise ValueError('Missing or duplicate item ID.')
        item_ids.add(iid)
        reviews = item.get('reviews')
        if not isinstance(reviews, list) or not 1 <= len(reviews) <= 2000:
            raise ValueError('Expected 1–2000 reviews per item.')
        for review in reviews:
            rid, text = str(review.get('id', '')), review.get('text')
            if not rid or rid in review_ids:
                raise ValueError('Missing or duplicate review ID in corpus.')
            if not isinstance(text, str) or not text.strip() or len(text) > 50000:
                raise ValueError('Review text must contain 1–50000 characters; no silent truncation.')
            review_ids.add(rid)
            result.append(dict(item_id=iid, item_title=item.get('title', iid), review_id=rid,
                               text=text, language=review.get('language', 'unknown'),
                               text_hash=digest(text), source_order=len(result),
                               provenance=review.get('provenance', {})))
    # Amazon imports can interleave products; retain original row order.
    if body.get('source_order'):
        order = body['source_order']
        if len(order) != len(result) or set(order) != review_ids:
            raise ValueError('source_order must list every review ID exactly once.')
        indexed = {r['review_id']: r for r in result}
        result = [{**indexed[rid], 'source_order': i} for i, rid in enumerate(order)]
    return result
