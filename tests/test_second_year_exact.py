from test_app import client, member, plan, edit
from app.rules import exact_month_members


def test_second_year_assigns_exactly_four_and_prioritizes_holidays(client, monkeypatch):
    monkeypatch.setattr('app.main.secrets.randbelow', lambda n: 42)
    for i in range(6):
        member(client, f'担当{i}')
    member(client, '対象期間終了', end='2027-03-31')
    p = plan(client)
    r = client.post(f'/api/plans/{p["id"]}/generate', json={'version': p['version']})
    assert r.status_code == 200, r.text
    p = r.json()
    assert not p['errors'] and not p['unfilled']
    assert [row['total'] for row in p['summaries']['2027-04']] == [4] * 6
    assert all(s['member_id'] for s in p['slots']
               if s['enabled'] and p['days'][s['date']]['holiday'])
    assert client.post(f'/api/plans/{p["id"]}/finalize', json={'version': p['version']}).status_code == 200


def test_impossible_exact_count_does_not_overwrite_plan(client):
    # Ten members need 40 duties, beyond the available automatic weekly budget.
    for i in range(10):
        member(client, f'担当{i}')
    p = plan(client)
    r = client.post(f'/api/plans/{p["id"]}/generate', json={'version': p['version']})
    assert r.status_code == 422
    assert '月4回' in r.text and '枠' in r.text
    saved = client.get(f'/api/plans/{p["id"]}').json()
    assert saved['version'] == p['version']
    assert saved['slots'] == p['slots']


def test_under_four_allowed_in_draft_but_not_final(client):
    mid = member(client)
    p = plan(client)
    # Disable all required slots: there are no empty required slots, but the
    # active member still needs four duties before the full month is final.
    for s in p['slots']:
        if s['enabled']:
            r = client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',
                           json={'version': p['version'], 'enabled': False})
            assert r.status_code == 200, r.text
            p = r.json()
    assert not p['unfilled']
    r = client.post(f'/api/plans/{p["id"]}/finalize', json={'version': p['version']})
    assert r.status_code == 422 and '月4回' in r.text
    for day in (3, 10, 17, 24):
        s = next(s for s in p['slots'] if s['date'] == f'2027-04-{day:02}'
                 and s['kind'] == 'day' and s['number'] == 1)
        r = client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',
                       json={'version': p['version'], 'enabled': True})
        assert r.status_code == 200, r.text
        p = r.json()
        r = edit(client, p, s['id'], member_id=mid)
        assert r.status_code == 200, r.text
        p = r.json()
    assert client.post(f'/api/plans/{p["id"]}/finalize', json={'version': p['version']}).status_code == 200


def test_rotation_preventing_four_explains_member_and_available_days(client):
    member(client, '研修担当', rotations=[{'kind': 'community', 'hospital': 'remote',
           'start': '2027-04-01', 'end': '2027-04-30'}])
    p = plan(client)
    r = client.post(f'/api/plans/{p["id"]}/generate', json={'version': p['version']})
    assert r.status_code == 422
    assert '研修担当' in r.text and '勤務可能日は0日' in r.text


def test_exact_count_scope_full_month_active_members_only():
    active = {'id': 1, 'periods': [{'start': '2026-04-01', 'end': '2028-03-31'}]}
    retired = {'id': 2, 'periods': [{'start': '2026-04-01', 'end': '2027-03-31'}]}
    archived = {**active, 'id': 3, 'archived': True}
    partial_member = {'id': 4, 'periods': [{'start': '2027-04-15', 'end': '2028-03-31'}]}
    members = [active, retired, archived, partial_member]
    p = {'start': '2027-03-15', 'end': '2027-05-10'}
    assert exact_month_members(p, members, '2027-03') == []
    assert exact_month_members(p, members, '2027-04') == [active, partial_member]
    assert exact_month_members(p, members, '2027-05') == []
    assert exact_month_members({'start': '2027-04-02', 'end': '2027-04-30'}, members, '2027-04') == []
    assert exact_month_members({'start': '2027-03-01', 'end': '2027-03-31'}, members, '2027-03') == []
