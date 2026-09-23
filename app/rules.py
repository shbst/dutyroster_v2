from datetime import date, timedelta
import calendar
import holidays

START = date(2026, 4, 1)
END = date(2028, 3, 31)
YEAR2 = date(2027, 4, 1)
JP = holidays.Japan(years=range(2026, 2029), language='ja')

HARD_RULES = [
 '対象は2026年4月入職の成人系メンバー。登録した当直対象期間内に割り当てます。',
 '同じ日の日直・当直の兼任、同じ人の2枠への配置は禁止します。当直の翌日は日直・当直とも不可。日直の翌日はどちらも可能です。',
 '1年目（2027年3月まで）は日直・当直を合わせ月4回が上限です。',
 '精神科研修中は月曜当直不可。土曜カウンセリング日は日直・当直とも不可です。',
 '新阿武山病院研修中は平日当直と、各研修日の前日の当直が不可です。',
 'へき地医療研修期間は日直・当直とも不可です。',
 '有効な枠は1枠1名。2名配置は指定した2枠目がある勤務だけです。',
]
SOFT_RULES = [
 '土日祝は日直・当直各1枠を初期設定し、手動で無効化できます。有効な休日枠と指定した必要枠を優先して埋めます。',
 '月4回を最低回数にしません。必要な枠を分担し、合計3回以下も許容します。',
 '同じ人の勤務間隔をできるだけ空け、短い間隔への集中を避けます。月をまたいでも評価します。',
 '公平性は各月の当直対象者と在籍日数で評価します。退職予定の人への前倒し配置はしません。',
 '合計回数に加え、平日当直・休日日直・休日当直それぞれの回数をできるだけ均等にします。',
 '麻酔科は平日当直2回と休日系2回を目標とし、金曜当直1回を優先します。金曜は両条件への重複計上可、実勤務は1回です。',
 '外来・地域・新阿武山病院研修中は、休日日直・明け休日当直を優先します。',
 '月〜金は祝日を含め原則週3日。月4回に合わせるための枠追加はしません。指定した追加枠・固定勤務は維持します。',
 '各当直表は独立した案です。同じ期間に複数作成でき、別の案との連続勤務や回数は合算しません。',
]

def dates(start, end):
    d = date.fromisoformat(start) if isinstance(start,str) else start
    e = date.fromisoformat(end) if isinstance(end,str) else end
    while d <= e:
        yield d
        d += timedelta(days=1)

def holiday(d, custom):
    return d.weekday() >= 5 or d in JP or d.isoformat() in custom

def holiday_name(d, custom):
    return custom.get(d.isoformat(), JP.get(d, ''))

def eligible(m, d):
    return any(p['start'] <= d.isoformat() <= p['end'] for p in m['periods'])

def rotation_on(m, d):
    return [r for r in m['rotations'] if r['start'] <= d.isoformat() <= r['end']]

def category(s, custom):
    d = date.fromisoformat(s['date'])
    return 'weekday_night' if not holiday(d, custom) else ('holiday_day' if s['kind']=='day' else 'holiday_night')

def holiday_duty(s, custom):
    d = date.fromisoformat(s['date'])
    return (s['kind']=='day' and holiday(d,custom)) or (s['kind']=='night' and holiday(d+timedelta(days=1),custom))

def anesthesia_groups(period, custom):
    """Shared definitions for optimization and displayed progress (Friday may overlap)."""
    return [
        ('weekday_night',2,100,[s for s in period if category(s,custom)=='weekday_night']),
        ('holiday_duty',2,100,[s for s in period if holiday_duty(s,custom)]),
        ('friday_night',1,50,[s for s in period if date.fromisoformat(s['date']).weekday()==4 and s['kind']=='night']),
    ]

def anesthesia_checks(slots,members,custom,month):
    result=[]
    for m in members:
        for r in m['rotations']:
            if r['kind']!='anesthesia': continue
            period=[s for s in slots if s['date'].startswith(month) and r['start']<=s['date']<=r['end']]
            if not period: continue
            assigned=[s for s in period if s['enabled'] and s.get('member_id')==m['id']]
            if not assigned and (m.get('archived') or not any(eligible(m,date.fromisoformat(s['date'])) for s in period)): continue
            checks={key:{'count':len(subset),'target':target,'met':len(subset)>=target} for key,target,weight,subset in anesthesia_groups(assigned,custom)}
            result.append({'member_id':m['id'],'name':m['name'],'start':min(s['date'] for s in period),'end':max(s['date'] for s in period),
                           'checks':checks,'all_met':all(c['met'] for c in checks.values())})
    return result

def reasons(m, s, custom):
    d = date.fromisoformat(s['date'])
    errors = []
    if not eligible(m,d): errors.append('当直対象期間外')
    if s['kind']=='day' and not holiday(d,custom): errors.append('平日に日直は設定できません')
    if any(e['date']==s['date'] and e['kind']=='counseling' for e in m['events']):
        errors.append('カウンセリング研修日')
    for r in rotation_on(m,d):
        if r['kind']=='remote' or (r['kind']=='community' and r['hospital']=='remote'):
            errors.append('へき地医療研修中')
        if r['kind']=='psychiatry':
            if d.weekday()==0 and s['kind']=='night': errors.append('精神科の月曜当直不可')
            if r['hospital']=='shin_abuyama' and not holiday(d,custom) and s['kind']=='night':
                errors.append('新阿武山病院の平日当直不可')
    tomorrow = d+timedelta(days=1)
    for r in rotation_on(m,tomorrow):
        if r['kind']=='psychiatry' and r['hospital']=='shin_abuyama' and s['kind']=='night':
            exception = next((e['kind'] for e in m['events'] if e['date']==tomorrow.isoformat() and e['kind'] in ('training','no_training')),None)
            training = exception=='training' or (exception!='no_training' and not holiday(tomorrow,custom))
            if training: errors.append('新阿武山病院の研修日前夜')
    return list(dict.fromkeys(errors))

def shifts_conflict(a, b):
    """Same-day duties conflict; only a night duty blocks the following day."""
    if a['date'] > b['date']:
        a, b = b, a
    gap = (date.fromisoformat(b['date']) - date.fromisoformat(a['date'])).days
    return gap == 0 or (gap == 1 and a['kind'] == 'night')


def validate(slots, members, custom):
    by_id = {m['id']:m for m in members}
    errors = []
    grouped = {}
    for s in slots:
        if s.get('member_id') is None: continue
        m = by_id.get(s['member_id'])
        if not m:
            errors.append('未登録のメンバーです'); continue
        for reason in reasons(m,s,custom): errors.append(f"{s['date']} {m['name']}：{reason}")
        if not s['enabled']: errors.append(f"{s['date']}：無効な枠に割り当てがあります")
        grouped.setdefault(m['id'],[]).append(s)
    for mid, assigned in grouped.items():
        ordered = sorted(assigned,key=lambda s:s['date'])
        counts = {}
        for s in ordered:
            month=s['date'][:7]; counts[month]=counts.get(month,0)+1
        for month,count in counts.items():
            if month<'2027-04' and count>4: errors.append(f"{month} {by_id[mid]['name']}：1年目の月4回上限を超えています")
        for a,b in zip(ordered,ordered[1:]):
            if shifts_conflict(a,b):
                detail='同日に複数の勤務があります' if a['date']==b['date'] else '当直の翌日に勤務があります'
                errors.append(f"{by_id[mid]['name']}：{a['date']} と {b['date']} は{detail}")
    return list(dict.fromkeys(errors))

def summary(slots,members,custom,month):
    result=[]
    first=date.fromisoformat(month+'-01'); last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
    for m in members:
        selected=[s for s in slots if s.get('member_id')==m['id'] and s['date'].startswith(month)]
        active=sum(eligible(m,d) for d in dates(first,last))
        if not active and not selected: continue
        row={'id':m['id'],'name':m['name'],'color':m['color'],'weekday_night':0,'holiday_day':0,'holiday_night':0,'total':len(selected),'active_days':active,'min_gap':None}
        for s in selected: row[category(s,custom)]+=1
        all_dates=sorted(date.fromisoformat(s['date']) for s in slots if s.get('member_id')==m['id'])
        gaps=[(b-a).days for a,b in zip(all_dates,all_dates[1:]) if a.strftime('%Y-%m')==month or b.strftime('%Y-%m')==month]
        if gaps: row['min_gap']=min(gaps)
        result.append(row)
    return result
