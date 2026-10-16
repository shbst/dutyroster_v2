import pymupdf
from test_app import client, member, plan, edit


def test_pdf_last_page_contains_whole_plan_totals_and_frozen_names(client):
    mid=member(client,'集計担当')
    p=plan(client,'2027-04-03','2027-05-04')
    for ds,kind in [('2027-04-03','day'),('2027-04-10','night'),('2027-05-04','night')]:
        s=next(s for s in p['slots'] if s['date']==ds and s['kind']==kind and s['number']==1)
        r=edit(client,p,s['id'],member_id=mid)
        assert r.status_code==200,r.text
        p=r.json()
    def check_pdf():
        r=client.get(f'/api/plans/{p["id"]}/pdf')
        assert r.status_code==200,r.text
        doc=pymupdf.open(stream=r.content,filetype='pdf')
        assert len(doc)==3
        text=doc[-1].get_text()
        assert '当直表全期間の集計' in text and '2027-04-03 - 2027-05-04' in text
        assert '集計担当\n0\n1\n2\n3\n' in text
        assert '全員合計\n0\n1\n2\n3\n' in text
        assert '変更後の名前' not in text
    check_pdf()
    r=client.post(f'/api/plans/{p["id"]}/finalize',json={'version':p['version']})
    assert r.status_code==200,r.text
    m=client.get('/api/bootstrap').json()['members'][0]
    m['name']='変更後の名前'
    assert client.put(f'/api/members/{mid}',json=m).status_code==200
    check_pdf()
