import math
import os
import time
from filelock import FileLock
from .store import Store, digest, Paused
from .pipeline import Engine, metrics
from .providers import OpenRouter, MODELS
from .fixture import FixtureProvider, corpus as fixture_corpus
from .corpus import rows
from .identity import ROUTING_VERSION, FAMILY_VERSION


def execute(db_path, body, *, provider='fixture', budget=0, allow_paid=False, request_key=None):
    if provider not in ('fixture', 'openrouter'):
        raise ValueError('Unknown provider.')
    if not math.isfinite(budget) or budget < 0:
        raise ValueError('Budget must be a finite nonnegative USD amount.')
    if provider == 'openrouter':
        if not allow_paid or not 0 < budget <= 10:
            raise ValueError('Paid runs require --allow-paid and --budget between 0 and 10 USD.')
        key = os.environ.get('OPENROUTER_API_KEY', '').strip()
        if not key:
            raise ValueError('Set OPENROUTER_API_KEY in your shell first.')
        factory = OpenRouter
    else:
        key, factory = '', FixtureProvider
        expected = {r['text'] for item in fixture_corpus()['items'] for r in item['reviews']}
        if not body.get('synthetic') or any(r['text'] not in expected for r in rows(body)):
            raise ValueError('The fixture provider only replays bundled synthetic review texts.')
    source_rows = rows(body)
    config = dict(purpose='canonical_corpus', signature='identity', routing_version=ROUTING_VERSION,
                  family_version=FAMILY_VERSION, embedding_contract=factory.embedding_contract,
                  provider=provider, models=MODELS if provider == 'openrouter' else {'all':'scripted-fixture'},
                  budget=budget, k=8, extraction_workers=3, corpus_provenance=body.get('provenance', {}))
    store = Store(db_path)
    request_key = request_key or 'run-' + digest([source_rows, config])
    with FileLock(str(store.path) + '.worker.lock', timeout=0):
        run = store.create(config, source_rows, request_key, [])
        if run['status'] == 'completed':
            return snapshot(store, run['id'])
        if run['status'] != 'queued':
            store.set_status(run['id'], 'running')  # refuses uncertain paid retries
            run = store.run(run['id'])
        else:
            run['status'] = 'running'
            store.save(run)
        try:
            Engine(store, key, provider_factory=factory).process(run)
        except (Paused, KeyboardInterrupt) as exc:
            run = store.run(run['id'])  # keep last atomic checkpoint, never a partial in-memory review
            run.update(status='paused', error=str(exc) or 'Interrupted by user.')
            store.save(run)
        except Exception as exc:
            run = store.run(run['id'])
            run.update(status='failed', error=type(exc).__name__ + ': step failed; retained checkpoints.')
            store.save(run)
            raise
    return snapshot(store, run['id'])


def snapshot(store, rid):
    run = store.run(rid)
    run['extractions'] = store.extractions(rid)
    run['metrics'] = metrics(run, store.calls_brief(rid))
    run['metrics']['wall_seconds'] = max(0, run.get('finished', time.time()) - run['created'])
    run['quality_notice'] = ('Scripted synthetic fixture replay; not an accuracy benchmark.' if run['config']['provider'] == 'fixture'
                             else 'Experimental induction. Exact spans do not validate extracted interpretations or values.')
    return run
