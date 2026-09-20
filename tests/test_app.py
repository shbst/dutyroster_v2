from datetime import date
import json
import pytest
from fastapi.testclient import TestClient
from app import db
from app.main import app
from app.rules import reasons, validate, holiday, holiday_duty, category

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.sqlite3')
    with TestClient(app) as c: yield c

def member(client,name='テスト 太郎',end='2028-03-31',rotations=None,events=None):
    r=client.post('/api/members',json={'name':name,'periods':[{'start':'2026-04-01','end':end}],'rotations':rotations or [],'events':events or []})
    assert r.status_code==200,r.text
    return r.json()['id']

def plan(client,start='2027-04-01',end='2027-04-30'):
    r=client.post('/api/plans',json={'name':'検証用当直表','start':start,'end':end}); assert r.status_code==200,r.text
    return client.get('/api/plans/'+str(r.json()['id'])).json()

def edit(client,p,sid,**kw): return client.post(f'/api/plans/{p["id"]}/assignment',json={'version':p['version'],'slot_id':sid,**kw})

def test_rules_psychiatry_and_remote():
    m={'id':1,'name':'A','periods':[{'start':'2026-04-01','end':'2028-03-31'}],'rotations':[{'kind':'psychiatry','hospital':'shin_abuyama','start':'2027-04-01','end':'2027-04-30'}],'events':[]}
    assert reasons(m,{'date':'2027-03-31','kind':'night'}, {})==['新阿武山病院の研修日前夜']
    assert '新阿武山病院の研修日前夜' in reasons(m,{'date':'2027-04-04','kind':'night'}, {})
    assert not reasons(m,{'date':'2027-04-02','kind':'night'}, {})==[] # Friday forbidden by weekday restriction
    assert not reasons(m,{'date':'2027-04-03','kind':'night'}, {})
    m['events']=[{'date':'2027-04-03','kind':'counseling'}]
    assert reasons(m,{'date':'2027-04-03','kind':'day'}, {})
    m['rotations'][0]['kind']='remote'
    assert 'へき地医療研修中' in reasons(m,{'date':'2027-04-03','kind':'night'}, {})

def test_friday_overlap_and_japanese_holidays():
    s={'date':'2027-04-02','kind':'night'}
    assert category(s,{})=='weekday_night'
    assert holiday_duty(s,{})
    assert holiday(date(2026,9,22),{}) # national holiday between Respect for the Aged Day and equinox
    assert holiday(date(2027,5,3),{})

def test_atomic_edit_conflict_lock_undo(client):
    mid=member(client); p=plan(client)
    s=next(s for s in p['slots'] if s['date']=='2027-04-03' and s['kind']=='day' and s['number']==1)
    r=edit(client,p,s['id'],member_id=mid); assert r.status_code==200,r.text;p=r.json()
    t=next(s for s in p['slots'] if s['date']=='2027-04-04' and s['kind']=='night' and s['number']==1)
    r=edit(client,p,t['id'],member_id=mid); assert r.status_code==422
    current=client.get(f'/api/plans/{p["id"]}').json();assert current['version']==p['version']
    same=next(s for s in p['slots'] if s['date']=='2027-04-03' and s['kind']=='night' and s['number']==1)
    assert edit(client,p,same['id'],member_id=mid).status_code==422
    r=edit(client,p,s['id'],locked=True);assert r.status_code==200;p=r.json()
    assert edit(client,p,s['id'],member_id=None).status_code==422
    r=client.post(f'/api/plans/{p["id"]}/undo',json={'version':p['version']});assert r.status_code==200
    assert not next(t for t in r.json()['slots'] if t['id']==s['id'])['locked']
    assert edit(client,p,s['id'],locked=False).status_code==409

def test_first_year_cap_and_retirement(client):
    mid=member(client,end='2027-03-31');p=plan(client,'2027-03-01','2027-03-31')
    selected=[s for s in p['slots'] if s['kind']=='night' and s['number']==1 and s['enabled']]
    assigned=[]
    for s in selected:
        if all(abs((date.fromisoformat(s['date'])-date.fromisoformat(t['date'])).days)>1 for t in assigned):
            r=edit(client,p,s['id'],member_id=mid)
            if len(assigned)<4: assert r.status_code==200;p=r.json();assigned.append(s)
            else: assert r.status_code==422;break
    assert len(assigned)==4
    april=plan(client);s=next(s for s in april['slots'] if s['enabled'])
    assert edit(client,april,s['id'],member_id=mid).status_code==422

def test_boundary_and_overlap(client):
    mid=member(client);march=plan(client,'2027-03-01','2027-03-31');april=plan(client)
    def enabled(p,ds):
        s=next(s for s in p['slots'] if s['date']==ds and s['kind']=='night' and s['number']==1)
        if not s['enabled']:
            p=client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',json={'version':p['version'],'enabled':True}).json()
        return p,s
    march,a=enabled(march,'2027-03-31');assert edit(client,march,a['id'],member_id=mid).status_code==200
    april,b=enabled(april,'2027-04-01');assert edit(client,april,b['id'],member_id=mid).status_code==200
    assert client.post('/api/plans',json={'start':'2027-03-20','end':'2027-04-05'}).status_code==200

def test_generation_two_slots_fairness_final_pdf(client,tmp_path):
    mids=[member(client,f'検証 {i+1}') for i in range(8)]
    retired=member(client,'年度末まで',end='2027-03-31')
    p=plan(client)
    second=next(s for s in p['slots'] if s['date']=='2027-04-03' and s['kind']=='day' and s['number']==2)
    p=client.put(f'/api/plans/{p["id"]}/slots/{second["id"]}',json={'version':p['version'],'enabled':True}).json()
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']});assert r.status_code==200,r.text;p=r.json()
    assert not p['errors'];assert not p['unfilled']
    assert next(s for s in p['slots'] if s['id']==second['id'])['member_id']
    assert all(s['member_id']!=retired for s in p['slots'])
    assert not any(s['member_id'] for s in p['slots'] if s['number']==2 and s['id']!=second['id'])
    counts=[r['total'] for r in p['summaries']['2027-04']];assert max(counts)-min(counts)<=1,counts
    pdf=client.get(f'/api/plans/{p["id"]}/pdf');assert pdf.status_code==200,pdf.text
    assert pdf.content.startswith(b'%PDF');(tmp_path/'test.pdf').write_bytes(pdf.content)
    r=client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']});assert r.status_code==200,r.text;p=r.json()
    assert p['status']=='final'
    assert client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']}).status_code==409
    assert client.get(f'/api/plans/{p["id"]}/pdf').status_code==200

def test_impossible_is_partial(client):
    member(client);p=plan(client,'2026-12-01','2026-12-31')
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']});assert r.status_code==200,r.text
    p=r.json();assert p['unfilled'];assert not p['errors'];assert p['summaries']['2026-12'][0]['total']<=4
    assert client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']}).status_code==422

def test_input_and_origin_validation(client):
    assert client.post('/api/members',json={'name':' ','periods':[{'start':'2026-04-01','end':'2028-03-31'}]}).status_code==422
    assert client.post('/api/members',json={'name':'X','periods':[{'start':'2026-04-01','end':'2028-03-31'}],'events':[{'date':'2027-04-02','kind':'counseling'}]}).status_code==422
    assert client.post('/api/plans',json={'start':'2027-04-01','end':'2027-04-30'},headers={'origin':'https://evil.example'}).status_code==403
