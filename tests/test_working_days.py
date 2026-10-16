from datetime import date
import pytest
from test_app import client, member, plan, edit
from app.rules import holiday, holiday_name, category, holiday_duty


@pytest.mark.parametrize('ds',['2027-05-03','2027-04-03','2027-04-04'])
def test_override_default_holidays_and_restore(client, ds):
    p=plan(client,ds,ds)
    r=client.post('/api/working-days',json={'date':ds})
    assert r.status_code==200,r.text
    p=client.get(f'/api/plans/{p["id"]}').json()
    assert p['days'][ds]=={'holiday':False,'name':'平日扱い'}
    assert all(not s['enabled'] for s in p['slots'] if s['kind']=='day')
    custom=client.get('/api/bootstrap').json()['holidays']
    assert custom[ds] is False
    assert not holiday(date.fromisoformat(ds),custom)
    assert category({'date':ds,'kind':'night'},custom)=='weekday_night'
    assert client.post('/api/working-days',json={'date':ds,'enabled':False}).status_code==200
    p=client.get(f'/api/plans/{p["id"]}').json()
    assert p['days'][ds]['holiday']
    assert all(s['enabled'] for s in p['slots'] if s['number']==1)


def test_existing_assignment_prevents_override_atomically(client):
    mid=member(client);p=plan(client,'2027-05-03','2027-05-03')
    s=next(s for s in p['slots'] if s['kind']=='day' and s['number']==1)
    p=edit(client,p,s['id'],member_id=mid).json()
    r=client.post('/api/working-days',json={'date':'2027-05-03'})
    assert r.status_code==422 and '日直' in r.text
    saved=client.get(f'/api/plans/{p["id"]}').json()
    assert saved['version']==p['version'] and saved['slots']==p['slots']
    assert '2027-05-03' not in client.get('/api/bootstrap').json()['holidays']


def test_custom_holiday_restored_and_explicit_holiday_replaces_override(client):
    ds='2027-04-06'
    assert client.post('/api/holidays',json={'date':ds,'name':'院内休日'}).status_code==200
    assert client.post('/api/working-days',json={'date':ds}).status_code==200
    assert client.post('/api/working-days',json={'date':ds,'enabled':False}).status_code==200
    assert client.get('/api/bootstrap').json()['holidays'][ds]=='院内休日'
    client.post('/api/working-days',json={'date':ds})
    client.post('/api/holidays',json={'date':ds,'name':'新休日'})
    assert client.get('/api/bootstrap').json()['holidays'][ds]=='新休日'


def test_generation_and_summary_use_override(client):
    member(client)
    ds='2027-05-03'
    assert client.post('/api/working-days',json={'date':ds}).status_code==200
    p=plan(client,ds,ds)
    assert not p['days'][ds]['holiday']
    s=next(s for s in p['slots'] if s['kind']=='night' and s['number']==1)
    p=client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',json={'version':p['version'],'enabled':True}).json()
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']})
    assert r.status_code==200,r.text
    p=r.json()
    assert not p['errors'] and not p['unfilled']
    assert p['plan_summary'][0]['weekday_night']==1
    assert p['plan_summary'][0]['holiday_night']==0
    assert p['summaries']['2027-05'][0]['weekday_night']==1
    assert client.get(f'/api/plans/{p["id"]}/pdf').status_code==200
    assert client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']}).status_code==200
    assert client.post('/api/working-days',json={'date':ds,'enabled':False}).status_code==409


def test_override_affects_previous_night_and_validates_date(client):
    custom={'2027-04-03':False}
    assert not holiday_duty({'date':'2027-04-02','kind':'night'},custom)
    assert client.post('/api/working-days',json={'date':'2029-01-01'}).status_code==422


def test_previous_day_final_plan_blocks_calendar_change(client):
    member(client)
    p=plan(client,'2027-04-02','2027-04-02')
    assert client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']}).status_code==200
    assert client.post('/api/working-days',json={'date':'2027-04-03'}).status_code==409


def test_rotation_conflict_rolls_back_override(client):
    mid=member(client,rotations=[{'kind':'psychiatry','hospital':'shin_abuyama','start':'2027-05-01','end':'2027-05-10'}])
    p=plan(client,'2027-05-03','2027-05-03')
    # Monday night is already prohibited; use the following national holiday.
    p=plan(client,'2027-05-04','2027-05-04')
    s=next(s for s in p['slots'] if s['kind']=='night' and s['number']==1)
    r=edit(client,p,s['id'],member_id=mid)
    assert r.status_code==200,r.text
    p=r.json()
    r=client.post('/api/working-days',json={'date':'2027-05-04'})
    assert r.status_code==422 and '平日当直' in r.text
    saved=client.get(f'/api/plans/{p["id"]}').json()
    assert saved['version']==p['version'] and saved['days']['2027-05-04']['holiday']
