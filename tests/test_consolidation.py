from pilon.consolidation import canonical_groups, canonical_snapshot


def test_no_blind_transitive_merge():
    facts = [{'id':s} for s in 'abc']
    def pair(left,right,choice):
        return dict(id=left+right,left=left,right=right,similarity=.99,decision=dict(choice=choice,confidence=.99))
    pairs = [pair('a','b','equivalent'),pair('b','c','equivalent'),pair('a','c','distinct')]
    groups = canonical_groups(facts,pairs)
    assert sorted(map(len,groups)) == [1,2]
    pairs[-1]['decision']['choice'] = 'equivalent'
    assert canonical_groups(facts,pairs) == [['a','b','c']]


def test_consolidation_preserves_values_without_publication():
    fact = dict(id='a',name='cable.presence',definition='Included cable.',values=['absent'],
                family='Package contents',family_decision=dict(choice='contents',confidence=.9),evidence_count=1)
    result = canonical_snapshot(dict(facts=[fact],pairs=[],source_run='test',source_fingerprint='hash'), [])
    assert result['published'] is False
    assert result['facts'][0]['values'] == ['absent']
    assert result['facts'][0]['family_review_is_not_fact_validation'] is True
