import pytest
from test_app import client, member, plan, edit


@pytest.mark.parametrize('year', [2026, 2027])
def test_monthly_cap_only_second_year(client, year):
    mid = member(client)
    p = plan(client, f'{year}-04-01', f'{year}-04-30')
    for index, day in enumerate((2, 6, 10, 14, 18)):
        s = next(s for s in p['slots'] if s['date'] == f'{year}-04-{day:02}'
                 and s['kind'] == 'night' and s['number'] == 1)
        if not s['enabled']:
            r = client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',
                           json={'version': p['version'], 'enabled': True})
            assert r.status_code == 200, r.text
            p = r.json()
        r = edit(client, p, s['id'], member_id=mid)
        if index < 4 or year == 2026:
            assert r.status_code == 200, r.text
            p = r.json()
        else:
            assert r.status_code == 422
            assert '月4回上限' in r.text


@pytest.mark.parametrize('count', [1, 4])
def test_holidays_take_capacity_before_optional_weekdays(client, monkeypatch, count):
    monkeypatch.setattr('app.main.secrets.randbelow', lambda n: 42)
    for i in range(count):
        member(client, f'担当{i}')
    # Four weekend days plus a custom weekday holiday = ten required duties.
    assert client.post('/api/holidays', json={'date': '2027-04-07', 'name': '休日'}).status_code == 200
    p = plan(client, '2027-04-01', '2027-04-11')
    r = client.post(f'/api/plans/{p["id"]}/generate', json={'version': p['version']})
    assert r.status_code == 200, r.text
    p = r.json()
    assert not p['errors']
    assert all(row['total'] <= 4 for row in p['summaries']['2027-04'])
    assigned = [s for s in p['slots'] if s['member_id'] is not None]
    holiday_assignments = [s for s in assigned if p['days'][s['date']]['holiday']]
    assert len(holiday_assignments) == (4 if count == 1 else 10)
    assert any(not s['enabled'] for s in p['slots']
               if not p['days'][s['date']]['holiday'] and s['kind'] == 'night' and s['number'] == 1)
    if count == 4:
        assert not p['unfilled']
        assert client.post(f'/api/plans/{p["id"]}/finalize', json={'version': p['version']}).status_code == 200
    else:
        assert len(assigned) == 4
        assert len(p['unfilled']) == 6


def test_manual_and_locked_weekdays_are_preserved(client):
    mid = member(client)
    p = plan(client, '2027-04-05', '2027-04-09')
    first = next(s for s in p['slots'] if s['date'] == '2027-04-05'
                 and s['kind'] == 'night' and s['number'] == 1)
    r = edit(client, p, first['id'], member_id=mid)
    assert r.status_code == 200, r.text
    p = r.json()
    r = edit(client, p, first['id'], locked=True)
    assert r.status_code == 200, r.text
    p = r.json()
    extra = next(s for s in p['slots'] if s['date'] == '2027-04-08'
                 and s['kind'] == 'night' and s['number'] == 1)
    r = client.put(f'/api/plans/{p["id"]}/slots/{extra["id"]}',
                   json={'version': p['version'], 'enabled': True})
    assert r.status_code == 200, r.text
    p = r.json()
    r = client.post(f'/api/plans/{p["id"]}/generate', json={'version': p['version']})
    assert r.status_code == 200, r.text
    p = r.json()
    assert not p['errors'] and not p['unfilled']
    saved = {s['id']: s for s in p['slots']}
    assert saved[first['id']]['locked'] and saved[first['id']]['member_id'] == mid
    assert saved[extra['id']]['enabled'] and saved[extra['id']]['member_id'] == mid
