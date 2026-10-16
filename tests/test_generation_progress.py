import json
from test_app import client,member,plan


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_stream_reports_stages_and_persists_once(client):
    member(client)
    p=plan(client,'2027-04-03','2027-04-03')
    response=client.post(f'/api/plans/{p["id"]}/generate-stream',json={'version':p['version']})
    assert response.status_code==200,response.text
    assert 'application/x-ndjson' in response.headers['content-type']
    messages=events(response)
    stages=[m['stage'] for m in messages if m['type']=='progress']
    assert '休日枠を充足中' in stages
    assert '全期間の公平性を検証中' in stages
    assert stages[-2:]==['勤務条件を最終確認中','配置結果を保存中']
    assert any(m.get('completed_months')==1 for m in messages)
    assert any(m.get('candidates',0)>0 for m in messages)
    assert messages[-1]['type']=='result'
    saved=client.get(f'/api/plans/{p["id"]}').json()
    assert saved['version']==p['version']+1
    assert saved['slots']==messages[-1]['plan']['slots']


def test_stream_failure_is_terminal_and_does_not_save(client,monkeypatch):
    member(client);p=plan(client,'2027-04-03','2027-04-03')
    def fail(*args,progress=None):
        progress(stage='全期間の公平性を検証中',month=None)
        raise ValueError('公平性の検証に失敗しました')
    monkeypatch.setattr('app.main.generate',fail)
    response=client.post(f'/api/plans/{p["id"]}/generate-stream',json={'version':p['version']})
    messages=events(response)
    assert messages[-1]=={'type':'error','detail':'公平性の検証に失敗しました'}
    assert not any(m['type']=='result' for m in messages)
    saved=client.get(f'/api/plans/{p["id"]}').json()
    assert saved['slots']==p['slots'] and saved['version']==p['version']
    assert saved['history']==p['history']


def test_stream_rejects_stale_version_before_start(client):
    p=plan(client)
    response=client.post(f'/api/plans/{p["id"]}/generate-stream',json={'version':p['version']-1})
    assert response.status_code==409


def test_progress_is_yielded_while_worker_is_still_running(client,monkeypatch):
    import asyncio
    from threading import Event
    from app.main import generate_stream,Version
    p=plan(client)
    release=Event();finished=Event()
    def slow(pid,data,progress):
        progress(stage='探索中',month='2027-04')
        assert release.wait(5)
        finished.set()
        return {'id':pid}
    monkeypatch.setattr('app.main.run_generation',slow)
    async def read():
        response=generate_stream(p['id'],Version(version=p['version']))
        iterator=response.body_iterator
        try:
            first=json.loads(await anext(iterator))
            second=json.loads(await asyncio.wait_for(anext(iterator),2))
            assert first['type']=='progress' and second['stage']=='探索中'
            assert not finished.is_set()
            release.set()
            last=json.loads(await asyncio.wait_for(anext(iterator),2))
            assert last['type']=='result'
        finally:
            release.set()
            await iterator.aclose()
    asyncio.run(read())
