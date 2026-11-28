"""Share agent decisions without redistributing their original demand quotations.

Recipients supply the source data. Hashes and offsets reattach quotations locally;
this is a replay of supplied decisions, not a new model evaluation.
"""
from copy import deepcopy
from hashlib import sha256

from .semantic import annotate_records
from .store import fingerprint

FORMAT = 'pilon_detached_semantic_reviews_v1'


def _model_hash(model):
    # Source mirror URLs/version strings do not alter schema semantics.
    return fingerprint({k:v for k,v in model.items() if k not in ('provenance','version')})


def detach_reviews(model, records, reviews):
    annotate_records(model,records,reviews)
    detached=deepcopy(reviews)
    for review in detached:
        for criterion in review['criteria']:
            quote=criterion.pop('quote')
            criterion['quote_sha256']=sha256(quote.encode('utf-8')).hexdigest()
    return dict(format=FORMAT, model_semantics_hash=_model_hash(model), records_hash=fingerprint(records),
                source_quotes_included=False, decision_origin='supplied_agent_review',
                independent_accuracy_evaluation=False, reviews=detached)


def attach_reviews(bundle, model, records):
    if not isinstance(bundle,dict) or bundle.get('format') != FORMAT:
        raise ValueError('Unknown detached review format')
    if bundle.get('model_semantics_hash') != _model_hash(model) or bundle.get('records_hash') != fingerprint(records):
        raise ValueError('Detached decisions do not match the supplied model and demand inputs')
    demands={r['id']:r for r in records if r.get('role')=='demand'}
    reviews=deepcopy(bundle.get('reviews'))
    if not isinstance(reviews,list):
        raise ValueError('Detached reviews must be an array')
    for review in reviews:
        if not isinstance(review,dict) or review.get('record_id') not in demands or not isinstance(review.get('criteria'),list):
            raise ValueError('Invalid detached review record')
        text=demands[review['record_id']]['text']
        for criterion in review['criteria']:
            start,end=criterion.get('start'),criterion.get('end')
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise ValueError('Invalid detached evidence offsets')
            quote=text[start:end]
            if sha256(quote.encode('utf-8')).hexdigest()!=criterion.pop('quote_sha256',None):
                raise ValueError('Detached evidence fingerprint mismatch')
            criterion['quote']=quote
    annotate_records(model,records,reviews)
    return reviews


def _audit_spans(value, text, *, detach):
    if isinstance(value, dict):
        if 'quote' in value or 'quote_sha256' in value:
            start, end = value.get('start'), value.get('end')
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise ValueError('Invalid detached audit span')
            quote = text[start:end]
            digest = sha256(quote.encode('utf-8')).hexdigest()
            if detach:
                if value.pop('quote') != quote:
                    raise ValueError('Audit source quote mismatch')
                value['quote_sha256'] = digest
            else:
                if value.pop('quote_sha256') != digest:
                    raise ValueError('Detached audit quote fingerprint mismatch')
                value['quote'] = quote
        for child in value.values():
            _audit_spans(child, text, detach=detach)
    elif isinstance(value, list):
        for child in value:
            _audit_spans(child, text, detach=detach)


def detach_audit(audit, model, records):
    from .audit import validate_audit
    out = validate_audit(audit, model, records)
    texts = {r['id']:r['text'] for r in records if r.get('role') == 'demand'}
    for finding in out['findings']:
        _audit_spans(finding, texts[finding['record_id']], detach=True)
    out.pop('model_hash')
    return dict(format='pilon_detached_audit_v1', model_semantics_hash=_model_hash(model), audit=out)


def attach_audit(bundle, model, records):
    from .audit import validate_audit
    if bundle.get('format') != 'pilon_detached_audit_v1' or bundle.get('model_semantics_hash') != _model_hash(model):
        raise ValueError('Detached audit does not match the model')
    out = deepcopy(bundle['audit'])
    texts = {r['id']:r['text'] for r in records if r.get('role') == 'demand'}
    for finding in out['findings']:
        if finding.get('record_id') not in texts:
            raise ValueError('Detached audit references an unknown demand')
        _audit_spans(finding, texts[finding['record_id']], detach=False)
    out['model_hash'] = fingerprint(model)
    return validate_audit(out, model, records)
