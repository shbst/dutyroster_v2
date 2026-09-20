import json
import secrets
import calendar
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .db import initialize, connect, all_members, all_slots
from .rules import START, END, dates, holiday, holiday_name, validate, summary, reasons, anesthesia_checks, HARD_RULES, SOFT_RULES
from .solver import generate
from .rotations import ROTATION_SITES, normalize_legacy_rotation

ROOT=Path(__file__).resolve().parent.parent

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app=FastAPI(title='当直ノート',lifespan=lifespan)

@app.middleware('http')
async def same_origin(request:Request, call_next):
    # Reject cross-origin writes to the local/shared server.
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin!=str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'別のサイトからの更新は許可されていません。'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    elif request.url.path=='/' or request.url.path.startswith('/static/'):
        response.headers['Cache-Control']='no-cache'
    return response

class Period(BaseModel):
    start:date
    end:date
    @model_validator(mode='after')
    def check(self):
        if not START<=self.start<=self.end<=END: raise ValueError('期間は2026/4/1〜2028/3/31内で指定してください')
        return self

class Rotation(Period):
    kind:Literal['anesthesia','psychiatry','outpatient','community','remote']
    hospital:str=Field(default='',max_length=80)

    @model_validator(mode='after')
    def check_placement(self):
        self.kind, self.hospital = normalize_legacy_rotation(self.kind, self.hospital)
        if self.hospital not in {value for value, label in ROTATION_SITES[self.kind]}:
            raise ValueError('研修科に対応する配属先を選択してください')
        return self

class Event(BaseModel):
    date:date
    kind:Literal['counseling','training','no_training']='counseling'
    @model_validator(mode='after')
    def check(self):
        if not START<=self.date<=END: raise ValueError('研修日は対象期間内にしてください')
        if self.kind=='counseling' and self.date.weekday()!=5: raise ValueError('カウンセリング研修は土曜日を指定してください')
        return self

class Member(BaseModel):
    name:str=Field(min_length=1,max_length=40)
    color:str=Field(default='#dce9fb',pattern=r'^#[0-9a-fA-F]{6}$')
    archived:bool=False
    periods:list[Period]=Field(min_length=1,max_length=30)
    rotations:list[Rotation]=Field(default_factory=list,max_length=100)
    events:list[Event]=Field(default_factory=list,max_length=200)
    @model_validator(mode='after')
    def check(self):
        self.name=self.name.strip()
        if not self.name: raise ValueError('名前を入力してください')
        for records in (self.periods,self.rotations):
            ordered=sorted(records,key=lambda p:p.start)
            if any(a.end>=b.start for a,b in zip(ordered,ordered[1:])): raise ValueError('同じ種類の期間を重複させないでください')
        return self

class NewPlan(Period):
    name:str=Field(default='当直表',min_length=1,max_length=80)

class Edit(BaseModel):
    version:int
    slot_id:int
    member_id:int|None=None
    target_id:int|None=None
    locked:bool|None=None

class SlotEdit(BaseModel):
    version:int
    enabled:bool

class Version(BaseModel):
    version:int

class HolidayInput(BaseModel):
    date:date
    name:str=Field(min_length=1,max_length=40)

def custom_holidays(db): return {r['date']:r['name'] for r in db.execute('SELECT * FROM holidays')}
def plan_row(db,pid):
    row=db.execute('SELECT * FROM plans WHERE id=?',(pid,)).fetchone()
    if not row: raise HTTPException(404,'当直表が見つかりません')
    return dict(row)
def writable(db,pid,version):
    p=plan_row(db,pid)
    if p['version']!=version: raise HTTPException(409,'別の操作で更新されています。再読み込みしてください。')
    if p['status']=='final': raise HTTPException(409,'確定済みです。「編集を再開」を押してください。')
    return p
def snapshot(db,pid,action):
    state={'plan':plan_row(db,pid),'slots':all_slots(db,pid),'members':all_members(db),'holidays':custom_holidays(db)}
    db.execute('INSERT INTO history(plan_id,action,snapshot) VALUES(?,?,?)',(pid,action,json.dumps(state,ensure_ascii=False)))
def bump(db,pid): db.execute('UPDATE plans SET version=version+1 WHERE id=?',(pid,))
def check_all(db,pid=None):
    members=all_members(db); custom=custom_holidays(db)
    ids=[pid] if pid is not None else [r['id'] for r in db.execute('SELECT id FROM plans')]
    errors=[f'当直表 #{plan_id}：{error}' for plan_id in ids for error in validate(all_slots(db,plan_id),members,custom)]
    if errors: raise HTTPException(422,errors)

def persist_slots(db,slots):
    for s in slots:
        db.execute('UPDATE slots SET enabled=?,origin=? WHERE id=?',(s['enabled'],s['origin'],s['id']))
        db.execute('DELETE FROM assignments WHERE slot_id=?',(s['id'],))
        if s.get('member_id') is not None:
            db.execute('INSERT INTO assignments(slot_id,member_id,locked,source) VALUES(?,?,?,?)',(s['id'],s['member_id'],s.get('locked',0),s.get('source') or 'manual'))

@app.get('/api/bootstrap')
def bootstrap():
    with connect() as db:
        return {'api_version':3,'members':all_members(db),'plans':[dict(r) for r in db.execute('SELECT * FROM plans ORDER BY start DESC')],
                'hard_rules':HARD_RULES,'soft_rules':SOFT_RULES,'holidays':custom_holidays(db),'rotation_sites':ROTATION_SITES}

@app.post('/api/members')
def create_member(data:Member):
    return save_member(None,data)

@app.put('/api/members/{mid}')
def update_member(mid:int,data:Member):
    return save_member(mid,data)

def save_member(mid,data):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if mid is None:
            mid=db.execute('INSERT INTO members(name,color,archived) VALUES(?,?,?)',(data.name,data.color,data.archived)).lastrowid
        else:
            if not db.execute('SELECT id FROM members WHERE id=?',(mid,)).fetchone(): raise HTTPException(404,'メンバーが見つかりません')
            db.execute('UPDATE members SET name=?,color=?,archived=? WHERE id=?',(data.name,data.color,data.archived,mid))
        for table in ('eligibility','rotations','training_events'): db.execute(f'DELETE FROM {table} WHERE member_id=?',(mid,))
        for p in data.periods: db.execute('INSERT INTO eligibility(member_id,start,end) VALUES(?,?,?)',(mid,p.start.isoformat(),p.end.isoformat()))
        for r in data.rotations: db.execute('INSERT INTO rotations(member_id,kind,hospital,start,end) VALUES(?,?,?,?,?)',(mid,r.kind,r.hospital,r.start.isoformat(),r.end.isoformat()))
        for e in data.events: db.execute('INSERT OR IGNORE INTO training_events(member_id,date,kind) VALUES(?,?,?)',(mid,e.date.isoformat(),e.kind))
        check_all(db)
        db.execute('UPDATE plans SET version=version+1')
    return {'id':mid}

@app.post('/api/holidays')
def add_holiday(data:HolidayInput):
    ds=data.date.isoformat()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT id FROM plans WHERE start<=? AND end>=? AND status='final'",(ds,ds)).fetchone(): raise HTTPException(409,'この日を含む確定表の編集を再開してください')
        db.execute('INSERT OR REPLACE INTO holidays(date,name) VALUES(?,?)',(ds,data.name))
        db.execute("UPDATE slots SET enabled=1 WHERE date=? AND number=1",(ds,))
        check_all(db); db.execute('UPDATE plans SET version=version+1')
    return {'ok':True}

@app.post('/api/plans')
def create_plan(data:NewPlan):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        pid=db.execute('INSERT INTO plans(name,start,end) VALUES(?,?,?)',(data.name,data.start.isoformat(),data.end.isoformat())).lastrowid
        custom=custom_holidays(db); chosen=set(); weeks={}
        for d in dates(data.start,data.end):
            if d.weekday()<5: weeks.setdefault(d-timedelta(days=d.weekday()),[]).append(d)
        for week in weeks.values():
            hs=sum(holiday(d,custom) for d in week)
            options=sorted([d for d in week if not holiday(d,custom)],key=lambda d:({4:0,0:1,2:2,1:3,3:4}[d.weekday()]))
            chosen.update(options[:max(0,3-hs)])
        for d in dates(data.start,data.end):
            for kind in ('day','night'):
                for number in (1,2):
                    on=number==1 and (holiday(d,custom) or (kind=='night' and d in chosen))
                    db.execute('INSERT INTO slots(plan_id,date,kind,number,enabled) VALUES(?,?,?,?,?)',(pid,d.isoformat(),kind,number,on))
        return {'id':pid}

@app.get('/api/plans/{pid}')
def get_plan(pid:int):
    with connect() as db:
        p=plan_row(db,pid); slots=all_slots(db,pid); members=all_members(db); custom=custom_holidays(db); all_s=slots
        months=sorted(set(d.strftime('%Y-%m') for d in dates(p['start'],p['end'])))
        unfilled=[]
        for s in slots:
            if s['enabled'] and not s.get('member_id'):
                candidates=[m for m in members if not m['archived'] and not reasons(m,s,custom)]
                reason='対象期間・研修条件に合うメンバーがいません' if not candidates else '現在の案では未充足です。月の上限・連日禁止・固定勤務・枠数を確認してください'
                unfilled.append({'slot_id':s['id'],'date':s['date'],'kind':s['kind'],'number':s['number'],'reason':reason})
        run=db.execute('SELECT result FROM generation_runs WHERE plan_id=? ORDER BY id DESC LIMIT 1',(pid,)).fetchone()
        history=[dict(r) for r in db.execute('SELECT id,action,created_at FROM history WHERE plan_id=? ORDER BY id DESC LIMIT 10',(pid,))]
        return {**p,'slots':slots,'members':members,'months':months,'days':{d.isoformat():{'holiday':holiday(d,custom),'name':holiday_name(d,custom)} for d in dates(p['start'],p['end'])},
                'summaries':{m:summary(all_s,members,custom,m) for m in months},'anesthesia_checks':{m:anesthesia_checks(slots,members,custom,m) for m in months},'errors':validate(all_s,members,custom),'unfilled':unfilled,'last_run':json.loads(run['result']) if run else None,'history':history}

@app.post('/api/plans/{pid}/generate')
def generate_plan(pid:int,data:Version):
    with connect() as db:
        p=writable(db,pid,data.version); slots=all_slots(db,pid); external=[]; members=all_members(db); custom=custom_holidays(db)
    seed=secrets.randbelow(1000000)
    try: result,report=generate(p,slots,external,members,custom,seed)
    except ValueError as e: raise HTTPException(422,str(e))
    errors=validate(result+external,members,custom)
    if errors: raise HTTPException(422,errors)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE'); writable(db,pid,data.version)
        snapshot(db,pid,'自動生成'); persist_slots(db,result); bump(db,pid)
        db.execute('INSERT INTO generation_runs(plan_id,seed,result,inputs) VALUES(?,?,?,?)',(pid,seed,json.dumps(report),json.dumps({'members':members,'holidays':custom,'external':external,'rule_version':2},ensure_ascii=False)))
    return get_plan(pid)

@app.post('/api/plans/{pid}/assignment')
def edit_assignment(pid:int,data:Edit):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE'); writable(db,pid,data.version)
        slots=all_slots(db,pid); byid={s['id']:s for s in slots}; s=byid.get(data.slot_id)
        if not s: raise HTTPException(404,'枠が見つかりません')
        snapshot(db,pid,'担当者の変更')
        if data.locked is not None:
            if not s.get('member_id'): raise HTTPException(422,'担当者を入れてから固定してください')
            s['locked']=int(data.locked)
        else:
            if s['locked']: raise HTTPException(422,'固定を解除してから変更してください')
            if data.target_id is not None:
                t=byid.get(data.target_id)
                if not t or not t['enabled']: raise HTTPException(422,'移動先は有効な枠を指定してください')
                if t['locked']: raise HTTPException(422,'移動先が固定されています')
                s['member_id'],t['member_id']=t['member_id'],s['member_id']; t['source']='manual'
            else:
                if data.member_id is not None and not db.execute('SELECT id FROM members WHERE id=?',(data.member_id,)).fetchone():
                    raise HTTPException(422,'メンバーが見つかりません')
                s['member_id']=data.member_id
            s['source']='manual'
            if not s['enabled']: raise HTTPException(422,'この枠を有効にしてください')
        persist_slots(db,slots); check_all(db,pid); bump(db,pid)
    return get_plan(pid)

@app.put('/api/plans/{pid}/slots/{sid}')
def edit_slot(pid:int,sid:int,data:SlotEdit):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE'); writable(db,pid,data.version)
        slots=all_slots(db,pid); s=next((s for s in slots if s['id']==sid),None)
        if not s: raise HTTPException(404,'枠が見つかりません')
        if s['locked'] or s.get('member_id'): raise HTTPException(422,'担当者を解除してから枠を変更してください')
        d=date.fromisoformat(s['date']); custom=custom_holidays(db)
        if s['kind']=='day' and not holiday(d,custom): raise HTTPException(422,'平日の日直は作成できません')
        if not data.enabled and s['number']==1 and holiday(d,custom): raise HTTPException(422,'休日の日直・当直は各1枠が必須です')
        if s['number']==2 and data.enabled:
            first=next(t for t in slots if t['date']==s['date'] and t['kind']==s['kind'] and t['number']==1)
            if not first['enabled']: raise HTTPException(422,'先に1枠目を有効にしてください')
        if s['number']==1 and not data.enabled and any(t['date']==s['date'] and t['kind']==s['kind'] and t['number']==2 and t['enabled'] for t in slots): raise HTTPException(422,'先に2枠目を解除してください')
        snapshot(db,pid,'必要枠の変更'); s['enabled']=int(data.enabled); s['origin']='manual'; persist_slots(db,slots); bump(db,pid)
    return get_plan(pid)

@app.post('/api/plans/{pid}/undo')
def undo(pid:int,data:Version):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE'); writable(db,pid,data.version)
        row=db.execute("SELECT * FROM history WHERE plan_id=? AND action!='確定' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
        if not row: raise HTTPException(422,'取り消せる操作がありません')
        snap=json.loads(row['snapshot']); persist_slots(db,snap['slots']); check_all(db,pid)
        db.execute('DELETE FROM history WHERE id=?',(row['id'],)); bump(db,pid)
    return get_plan(pid)

@app.post('/api/plans/{pid}/finalize')
def finalize(pid:int,data:Version):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE'); writable(db,pid,data.version); check_all(db,pid)
        if any(s['enabled'] and not s.get('member_id') for s in all_slots(db,pid)): raise HTTPException(422,'未割り当ての枠があります')
        snapshot(db,pid,'確定'); db.execute("UPDATE plans SET status='final',version=version+1 WHERE id=?",(pid,))
    return get_plan(pid)

@app.post('/api/plans/{pid}/reopen')
def reopen(pid:int,data:Version):
    with connect() as db:
        p=plan_row(db,pid)
        if p['version']!=data.version: raise HTTPException(409,'再読み込みしてください')
        db.execute("UPDATE plans SET status='draft',version=version+1 WHERE id=?",(pid,))
    return get_plan(pid)

@app.get('/api/plans/{pid}/pdf')
def pdf(pid:int):
    from .pdf import make_pdf
    data=get_plan(pid)
    with connect() as db:
        if data['status']=='final':
            r=db.execute("SELECT snapshot FROM history WHERE plan_id=? AND action='確定' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
            if r:
                saved=json.loads(r['snapshot']); data['members']=saved['members']; data['slots']=saved['slots']
                data['summaries']={m:summary(saved['slots'],saved['members'],saved['holidays'],m) for m in data['months']}
    return Response(make_pdf(data),media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="duty-{data["start"]}.pdf"'})

@app.delete('/api/plans/{pid}')
def delete_plan(pid:int,data:Version):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        p=plan_row(db,pid)
        if p['version']!=data.version: raise HTTPException(409,'別の操作で更新されています。再読み込みしてください。')
        db.execute('DELETE FROM assignments WHERE slot_id IN (SELECT id FROM slots WHERE plan_id=?)',(pid,))
        for table in ('slots','history','generation_runs'):
            db.execute(f'DELETE FROM {table} WHERE plan_id=?',(pid,))
        db.execute('DELETE FROM plans WHERE id=?',(pid,))
    return {'ok':True}

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
