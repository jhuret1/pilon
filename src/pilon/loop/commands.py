"""CLI for demand-led background enrichment, explicit model publication and rollback."""
import argparse
from itertools import chain
import json
import math
from pathlib import Path
import time

from ..facets.io import read_signals,write_text
from .store import Queue
from .worker import run_once,report


def configure(parser):
    sub=parser.add_subparsers(dest='loop_command',required=True)
    demo=sub.add_parser('demo',help='Run a fictional background cycle and save the cockpit')
    demo.add_argument('--new-source',action='store_true',help='Add an insole source to satisfy a previously unanswered demand')
    demo.add_argument('--html',type=Path,default=Path('runtime/background-loop.html'))
    demo.add_argument('--output',type=Path,default=Path('runtime/background-loop.json'))
    enqueue=sub.add_parser('enqueue',help='Freeze model and source inputs as an idempotent job')
    enqueue.add_argument('--model',type=Path,required=True)
    enqueue.add_argument('--signals',required=True,action='append')
    enqueue.add_argument('--top-k',type=int,default=50)
    enqueue.add_argument('--exhaustive',action='store_true')
    watch=sub.add_parser('watch',help='Watch local source exports and enqueue a new snapshot only when content changes')
    watch.add_argument('--model',type=Path,required=True)
    watch.add_argument('--signals',required=True,action='append')
    watch.add_argument('--top-k',type=int,default=50)
    watch.add_argument('--exhaustive',action='store_true')
    watch.add_argument('--once',action='store_true')
    watch.add_argument('--poll-seconds',type=float,default=10)
    for p in (enqueue,watch):
        p.add_argument('--geometry',action='store_true',help='Inspect supplied compatible vectors without changing extraction')
    revisit=sub.add_parser('revisit',help='Reuse retained demand and add new immutable source records')
    revisit.add_argument('job_id')
    revisit.add_argument('--signals',required=True,action='append')
    revisit.add_argument('--model',type=Path,help='Optional newer model snapshot; previous model is the default')
    work=sub.add_parser('work',help='Background worker; completed stages are not recomputed')
    work.add_argument('--once',action='store_true')
    work.add_argument('--job')
    work.add_argument('--lease-seconds',type=float,default=60)
    work.add_argument('--poll-seconds',type=float,default=2)
    view=sub.add_parser('report',help='Export a checkpointed job snapshot')
    view.add_argument('job_id');view.add_argument('--html',type=Path);view.add_argument('--output',type=Path)
    serve=sub.add_parser('serve',help='Read-only cockpit; does not start jobs or publish models')
    serve.add_argument('--port',type=int,default=8473)
    retry=sub.add_parser('retry',help='Explicitly retry a failed job from its checkpoints')
    retry.add_argument('job_id')
    publish=sub.add_parser('publish',help='Explicitly publish a projection to a local model store')
    publish.add_argument('job_id');publish.add_argument('--store',type=Path,default=Path('runtime/model-store'))
    publish.add_argument('--actor',required=True)
    publish.add_argument('--expected-current',type=int,help='Require this publication revision; base hash is always verified')
    rollback=sub.add_parser('rollback',help='Restore a previously published local snapshot')
    rollback.add_argument('--store',type=Path,default=Path('runtime/model-store'))
    rollback.add_argument('--actor',required=True)
    rollback.add_argument('--target',type=int,required=True)
    rollback.add_argument('--expected-current',type=int,required=True)
    for p in (demo,enqueue,watch,revisit,work,view,serve,retry,publish,rollback):
        p.add_argument('--db',type=Path,default=Path('runtime/background.sqlite'))


def _emit(value):
    print(json.dumps(value,ensure_ascii=True,indent=2))


def execute(args):
    _validate_paths(args)
    queue=Queue(args.db)
    command=args.loop_command
    if command in ('enqueue','watch'):
        if args.signals.count('-')>1 or args.top_k<1:
            raise ValueError('Use at most one stdin feed and positive top-k')
        if command=='watch' and ('-' in args.signals or not math.isfinite(args.poll_seconds) or args.poll_seconds<=0):
            raise ValueError('Watch requires local files and a positive polling interval')
        previous=None
        while True:
            # Source systems should export atomically. A failed read must not enqueue partial input.
            try:
                model=json.loads(args.model.read_text(encoding='utf-8-sig'))
                records=list(chain.from_iterable(read_signals(p) for p in args.signals))
                jid=queue.enqueue(model,records,options=dict(top_k=args.top_k,exhaustive=args.exhaustive,geometry=args.geometry))
            except (ValueError,OSError) as exc:
                if command=='enqueue' or args.once:
                    raise
                _emit(dict(status='source_unavailable',error=str(exc)))
                time.sleep(args.poll_seconds)
                continue
            if jid!=previous:
                _emit(dict(job_id=jid,status=queue.get(jid)['status']));previous=jid
            if command=='enqueue' or args.once:
                break
            time.sleep(args.poll_seconds)
    elif command=='demo':
        from .demo import inputs
        from .report import render_loop
        model,records=inputs(with_new_source=args.new_source)
        jid=queue.enqueue(model,records,synthetic=True)
        run_once(queue,job_id=jid)
        result=report(queue,jid)
        if args.html.resolve()==args.output.resolve():
            raise ValueError('JSON and HTML outputs must be distinct')
        write_text(args.output,json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        write_text(args.html,render_loop(result))
        _emit(dict(job_id=jid,status=result['status'],candidates=len(result['candidates']),
                   html=str(args.html.resolve()),json=str(args.output.resolve()),published=False))
    elif command=='revisit':
        old=queue.get(args.job_id)['payload']
        model=json.loads(args.model.read_text(encoding='utf-8-sig')) if args.model else old['model']
        if args.signals.count('-')>1:
            raise ValueError('Use at most one stdin feed')
        records=old['records']+list(chain.from_iterable(read_signals(p) for p in args.signals))
        # Record IDs are immutable. Conflicting revisions need distinct IDs rather than an overwrite.
        unique={}
        for row in records:
            rid=row.get('id')
            if not isinstance(rid,str) or not rid:
                raise ValueError('Every source record requires an ID')
            if rid in unique and unique[rid]!=row:
                raise ValueError('Conflicting source record: '+rid)
            unique[rid]=row
        jid=queue.enqueue(model,list(unique.values()),options=old['options'],synthetic=False)
        queue.event(jid,'revisited',dict(previous_job=args.job_id))
        _emit(dict(job_id=jid,status=queue.get(jid)['status'],previous_job=args.job_id))
    elif command=='work':
        if not all(math.isfinite(v) for v in (args.lease_seconds,args.poll_seconds)) or args.lease_seconds<1 or args.poll_seconds<=0:
            raise ValueError('Lease must be at least one second and poll interval positive')
        while True:
            try:
                result=run_once(queue,job_id=args.job,lease_seconds=args.lease_seconds)
            except Exception as exc:
                if args.once:
                    raise
                _emit(dict(status='job_failed',error_type=type(exc).__name__,error=str(exc)))
                time.sleep(args.poll_seconds)
                continue
            if result:
                _emit(dict(job_id=result['id'],status=result['status'],candidates=len(result['candidates'])))
            if args.once:
                if result is None:
                    _emit(dict(status='idle'))
                break
            time.sleep(args.poll_seconds)
    elif command=='report':
        from .report import render_loop
        result=report(queue,args.job_id)
        if args.html:
            write_text(args.html,render_loop(result))
        if args.output:
            write_text(args.output,json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        else:
            _emit(result)
    elif command=='serve':
        from .app import serve
        if not 0<=args.port<=65535:
            raise ValueError('Invalid port')
        serve(queue,args.port)
    elif command=='retry':
        queue.retry(args.job_id);_emit(dict(job_id=args.job_id,status='queued'))
    elif command in ('publish','rollback'):
        return _publish_command(args,queue)


def _publish_command(args,queue):
    from .projection import initialize_store, read_published, publish_projection, rollback_publication
    if args.loop_command=='publish':
        job=queue.get(args.job_id)
        if job['status']!='completed' or not job['result'].get('projection'):
            raise ValueError('Only a completed job with a projection can be published')
        proposal=job['result']['projection']
        if not proposal.get('schema_changes') and not proposal.get('assignment_changes'):
            raise ValueError('Projection has no publishable changes')
        # Existing stores are read, never reset; publish checks the immutable proposal base.
        current=(read_published(args.store) if (args.store/'HEAD.json').exists()
                 else initialize_store(args.store,job['payload']['model'],actor=args.actor))
        expected=current['revision'] if args.expected_current is None else args.expected_current
        receipt=publish_projection(args.store,proposal,expected_revision=expected,actor=args.actor)
        queue.event(args.job_id,'publication_receipt',dict(store=str(args.store.resolve()),
                    revision=receipt['revision'],snapshot_hash=receipt['snapshot_hash'],actor=args.actor))
    else:
        receipt=rollback_publication(args.store,args.target,
                    expected_revision=args.expected_current,actor=args.actor)
    current=read_published(args.store)
    _emit(dict(store=str(args.store.resolve()),receipt_revision=receipt['revision'],
               current_revision=current['revision'],snapshot_hash=current['snapshot_hash'],
               operation=args.loop_command,actor=args.actor))


def _validate_paths(args):
    """Reject accidental overwrite of source files or the live job database."""
    database=args.db.resolve()
    outputs=[p.resolve() for p in (getattr(args,'html',None),getattr(args,'output',None)) if p]
    inputs=[Path(p).resolve() for p in getattr(args,'signals',[]) if p!='-']
    if getattr(args,'model',None):
        inputs.append(args.model.resolve())
    protected={database,Path(str(database)+'-wal'),Path(str(database)+'-shm'),*inputs}
    if len(set(outputs))!=len(outputs) or any(p in protected for p in outputs):
        raise ValueError('Export paths must differ from each other, source files and the job database')
    if database in inputs:
        raise ValueError('Job database must not overwrite an input source')
