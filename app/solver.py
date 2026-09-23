"""Monthly CP-SAT scheduling. Hard rules are shared with the editor validator."""
import calendar
import random
from math import gcd
from datetime import date, timedelta
from ortools.sat.python import cp_model
from .rules import dates, eligible, reasons, holiday, holiday_duty, category, rotation_on, anesthesia_groups, shifts_conflict

GAP_PENALTIES = {1:400,2:260,3:180,4:110,5:60,6:25,7:5}

def generate(plan, slots, external, members, custom, seed):
    rng=random.Random(seed)
    slots=[dict(s) for s in slots]
    members=[m for m in members if not m['archived'] or any(s.get('member_id')==m['id'] and s.get('locked') for s in slots)]
    if not members: raise ValueError('当直対象のメンバーを登録してください。')
    reports=[]
    months=sorted(set(d.strftime('%Y-%m') for d in dates(plan['start'],plan['end'])))
    for month in months:
        group=[s for s in slots if s['date'].startswith(month)]
        # Later unlocked assignments will be regenerated; earlier solved months and all locks are fixed context.
        context=external+[s for s in slots if not s['date'].startswith(month) and (s['date'][:7]<month or s.get('locked')) and s.get('member_id')]
        model=cp_model.CpModel(); x={}; used={}; enabled={}; soft=[]; missing=[]; missing_holiday=[]; total_fair=[]; category_fair=[]
        for s in group:
            d=date.fromisoformat(s['date']); sid=s['id']
            y=model.new_bool_var(f'on_{sid}'); enabled[sid]=y
            variable=s['origin']=='auto' and s['kind']=='night' and s['number']==1 and not holiday(d,custom) and not s.get('locked')
            if not variable: model.add(y==int(s['enabled']))
            else: soft.append(160*y)
            candidates=[]
            for m in members:
                mid=m['id']
                v=model.new_bool_var(f'x_{sid}_{mid}'); x[sid,mid]=v
                blocked=(m['archived'] and not (s.get('locked') and s.get('member_id')==mid)) or reasons(m,s,custom) or any(t.get('member_id')==mid and shifts_conflict(t,s) for t in context)
                if blocked: model.add(v==0)
                if s.get('locked') and s.get('member_id'):
                    model.add(v==int(mid==s['member_id']))
                candidates.append(v)
                # Seed only breaks otherwise similar choices.
                soft.append(rng.randrange(4)*v)
                for r in rotation_on(m,d):
                    prefers=r['kind'] in ('outpatient','community') or (r['kind']=='psychiatry' and r['hospital']=='shin_abuyama')
                    if prefers and not holiday_duty(s,custom): soft.append(100*v)
            model.add(sum(candidates)<=y)
            miss=model.new_bool_var(f'missing_{sid}'); model.add(miss==y-sum(candidates)); missing.append(miss)
            if holiday(d,custom): missing_holiday.append(miss)
        for s in group:
            if s['number']==2:
                first=next(t for t in group if t['date']==s['date'] and t['kind']==s['kind'] and t['number']==1)
                model.add(enabled[s['id']]<=enabled[first['id']])
        # Only this plan participates. Cap automatic weekdays at three per week,
        # counting weekday holidays; explicit extra slots and locks are retained.
        weeks={}
        for s in group:
            d=date.fromisoformat(s['date'])
            if d.weekday()<5 and s['kind']=='night' and s['number']==1:
                monday=d-timedelta(days=d.weekday()); weeks.setdefault(monday,[]).append(s)
        for monday,week in weeks.items():
            # A week crossing a month is settled by its earlier solved days / future minimum allowance.
            outside_dates={t['date'] for t in slots if t['date'][:7]<month and t['kind']=='night' and t['number']==1 and t['enabled'] and monday<=date.fromisoformat(t['date'])<=monday+timedelta(days=4)}
            future_slots=[t for t in slots if t['date'][:7]>month and t['kind']=='night' and t['number']==1 and monday<=date.fromisoformat(t['date'])<=monday+timedelta(days=4)]
            def forced(t):
                return t['enabled'] and (t['origin']=='manual' or t.get('locked') or holiday(date.fromisoformat(t['date']),custom) or any(u['date']==t['date'] and u['kind']=='night' and u['number']==2 and u['enabled'] for u in slots))
            future_days=[t for t in future_slots if t['enabled'] or t['origin']=='auto']
            potential=[s for s in week if s['enabled'] or s['origin']=='auto']
            required=max(0,min(len(potential),3-len(outside_dates)-len(future_days)))
            model.add(sum(enabled[s['id']] for s in week)>=required)
            limit=max(required,sum(bool(forced(s)) for s in week),3-len(outside_dates)-sum(bool(forced(s)) for s in future_slots))
            model.add(sum(enabled[s['id']] for s in week)<=limit)
        for m in members:
            mid=m['id']; bydate={}
            for s in group: bydate.setdefault(s['date'],[]).append(x[s['id'],mid])
            for ds,vs in bydate.items():
                u=model.new_bool_var(f'used_{mid}_{ds}'); model.add(u==sum(vs)); used[mid,ds]=u
            ordered=sorted(bydate)
            for i,ds in enumerate(ordered):
                d=date.fromisoformat(ds)
                for other in ordered[i+1:]:
                    gap=(date.fromisoformat(other)-d).days
                    if gap>7: break
                    a=used[mid,ds]; b=used[mid,other]
                    if gap==1:
                        nights=sum(x[s['id'],mid] for s in group if s['date']==ds and s['kind']=='night')
                        model.add(nights+b<=1)
                    pair=model.new_bool_var(f'near_{mid}_{ds}_{other}')
                    model.add(pair>=a+b-1)
                    soft.append(GAP_PENALTIES[gap]*pair)
                for t in context:
                    if t.get('member_id')==mid:
                        gap=abs((date.fromisoformat(t['date'])-d).days)
                        if 1<=gap<=7: soft.append(GAP_PENALTIES[gap]*used[mid,ds])
            count=sum(x[s['id'],mid] for s in group)+sum(t.get('member_id')==mid and t['date'].startswith(month) for t in context)
            if month<'2027-04': model.add(count<=4)
            first=date.fromisoformat(month+'-01'); last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
            for r in m['rotations']:
                if r['kind']!='anesthesia' or r['start']>last.isoformat() or r['end']<first.isoformat(): continue
                period=[s for s in group if r['start']<=s['date']<=r['end']]
                if not period: continue
                for key,target,weight,subset in anesthesia_groups(period,custom):
                    deficit=model.new_int_var(0,target,'anesthesia_deficit')
                    model.add(deficit>=target-sum(x[s['id'],mid] for s in subset)); soft.append(weight*deficit)
        # Distance from each member's proportional share; linear in member count.
        first=date.fromisoformat(month+'-01'); last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
        active_start=max(first,date.fromisoformat(plan['start'])); active_end=min(last,date.fromisoformat(plan['end']))
        activity={m['id']:sum(eligible(m,d) for d in dates(active_start,active_end)) for m in members}
        divisor=gcd(*activity.values()) or 1
        weights={mid:days//divisor for mid,days in activity.items()}
        total_weight=sum(weights.values())
        for cat in (None,'weekday_night','holiday_day','holiday_night'):
            subset=[s for s in group if cat is None or category(s,custom)==cat]
            counts={m['id']:sum(x[s['id'],m['id']] for s in subset) for m in members}
            total_count=sum(counts.values())
            for mid,days in weights.items():
                if not days: continue
                dev=model.new_int_var(0,max(1,2*len(group)*total_weight),'fair')
                model.add_abs_equality(dev,counts[mid]*total_weight-total_count*days)
                (total_fair if cat is None else category_fair).append(dev)
        solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=3; solver.parameters.num_search_workers=4; solver.parameters.random_seed=seed
        # Fill holidays first, then all enabled slots, before optimizing distribution.
        for objective in (sum(missing_holiday),sum(missing)):
            model.minimize(objective); status=solver.solve(model)
            if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                raise ValueError(f'{month}：固定した勤務と条件が矛盾しています。固定を見直してください。' if status==cp_model.INFEASIBLE else f'{month}：時間内に配置案が見つかりませんでした。再実行してください。')
            model.add(objective<=int(solver.value(objective)))
        def capture():
            saved={s['id']:(int(solver.value(enabled[s['id']])),next((m['id'] for m in members if solver.value(x[s['id'],m['id']])),None)) for s in group}
            model.clear_hints()
            for v in [*x.values(),*enabled.values()]: model.add_hint(v,solver.value(v))
            return saved
        fallback=capture()
        # Preserve balanced totals before balancing the three categories; then
        # improve spacing and rotation preferences without undoing those gains.
        solver.parameters.max_time_in_seconds=4
        for objective in (sum(total_fair),sum(category_fair)):
            model.minimize(objective); status=solver.solve(model)
            if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                model.add(objective<=int(solver.value(objective)))
                fallback=capture()
        model.minimize(sum(soft)); solver.parameters.max_time_in_seconds=7; status=solver.solve(model)
        solved=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
        for s in group:
            on,mid=(int(solver.value(enabled[s['id']])),next((m['id'] for m in members if solver.value(x[s['id'],m['id']])),None)) if solved else fallback[s['id']]
            s.update(enabled=on,member_id=mid)
            if not s.get('locked'): s['source']='auto'
        reports.append({'month':month,'status':solver.status_name(status),'unfilled':sum(s['enabled'] and not s.get('member_id') for s in group)})
    return slots,reports
