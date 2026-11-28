from copy import deepcopy
import pytest

from pilon.loop.review_bundle import attach_reviews, detach_reviews


def inputs():
    model=dict(category='Tools',facets=[dict(key='power',label='Power',values=['cordless'])],categories=[])
    records=[dict(id='q1',role='demand',category='Tools',source='search',text='cordless drill')]
    reviews=[dict(record_id='q1',interpretation='A drill without a power cable',criteria=[dict(
        assessment='represented',label='Power',value='cordless',fact_key='power',matched_value='cordless',
        quote='cordless',start=0,end=8,rationale='An observed power mode.',category_refs=[])])]
    return model,records,reviews


def test_decisions_reattach_only_to_exact_source_and_schema():
    model,records,reviews=inputs();original=deepcopy((model,records,reviews))
    bundle=detach_reviews(model,records,reviews)
    assert 'quote' not in bundle['reviews'][0]['criteria'][0]
    assert attach_reviews(bundle,model,records)==reviews
    assert attach_reviews(bundle,dict(model,provenance={'mirror':'another URL'},version='another metadata version'),records)==reviews
    assert (model,records,reviews)==original
    changed=deepcopy(model);changed['facets'][0]['values'].append('corded')
    with pytest.raises(ValueError):attach_reviews(bundle,changed,records)
    altered=deepcopy(records);altered[0]['text']='corded drill'
    with pytest.raises(ValueError):attach_reviews(bundle,model,altered)
    tampered=deepcopy(bundle);tampered['reviews'][0]['criteria'][0]['end']=7
    with pytest.raises(ValueError,match='fingerprint'):attach_reviews(tampered,model,records)


def test_audit_replay_checks_nested_correction_quotes_and_demand_identity():
    from pilon.loop.review_bundle import detach_audit, attach_audit
    from pilon.loop.store import fingerprint
    model,records,reviews=inputs()
    finding=dict(id='a1',record_id='q1',status='corrected',kind='mapping',summary='Use existing power field',
                 expected='Power=cordless',observed='A new field was proposed',quote='cordless',start=0,end=8,
                 correction=deepcopy(reviews[0]['criteria'][0]))
    audit=dict(model_hash=fingerprint(model),demand_hash=fingerprint([['q1','cordless drill']]),
               sample_size=1,reviewed_record_ids=['q1'],method='Agent review',findings=[finding])
    bundle=detach_audit(audit,model,records)
    assert 'quote' not in bundle['audit']['findings'][0]['correction']
    restored=attach_audit(bundle,dict(model,provenance={'mirror':'different'}),records)
    assert restored['findings']==audit['findings']
    assert restored['independent'] is False
    broken=deepcopy(bundle);broken['audit']['findings'][0]['correction']['quote_sha256']='0'*64
    with pytest.raises(ValueError,match='fingerprint'):
        attach_audit(broken,model,records)
    with pytest.raises(ValueError):
        attach_audit(bundle,model,[dict(records[0],text='corded drill')])
