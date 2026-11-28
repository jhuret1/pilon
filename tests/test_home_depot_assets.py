import csv
import pytest

from pilon.home_depot_assets import index_descriptions, route_assets


def source(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=['product_uid','product_description'])
        writer.writeheader()
        writer.writerows(rows)


def test_description_routing_is_source_preserving_and_not_fact_validation(tmp_path):
    path=tmp_path/'sources.csv'
    source(path,[dict(product_uid='1',product_description='A quiet pump, with a brass fitting.'),
                 dict(product_uid='2',product_description='This red planter has no pump.')])
    db=tmp_path/'sources.sqlite'
    manifest=index_descriptions(path,db)
    assert manifest['documents']==2
    assert index_descriptions(path,db)==manifest
    records,routing=route_assets(db,['quiet pump'],limit=1)
    assert records[0]['text']=='A quiet pump, with a brass fitting.'
    assert records[0]['role']=='catalog' and records[0]['product_id']=='1'
    assert 'extractions' not in records[0]
    assert routing['indexed_assets']==2 and routing['unassessed_outside_shortlist']==1
    assert routing['selection_recall']=='not_measured'
    assert route_assets(db,['no matching concept'])[0]==[]
    source(path,[dict(product_uid='1',product_description='Changed.')])
    with pytest.raises(ValueError,match='changed'): index_descriptions(path,db)


def test_conflicting_sources_fail_without_publishing_partial_index(tmp_path):
    path=tmp_path/'sources.csv';db=tmp_path/'sources.sqlite'
    source(path,[dict(product_uid='1',product_description='First'),dict(product_uid='1',product_description='Different')])
    with pytest.raises(ValueError,match='Conflicting'): index_descriptions(path,db)
    assert not db.exists()


def test_routing_does_not_create_a_missing_database(tmp_path):
    with pytest.raises(Exception): route_assets(tmp_path/'missing.sqlite',['pump'])
    assert not (tmp_path/'missing.sqlite').exists()
