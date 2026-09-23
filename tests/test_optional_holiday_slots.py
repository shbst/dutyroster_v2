import pytest
from test_app import client, member, plan, edit


def change(client, p, s, enabled):
    return client.put(f'/api/plans/{p["id"]}/slots/{s["id"]}',
                      json={'version':p['version'], 'enabled':enabled})


@pytest.mark.parametrize('ds', ['2027-04-03', '2027-04-04', '2027-05-03', '2027-04-06'])
@pytest.mark.parametrize('kind', ['day', 'night'])
def test_disabled_holiday_slot_stays_disabled_and_can_finalize(client, ds, kind):
    if ds=='2027-04-06':
        assert client.post('/api/holidays', json={'date':ds,'name':'Test holiday'}).status_code==200
    member(client)
    p=plan(client, ds, ds)
    s=next(s for s in p['slots'] if s['kind']==kind and s['number']==1)
    assert s['enabled']
    r=change(client,p,s,False); assert r.status_code==200,r.text
    p=r.json()
    assert len(p['unfilled'])==1
    # Updating the holiday's name must not reactivate manually disabled slots.
    assert client.post('/api/holidays',json={'date':ds,'name':'Updated holiday'}).status_code==200
    p=client.get(f'/api/plans/{p["id"]}').json()
    r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']})
    assert r.status_code==200,r.text
    p=r.json()
    saved=next(t for t in p['slots'] if t['id']==s['id'])
    assert saved['enabled']==0 and saved['member_id'] is None and saved['origin']=='manual'
    assert not p['unfilled'] and not p['errors']
    assert client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']}).status_code==200


def test_disable_guards_undo_and_reenable(client):
    mid=member(client); p=plan(client,'2027-04-03','2027-04-03')
    first=next(s for s in p['slots'] if s['kind']=='day' and s['number']==1)
    second=next(s for s in p['slots'] if s['kind']=='day' and s['number']==2)
    p=edit(client,p,first['id'],member_id=mid).json()
    assert change(client,p,first,False).status_code==422
    p=edit(client,p,first['id'],member_id=None).json()
    p=change(client,p,second,True).json()
    assert change(client,p,first,False).status_code==422
    p=change(client,p,second,False).json()
    p=change(client,p,first,False).json()
    r=client.post(f'/api/plans/{p["id"]}/undo',json={'version':p['version']})
    assert r.status_code==200
    p=r.json(); assert next(s for s in p['slots'] if s['id']==first['id'])['enabled']
    p=change(client,p,first,False).json()
    r=change(client,p,first,True)
    assert r.status_code==200 and next(s for s in r.json()['slots'] if s['id']==first['id'])['enabled']
