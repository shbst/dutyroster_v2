import pytest
from app.main import Rotation
from app.rules import reasons
from app import db
from test_app import client, member

@pytest.mark.parametrize('kind,hospital',[
    ('anesthesia',''),('outpatient',''),('psychiatry',''),
    ('psychiatry','shin_abuyama'),('community','takatsuki_nearby'),('community','remote'),
])
def test_valid_placements_round_trip(client,kind,hospital):
    mid=member(client,rotations=[{'kind':kind,'hospital':hospital,'start':'2027-04-01','end':'2027-04-30'}])
    saved=next(m for m in client.get('/api/bootstrap').json()['members'] if m['id']==mid)
    assert saved['rotations'][0]['kind']==kind
    assert saved['rotations'][0]['hospital']==hospital
    payload={k:saved[k] for k in ('name','color','periods','rotations','events')}
    assert client.put(f'/api/members/{mid}',json=payload).status_code==200

@pytest.mark.parametrize('kind,hospital',[
    ('anesthesia','shin_abuyama'),('anesthesia','remote'),('outpatient','shin_abuyama'),
    ('psychiatry','remote'),('community','shin_abuyama'),('community','unknown'),
])
def test_invalid_placements_rejected(client,kind,hospital):
    r=client.post('/api/members',json={'name':'不正な配属先','periods':[{'start':'2026-04-01','end':'2028-03-31'}],
        'rotations':[{'kind':kind,'hospital':hospital,'start':'2027-04-01','end':'2027-04-30'}]})
    assert r.status_code==422
    assert not client.get('/api/bootstrap').json()['members']

def test_community_remote_blocks_both_shifts(client):
    mid=member(client,rotations=[{'kind':'community','hospital':'remote','start':'2027-04-01','end':'2027-04-30'}])
    m=next(m for m in client.get('/api/bootstrap').json()['members'] if m['id']==mid)
    for kind in ('day','night'):
        assert 'へき地医療研修中' in reasons(m,{'date':'2027-04-03','kind':kind},{})
        assert 'へき地医療研修中' not in reasons(m,{'date':'2027-05-01','kind':kind},{})
    m['rotations'][0]['hospital']='takatsuki_nearby'
    assert not reasons(m,{'date':'2027-04-03','kind':'day'},{})

def test_legacy_data_migration_is_idempotent(client):
    mid=member(client)
    with db.connect() as conn:
        conn.execute("INSERT INTO rotations(member_id,kind,hospital,start,end) VALUES(?,'remote','','2027-04-01','2027-04-30')",(mid,))
        conn.execute("INSERT INTO rotations(member_id,kind,hospital,start,end) VALUES(?,'community','','2027-05-01','2027-05-31')",(mid,))
    db.initialize();db.initialize()
    m=client.get('/api/bootstrap').json()['members'][0]
    assert [(r['kind'],r['hospital']) for r in m['rotations']]==[('community','remote'),('community','takatsuki_nearby')]
    old=Rotation(kind='remote',hospital='',start='2027-04-01',end='2027-04-30')
    assert (old.kind,old.hospital)==('community','remote')

def test_placement_metadata(client):
    response=client.get('/api/bootstrap')
    assert response.json()['api_version']==3
    assert response.headers['cache-control']=='no-store'
    sites=response.json()['rotation_sites']
    assert sites=={
        'anesthesia':[['','院内']], 'outpatient':[['','院内']],
        'psychiatry':[['','院内'],['shin_abuyama','新阿武山病院']],
        'community':[['takatsuki_nearby','高槻病院近傍'],['remote','へき地']],
    }
