from datetime import date,timedelta
from test_app import client,member,plan,edit
from app import db

def test_overlapping_plans_have_independent_assignments_and_summaries(client):
    mid=member(client)
    a=plan(client,'2027-03-01','2027-03-31'); b=plan(client,'2027-03-01','2027-03-31')
    for current in (a,b):
        for ds in ('2027-03-06','2027-03-13','2027-03-20','2027-03-27'):
            s=next(s for s in current['slots'] if s['date']==ds and s['kind']=='day' and s['number']==1)
            r=edit(client,current,s['id'],member_id=mid);assert r.status_code==200,r.text;current=r.json()
        assert current['summaries']['2027-03'][0]['total']==4
        assert not current['errors']
    # A member edit validates each plan separately, not eight shifts as one month.
    saved=client.get('/api/bootstrap').json()['members'][0]
    assert client.put(f'/api/members/{mid}',json={k:saved[k] for k in ('name','periods','rotations','events','color')}).status_code==200

def test_boundary_inside_one_plan_still_disallows_consecutive_dates(client):
    mid=member(client);p=plan(client,'2027-03-31','2027-04-01')
    for i,ds in enumerate(('2027-03-31','2027-04-01')):
        s=next(s for s in p['slots'] if s['date']==ds and s['kind']=='night' and s['number']==1)
        r=edit(client,p,s['id'],member_id=mid)
        if i==0: assert r.status_code==200;p=r.json()
        else: assert r.status_code==422

def test_delete_only_selected_plan_and_reject_stale_version(client):
    mid=member(client); a=plan(client);b=plan(client)
    s=next(s for s in a['slots'] if s['enabled'])
    a=edit(client,a,s['id'],member_id=mid).json()
    assert client.request('DELETE',f'/api/plans/{a["id"]}',json={'version':a['version']-1}).status_code==409
    assert client.get(f'/api/plans/{a["id"]}').status_code==200
    assert client.request('DELETE',f'/api/plans/{a["id"]}',json={'version':a['version']}).status_code==200
    assert client.get(f'/api/plans/{a["id"]}').status_code==404
    assert client.get(f'/api/plans/{b["id"]}').status_code==200
    state=client.get('/api/bootstrap').json()
    assert len(state['members'])==1 and len(state['plans'])==1
    with db.connect() as conn:
        for table in ('slots','history','generation_runs'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table} WHERE plan_id=?',(a['id'],)).fetchone()[0]==0
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()

def test_generation_weekly_budget_and_balanced_categories(client,monkeypatch):
    monkeypatch.setattr('app.main.secrets.randbelow',lambda n:42)
    for i in range(10): member(client,f'メンバー{i}')
    # A second independently generated alternative, covering the same month.
    p=plan(client);other=plan(client)
    for current in (p,other):
        r=client.post(f'/api/plans/{current["id"]}/generate',json={'version':current['version']})
        assert r.status_code==200,r.text;current=r.json()
        assert not current['errors'] and not current['unfilled']
        weeks={}
        for s in current['slots']:
            d=date.fromisoformat(s['date'])
            if d.weekday()<5 and s['kind']=='night' and s['number']==1:
                monday=d-timedelta(days=d.weekday());weeks.setdefault(monday,[]).append(s)
        for slots in weeks.values(): assert sum(s['enabled'] for s in slots)==min(3,len(slots))
        rows=current['summaries']['2027-04']
        assert any(row['total']<=3 for row in rows)
        for key in ('total','weekday_night','holiday_day','holiday_night'):
            counts=[row[key] for row in rows]
            assert max(counts)-min(counts)<=1,(key,counts)

def test_week_crossing_month_counts_three_days_total(client,monkeypatch):
    monkeypatch.setattr('app.main.secrets.randbelow',lambda n:42)
    for i in range(5):member(client,f'境界{i}')
    p=plan(client,'2027-03-29','2027-04-02')
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']});assert r.status_code==200,r.text
    p=r.json(); assert not p['errors']
    assert sum(s['enabled'] for s in p['slots'] if s['kind']=='night' and s['number']==1)==3
