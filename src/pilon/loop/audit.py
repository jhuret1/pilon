"""Validate locally supplied review findings without treating disagreements as truth."""
from copy import deepcopy

from .store import fingerprint


def validate_audit(audit, model, records):
    if not isinstance(audit, dict):
        raise ValueError('Audit must be an object')
    demands = {r['id']: r for r in records if r.get('role') == 'demand'}
    if audit.get('model_hash') != fingerprint(model):
        raise ValueError('Audit model fingerprint mismatch')
    if audit.get('demand_hash') != fingerprint([[r['id'], r['text']] for r in records if r.get('role') == 'demand']):
        raise ValueError('Audit demand fingerprint mismatch')
    reviewed = audit.get('reviewed_record_ids')
    if not isinstance(reviewed, list) or len(set(reviewed)) != len(reviewed) or any(r not in demands for r in reviewed):
        raise ValueError('Audit needs distinct, known reviewed record IDs')
    if audit.get('sample_size') != len(reviewed):
        raise ValueError('Audit sample size must equal its reviewed records')
    if not isinstance(audit.get('method'), str) or not audit['method'].strip():
        raise ValueError('Audit requires its method')
    findings = audit.get('findings')
    if not isinstance(findings, list):
        raise ValueError('Audit findings must be an array')
    ids = set()
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get('id'), str) or not finding['id'] or finding['id'] in ids:
            raise ValueError('Audit findings require unique IDs')
        ids.add(finding['id'])
        rid = finding.get('record_id')
        if rid not in reviewed:
            raise ValueError('Audit finding outside the reviewed sample')
        if finding.get('status') not in {'confirmed_error', 'corrected', 'needs_review'}:
            raise ValueError('Audit findings must distinguish errors from disagreements')
        for name in ('kind', 'summary', 'expected', 'observed'):
            if not isinstance(finding.get(name), str) or not finding[name].strip():
                raise ValueError('Audit finding requires ' + name)
        start, end = finding.get('start'), finding.get('end')
        text = demands[rid]['text']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != finding.get('quote'):
            raise ValueError('Audit quotation does not match its source')
    out = deepcopy(audit)
    # An imported reviewer decision is not an independently labelled accuracy set.
    out['independent'] = False
    out['validation'] = 'references_and_exact_spans_verified'
    return out
