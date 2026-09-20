from app.rules import anesthesia_checks
from test_app import client,member,plan,edit
import pymupdf

def test_anesthesia_counts_overlap_and_stay_in_rotation_month():
    m={'id':1,'name':'麻酔科担当','periods':[{'start':'2026-04-01','end':'2028-03-31'}],
       'rotations':[{'kind':'anesthesia','start':'2027-04-01','end':'2027-04-15'}]}
    def slot(ds,kind='night',mid=1):return {'date':ds,'kind':kind,'member_id':mid,'enabled':True}
    slots=[slot('2027-04-02'),slot('2027-04-06'),slot('2027-04-10','day'),slot('2027-04-23'),slot('2027-05-07'),slot('2027-04-13',mid=2)]
    row=anesthesia_checks(slots,[m],{},'2027-04')[0]
    assert row['all_met']
    assert {key:c['count'] for key,c in row['checks'].items()}=={'weekday_night':2,'holiday_duty':2,'friday_night':1}
    assert not anesthesia_checks(slots,[m],{},'2027-05')
    slots[0]['member_id']=None
    row=anesthesia_checks(slots,[m],{},'2027-04')[0]
    assert not row['all_met']
    assert row['checks']['weekday_night']['count']==1
    assert row['checks']['holiday_duty']['count']==1
    assert row['checks']['friday_night']['count']==0

def test_api_recalculates_status_after_edit_and_undo(client):
    mid=member(client,rotations=[{'kind':'anesthesia','start':'2027-04-01','end':'2027-04-30'}])
    p=plan(client)
    row=p['anesthesia_checks']['2027-04'][0]
    assert not row['all_met'] and all(c['count']==0 for c in row['checks'].values())
    s=next(s for s in p['slots'] if s['date']=='2027-04-02' and s['kind']=='night' and s['number']==1)
    p=edit(client,p,s['id'],member_id=mid).json()
    row=p['anesthesia_checks']['2027-04'][0]
    assert row['checks']['friday_night']['met']
    assert row['checks']['weekday_night']['count']==1
    assert row['checks']['holiday_duty']['count']==1
    assert not row['all_met']
    p=client.post(f'/api/plans/{p["id"]}/undo',json={'version':p['version']}).json()
    assert all(c['count']==0 for c in p['anesthesia_checks']['2027-04'][0]['checks'].values())
    other=plan(client)
    assert all(c['count']==0 for c in other['anesthesia_checks']['2027-04'][0]['checks'].values())

def test_pdf_removes_requested_note(client):
    member(client);p=plan(client)
    response=client.get(f'/api/plans/{p["id"]}/pdf')
    assert response.status_code==200
    with pymupdf.open(stream=response.content,filetype='pdf') as pdf:
        text=''.join(page.get_text() for page in pdf)
    assert '名称は全学年' not in text
    assert '最短間隔は勤務開始日の差' not in text
    assert '金曜当直は平日当直に集計' not in text
    assert '平日当直' in text and '最短間隔' in text
