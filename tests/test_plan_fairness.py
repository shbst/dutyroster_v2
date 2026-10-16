from test_app import client, member, plan
from app.solver import generate
from app.rules import plan_summary


def test_first_year_fills_enabled_weekdays_and_exceeds_four(client):
    for i in range(4):
        member(client, f'担当{i}')
    p=plan(client, '2026-06-01', '2026-06-30')
    required={s['id'] for s in p['slots'] if s['enabled']}
    r=client.post(f'/api/plans/{p["id"]}/generate', json={'version':p['version']})
    assert r.status_code==200, r.text
    p=r.json()
    assert not p['errors'] and not p['unfilled']
    assert all(s['enabled'] and s['member_id'] for s in p['slots'] if s['id'] in required)
    assert all(r['total']>4 for r in p['plan_summary'])


def test_second_year_empty_slots_can_finalize(client):
    member(client)
    p=plan(client)
    r=client.post(f'/api/plans/{p["id"]}/generate', json={'version':p['version']})
    assert r.status_code==200, r.text
    p=r.json()
    assert p['unfilled'] and p['plan_summary'][0]['total']==4
    assert client.post(f'/api/plans/{p["id"]}/finalize', json={'version':p['version']}).status_code==200


def test_cumulative_categories_compensate_for_locked_first_month():
    members=[{'id':i,'name':str(i),'color':'#ffffff','archived':False,
              'periods':[{'start':'2026-06-01','end':'2026-08-31'}],
              'rotations':[],'events':[]} for i in range(1,4)]
    slots=[]
    # Every month has three duties and each member gets one. After three
    # months each should have one of each type despite June's fixed choices.
    for month, weekend in ((6,6),(7,4),(8,8)):
        for member_id,(day,kind) in enumerate(((3,'night'),(weekend,'day'),(weekend+1,'night')),1):
            slots.append({'id':len(slots)+1,'date':f'2026-{month:02}-{day:02}',
                          'kind':kind,'number':1,'enabled':1,'origin':'manual',
                          'locked':month==6,'member_id':member_id if month==6 else None})
    p={'start':'2026-06-01','end':'2026-08-31'}
    solved,_=generate(p,slots,[],members,{},42)
    rows=plan_summary(solved,members,{},p['start'],p['end'])
    assert all((r['weekday_night'],r['holiday_day'],r['holiday_night'])==(1,1,1) for r in rows)



def test_first_year_keeps_four_weekdays_after_manual_addition(client):
    for i in range(4): member(client, f'担当{i}')
    p=plan(client,'2026-12-14','2026-12-18')
    extra=next(s for s in p['slots'] if s['date']=='2026-12-17' and s['kind']=='night' and s['number']==1)
    p=client.put(f'/api/plans/{p["id"]}/slots/{extra["id"]}',json={'version':p['version'],'enabled':True}).json()
    required={s['id'] for s in p['slots'] if s['enabled']}
    assert len(required)==4
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']})
    assert r.status_code==200,r.text
    p=r.json()
    assert not p['errors'] and not p['unfilled']
    assert {s['id'] for s in p['slots'] if s['enabled']}==required


def test_first_year_keeps_slots_when_holidays_cross_month(client):
    for i in range(4): member(client, f'担当{i}')
    p=plan(client,'2026-12-28','2027-01-01')
    for ds in ('2026-12-30','2026-12-31'):
        assert client.post('/api/holidays',json={'date':ds,'name':'年末'}).status_code==200
    p=client.get(f'/api/plans/{p["id"]}').json()
    required={s['id'] for s in p['slots'] if s['enabled']}
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']})
    assert r.status_code==200,r.text
    p=r.json()
    assert not p['errors'] and not p['unfilled']
    assert {s['id'] for s in p['slots'] if s['enabled']}==required


def test_cumulative_total_compensates_for_fixed_previous_imbalance():
    members=[{'id':i,'name':str(i),'color':'#ffffff','archived':False,
              'periods':[{'start':'2026-06-01','end':'2026-07-31'}],
              'rotations':[],'events':[]} for i in (1,2)]
    slots=[]
    for ds,mid in [('2026-06-01',1),('2026-06-08',1),('2026-06-15',1),
                   ('2026-06-22',2),('2026-07-06',None),('2026-07-13',None)]:
        slots.append({'id':len(slots)+1,'date':ds,'kind':'night','number':1,
                      'enabled':1,'origin':'manual','locked':mid is not None,'member_id':mid})
    p={'start':'2026-06-01','end':'2026-07-31'}
    solved,_=generate(p,slots,[],members,{},42)
    rows=plan_summary(solved,members,{},p['start'],p['end'])
    assert [r['total'] for r in rows]==[3,3]
    assert all(s['member_id']==2 for s in solved if s['date'].startswith('2026-07'))
    assert all(s['member_id']==t['member_id'] for s,t in zip(solved,slots) if t['locked'])
