import pytest
from test_app import client, member, plan, edit


@pytest.mark.parametrize('locked',[True,False])
def test_assign_and_lock_together_and_undo(client,locked):
    mid=member(client)
    p=plan(client,'2027-04-03','2027-04-03')
    s=next(s for s in p['slots'] if s['kind']=='day' and s['number']==1)
    r=edit(client,p,s['id'],member_id=mid,locked=locked)
    assert r.status_code==200,r.text
    p=r.json()
    saved=next(t for t in p['slots'] if t['id']==s['id'])
    assert saved['member_id']==mid and bool(saved['locked'])==locked
    if locked:
        assert edit(client,p,s['id'],member_id=mid,locked=False).status_code==422
        r=client.post(f'/api/plans/{p["id"]}/generate',json={'version':p['version']})
        assert r.status_code==200,r.text
        generated=next(t for t in r.json()['slots'] if t['id']==s['id'])
        assert generated['member_id']==mid and generated['locked']
        p=client.post(f'/api/plans/{p["id"]}/undo',json={'version':r.json()['version']}).json()
    r=client.post(f'/api/plans/{p["id"]}/undo',json={'version':p['version']})
    assert r.status_code==200,r.text
    saved=next(t for t in r.json()['slots'] if t['id']==s['id'])
    assert saved['member_id'] is None and not saved['locked']


def test_invalid_combined_assignment_is_atomic(client):
    mid=member(client,end='2027-03-31')
    p=plan(client,'2027-04-03','2027-04-03')
    s=next(s for s in p['slots'] if s['kind']=='day' and s['number']==1)
    assert edit(client,p,s['id'],member_id=mid,locked=True).status_code==422
    saved=client.get(f'/api/plans/{p["id"]}').json()
    assert saved['version']==p['version'] and saved['slots']==p['slots']
    assert saved['history']==p['history']
