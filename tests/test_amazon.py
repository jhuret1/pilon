import json
from contextlib import contextmanager
import pytest
from pilon.amazon import normalize, download
from pilon.corpus import rows

REV = 'a'*40


def records():
    return [dict(parent_asin='p1', asin='v1', text='A fictional filter is missing.', user_id='EXCLUDE', images=['EXCLUDE']),
            dict(parent_asin='p2', asin='v2', text='A fictional lid seals well.'),
            dict(parent_asin='p1', asin='v1', text='A fictional motor failed.')]


def test_amazon_normalization_provenance_and_order():
    data = normalize(records(), revision=REV, category='Home_and_Kitchen', offset=10)
    assert len(data['items']) == 2
    assert [r['item_id'] for r in rows(data)] == ['p1','p2','p1']
    assert [r['provenance']['source_row'] for r in rows(data)] == [10,11,12]
    assert 'EXCLUDE' not in json.dumps(data)
    assert data['provenance']['revision'] == REV
    assert rows(data)[0]['text'] == records()[0]['text']


def test_bounded_stream_closes_and_does_not_overwrite(tmp_path):
    class Response:
        closed = False
        def __enter__(self): return self
        def __exit__(self, *a): self.closed = True
        def raise_for_status(self): pass
        def iter_lines(self, **kwargs):
            yield json.dumps(records()[0]).encode()
            raise AssertionError('Read past the requested limit')
    response = Response()
    class Session:
        def get(self, url, **kwargs):
            assert '/resolve/'+REV+'/' in url
            assert kwargs['stream']
            return response
    path = tmp_path/'amazon.json'
    data = download(path, limit=1, revision=REV, session=Session())
    assert response.closed
    assert len(rows(data)) == 1
    with pytest.raises(ValueError, match='exists'):
        download(path, limit=1, revision=REV, session=Session())


@pytest.mark.parametrize('kwargs', [{'limit':0}, {'limit':101}, {'offset':10001}, {'category':'../secret'}, {'revision':'main'}])
def test_invalid_download_arguments(tmp_path, kwargs):
    with pytest.raises(ValueError):
        download(tmp_path/'unused.json', revision=kwargs.pop('revision', REV), **kwargs)


def test_invalid_text_is_not_silently_dropped():
    with pytest.raises(ValueError):
        normalize([dict(parent_asin='p1', text='')], revision=REV, category='Home_and_Kitchen')
