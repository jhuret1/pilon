"""Transparent fixture replay: no trained model and no network calls."""
import hashlib
import json
from importlib.resources import files
import numpy as np
from .identity import FAMILIES, normalized


def corpus():
    return json.loads(files('pilon').joinpath('data/synthetic-products.json').read_text(encoding='utf-8'))


class FixtureProvider:
    embedding_contract = 'fixture-hash-v1|1024|l2|float32'

    def __init__(self, store, rid, key):
        self.rows = {r['text']: r for item in corpus()['items'] for r in item['reviews']}

    def extract(self, text):
        if text not in self.rows:
            raise ValueError('Fixture replay only accepts the exact bundled synthetic texts.')
        return json.loads(json.dumps(self.rows[text]['expected_extractions']))

    def embed(self, texts):
        # Toy vectors exercise storage/routing only; NOT BGE or semantic representations.
        result = []
        for text in texts:
            v = np.zeros(1024, dtype=np.float32)
            for token in normalized(text).split():
                h = hashlib.sha256(token.encode()).digest()
                v[int.from_bytes(h[:2], 'little') % 1024] += 1 if h[2] % 2 else -1
            if not np.any(v):
                v[0] = 1
            result.append((v / np.linalg.norm(v)).tolist())
        return result

    def enrich(self, row, extraction, candidates, identity_only=False):
        a = extraction['attributes']
        match = next((f for f in candidates if normalized(f['definition']) == normalized(a['definition'])), None)
        return {'routing': {'choice': match['id'] if match else 'new_candidate',
                            'type': 'fixture_script', 'confidence': 1.0}}

    def classify_families(self, facts, families):
        registry = {f['name']: f['id'] for f in FAMILIES}
        definitions = {e['attributes']['definition']: e['attributes']['family']
                       for r in self.rows.values() for e in r['expected_extractions']}
        return [{'choice': registry.get(definitions.get(f['definition']), 'uncertain'),
                 'confidence': 1.0, 'type': 'fixture_script'} for f in facts]
