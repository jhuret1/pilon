from pilon.cli import main


def test_start_keeps_a_new_workspace_empty_and_makes_no_provider_request(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('pilon.loop.app.serve', lambda q, port: calls.append((q.jobs(), port)))
    assert main(['start', '--db', str(tmp_path / 'empty.sqlite'), '--port', '8479']) == 0
    assert calls == [([], 8479)]


def test_start_demo_is_repeatable_and_unpublished(tmp_path, monkeypatch):
    snapshots = []
    def serve(queue, port):
        jobs = queue.jobs()
        assert len(jobs) == 1
        snapshots.append(queue.get(jobs[0]['id']))
    monkeypatch.setattr('pilon.loop.app.serve', serve)
    args = ['start', '--demo', '--db', str(tmp_path / 'demo.sqlite')]
    assert main(args) == 0
    assert main(args) == 0
    assert snapshots[0] == snapshots[1]
    assert snapshots[0]['status'] == 'completed'
    assert snapshots[0]['payload']['synthetic'] is True
    assert not any(event['kind'] == 'publication_receipt' for event in snapshots[0]['events'])
