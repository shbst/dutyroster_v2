"""Create an isolated, disposable preview database. Never touches the application's database."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import db
from fastapi.testclient import TestClient
from app.main import app

db.DB_PATH=Path('tmp/preview.sqlite3')
with TestClient(app) as c:
    if not c.get('/api/bootstrap').json()['members']:
        for i,name in enumerate(['青木','石井','上田','大野','加藤','佐藤','高橋','中村']):
            body={'name':f'{name}（デモ）','color':['#dce9fb','#e1efdf','#ece2f6','#f8e6dc','#dcf0ef','#f4e2ed','#e8e9ce','#e1e3f7'][i],'periods':[{'start':'2026-04-01','end':'2028-03-31'}]}
            if i==0: body['rotations']=[{'kind':'anesthesia','start':'2027-04-01','end':'2027-04-30'}]
            if i==1: body['rotations']=[{'kind':'psychiatry','hospital':'shin_abuyama','start':'2027-05-01','end':'2027-05-31'}]
            r=c.post('/api/members',json=body);assert r.status_code==200,r.text
    if not c.get('/api/bootstrap').json()['plans']:
        r=c.post('/api/plans',json={'name':'操作確認用・デモ当直表','start':'2027-04-01','end':'2027-05-31'});assert r.status_code==200,r.text
        pid=r.json()['id'];p=c.get(f'/api/plans/{pid}').json()
        r=c.post(f'/api/plans/{pid}/generate',json={'version':p['version']});assert r.status_code==200,r.text
    p=c.get('/api/plans/1').json()
    print('assigned',sum(bool(s['member_id']) for s in p['slots']),'unfilled',len(p['unfilled']))
    Path('tmp/pdfs').mkdir(parents=True,exist_ok=True)
    r=c.get('/api/plans/1/pdf');assert r.status_code==200
    Path('tmp/pdfs/preview.pdf').write_bytes(r.content)
    import fitz
    pdf=fitz.open(stream=r.content,filetype='pdf')
    for i,page in enumerate(pdf): page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(f'tmp/pdfs/page-{i+1}.png')
    print('PDF pages',len(pdf))
