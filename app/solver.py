"""Monthly CP-SAT scheduling. Hard rules are shared with the editor validator."""
import calendar
import random
from math import gcd
from datetime import date, timedelta
from ortools.sat.python import cp_model
from .rules import YEAR2, dates, eligible, reasons, holiday, holiday_duty, category, rotation_on, anesthesia_groups, shifts_conflict, exact_month_members, validate

GAP_PENALTIES = {1:400,2:260,3:180,4:110,5:60,6:25,7:5}

def solve_with_progress(solver, model, progress, **info):
    if progress is None: return solver.solve(model)
    progress(**info, candidates=0)
    class Updates(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__(); self.count=0; self.last=-1
        def on_solution_callback(self):
            self.count+=1
            if self.WallTime()-self.last>=0.5:
                self.last=self.WallTime()
                progress(**info,candidates=self.count)
    updates=Updates()
    status=solver.solve(model,updates)
    progress(**info,candidates=updates.count,search_status=solver.status_name(status))
    return status


def generate(plan, slots, external, members, custom, seed, progress=None):
    rng=random.Random(seed)
    slots=[dict(s) for s in slots]
    members=[m for m in members if not m['archived'] or any(s.get('member_id')==m['id'] and s.get('locked') for s in slots)]
    if not members: raise ValueError('当直対象のメンバーを登録してください。')
    reports=[]
    months=sorted(set(d.strftime('%Y-%m') for d in dates(plan['start'],plan['end'])))
    for month in months:
        def update(**info):
            if progress: progress(month=month,completed_months=len(reports),total_months=len(months),**info)
        if progress: update(stage='勤務条件と固定枠を確認中')
        group=[s for s in slots if s['date'].startswith(month)]
        exact_ids={m['id'] for m in exact_month_members(plan,members,month)}
        # Later unlocked assignments will be regenerated; earlier solved months and all locks are fixed context.
        context=external+[s for s in slots if not s['date'].startswith(month) and (s['date'][:7]<month or s.get('locked')) and s.get('member_id')]
        for m in members:
            if m['id'] not in exact_ids: continue
            possible_dates={s['date'] for s in group
                            if (s['enabled'] or (s['origin']=='auto' and s['kind']=='night' and s['number']==1 and not s.get('locked') and not holiday(date.fromisoformat(s['date']),custom)))
                            and not reasons(m,s,custom)
                            and not (s.get('locked') and s.get('member_id') not in (None,m['id']))
                            and not any(t.get('member_id')==m['id'] and shifts_conflict(t,s) for t in context)}
            if len(possible_dates)<4:
                raise ValueError(f"{month} {m['name']}：2年目の月4回ちょうどを満たせません。対象期間・研修条件・有効な枠・固定勤務を考慮すると勤務可能日は{len(possible_dates)}日です。")
        model=cp_model.CpModel(); x={}; used={}; enabled={}; soft=[]; missing=[]; missing_holiday=[]; total_fair=[]; category_fair=[]
        for s in group:
            d=date.fromisoformat(s['date']); sid=s['id']
            y=model.new_bool_var(f'on_{sid}'); enabled[sid]=y
            variable=d>=YEAR2 and s['origin']=='auto' and s['kind']=='night' and s['number']==1 and not holiday(d,custom) and not s.get('locked')
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
        # Expose the required capacity directly so insufficient weekly budgets
        # are detected before searching individual member assignments.
        if exact_ids: model.add(sum(enabled.values())>=4*len(exact_ids))
        # Only this plan participates. Cap automatic weekdays at three per week,
        # counting weekday holidays; explicit extra slots and locks are retained.
        weeks={}
        for s in group:
            d=date.fromisoformat(s['date'])
            if d.weekday()<5 and s['kind']=='night' and s['number']==1:
                monday=d-timedelta(days=d.weekday()); weeks.setdefault(monday,[]).append(s)
        for monday,week in weeks.items():
            # First-year enabled slots are fixed too: preserve them even when
            # added slots/holidays exceed the automatic three-day baseline.
            # Reserve room for forced future days when a week crosses a month.
            outside_dates={t['date'] for t in slots if t['date'][:7]<month and t['kind']=='night' and t['number']==1 and t['enabled'] and monday<=date.fromisoformat(t['date'])<=monday+timedelta(days=4)}
            future_slots=[t for t in slots if t['date'][:7]>month and t['kind']=='night' and t['number']==1 and monday<=date.fromisoformat(t['date'])<=monday+timedelta(days=4)]
            def forced(t):
                return t['enabled'] and (date.fromisoformat(t['date'])<YEAR2 or t['origin']=='manual' or t.get('locked') or holiday(date.fromisoformat(t['date']),custom) or any(u['date']==t['date'] and u['kind']=='night' and u['number']==2 and u['enabled'] for u in slots))
            limit=max(0,sum(bool(forced(s)) for s in week),3-len(outside_dates)-sum(bool(forced(s)) for s in future_slots))
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
            if month >= YEAR2.strftime('%Y-%m'): model.add(count<=4)
            if mid in exact_ids:
                model.add(count==4)
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
        cumulative_fair=[]; cumulative_total_fair=[]
        for cat in (None,'weekday_night','holiday_day','holiday_night'):
            subset=[s for s in group if cat is None or category(s,custom)==cat]
            counts={m['id']:sum(x[s['id'],m['id']] for s in subset) for m in members}
            total_count=sum(counts.values())
            for mid,days in weights.items():
                if not days: continue
                dev=model.new_int_var(0,max(1,2*len(group)*total_weight),'fair')
                model.add_abs_equality(dev,counts[mid]*total_weight-total_count*days)
                (total_fair if cat is None else category_fair).append(dev)
        # Carry total and category history forward instead of resetting each month.
        # Use elapsed eligibility, so future retirement never front-loads duties.
        elapsed={m['id']:sum(eligible(m,d) for d in dates(plan['start'],active_end)) for m in members}
        divisor=gcd(*elapsed.values()) or 1
        weights={mid:days//divisor for mid,days in elapsed.items()}
        total_weight=sum(weights.values())
        past=[s for s in slots if s['date'][:7]<month and s['enabled'] and s.get('member_id')]
        for cat in (None,'weekday_night','holiday_day','holiday_night'):
            counts={m['id']:sum(x[s['id'],m['id']] for s in group if cat is None or category(s,custom)==cat)
                    +sum(s['member_id']==m['id'] and (cat is None or category(s,custom)==cat) for s in past) for m in members}
            total_count=sum(counts.values())
            for mid,days in weights.items():
                if not days: continue
                dev=model.new_int_var(0,max(1,2*len(slots)*total_weight),'cumulative_fair')
                model.add_abs_equality(dev,counts[mid]*total_weight-total_count*days)
                (cumulative_total_fair if cat is None else cumulative_fair).append(dev)
        solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=3; solver.parameters.num_search_workers=4; solver.parameters.random_seed=seed
        # Fill holidays first, then all enabled slots, before optimizing distribution.
        for label,objective in (('休日枠を充足中',sum(missing_holiday)),('有効枠を充足中',sum(missing))):
            model.minimize(objective); status=solve_with_progress(solver,model,update if progress else None,stage=label)
            if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                if status==cp_model.INFEASIBLE and exact_ids:
                    raise ValueError(f'{month}：2年目の対象者全員を月4回ちょうどに配置できません。必要回数は{len(exact_ids)*4}回です。週3日までの自動枠・手動指定枠の数、当直対象期間、研修条件、当直翌日の勤務禁止、固定勤務を確認してください。必要に応じて追加枠を指定してください。')
                raise ValueError(f'{month}：有効な枠または固定勤務が配置条件と矛盾しています。枠の設定・研修条件・当直翌日の勤務禁止・固定勤務を確認してください。' if status==cp_model.INFEASIBLE else f'{month}：時間内に配置案が見つかりませんでした。再実行してください。')
            model.add(objective<=int(solver.value(objective)))
        def capture():
            saved={s['id']:(int(solver.value(enabled[s['id']])),next((m['id'] for m in members if solver.value(x[s['id'],m['id']])),None)) for s in group}
            model.clear_hints()
            for v in [*x.values(),*enabled.values()]: model.add_hint(v,solver.value(v))
            return saved
        fallback=capture()
        # Prioritize cumulative totals, then monthly totals and categories; then
        # improve spacing and rotation preferences without undoing those gains.
        solver.parameters.max_time_in_seconds=4
        for label,objective in (('全期間の合計回数を調整中',sum(cumulative_total_fair)),('月内の合計回数を調整中',sum(total_fair)),('全期間の勤務種別を調整中',sum(cumulative_fair)),('月内の勤務種別を調整中',sum(category_fair))):
            model.minimize(objective); status=solve_with_progress(solver,model,update if progress else None,stage=label)
            if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                model.add(objective<=int(solver.value(objective)))
                fallback=capture()
        model.minimize(sum(soft)); solver.parameters.max_time_in_seconds=7; status=solve_with_progress(solver,model,update if progress else None,stage='勤務間隔と研修の希望条件を調整中')
        solved=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
        for s in group:
            on,mid=(int(solver.value(enabled[s['id']])),next((m['id'] for m in members if solver.value(x[s['id'],m['id']])),None)) if solved else fallback[s['id']]
            s.update(enabled=on,member_id=mid)
            if not s.get('locked'): s['source']='auto'
        reports.append({'month':month,'status':solver.status_name(status),'unfilled':sum(s['enabled'] and not s.get('member_id') for s in group)})
        if progress: progress(stage='月の配置完了',month=month,completed_months=len(reports),total_months=len(months))
    if progress: progress(stage='全期間の公平性を検証中',month=None,completed_months=len(months),total_months=len(months))
    slots=enforce_plan_fairness(plan,slots,external,members,custom,seed,progress=progress)
    return slots,reports


def fairness_bounds(plan, slots, members):
    """Integer quotas around each member's eligibility-weighted whole-plan share."""
    total=sum(bool(s['enabled'] and s.get('member_id')) for s in slots)
    days={m['id']:sum(eligible(m,d) for d in dates(plan['start'],plan['end'])) for m in members}
    denominator=sum(days.values())
    if not denominator: return {mid:(0,0) for mid in days}
    return {mid:(total*n//denominator,(total*n+denominator-1)//denominator) for mid,n in days.items()}


def enforce_plan_fairness(plan, slots, external, members, custom, seed, progress=None):
    """Repair all months jointly with hard quotas; never return an unverified fallback.

    Keep the selected slots and coverage unchanged. Only unlocked assignees may move.
    Monthly optimization alone can stop at FEASIBLE or freeze an unfortunate earlier
    month, so its objective value is not a whole-plan fairness guarantee.
    """
    bounds=fairness_bounds(plan,slots,members)
    filled=[s for s in slots if s['enabled'] and s.get('member_id')]
    def balanced(result):
        return all(lo<=sum(s['enabled'] and s.get('member_id')==mid for s in result)<=hi
                   for mid,(lo,hi) in bounds.items())
    if balanced(slots): return slots
    model=cp_model.CpModel(); variables={}; changes=[]
    for s in filled:
        candidates=[]
        for m in members:
            mid=m['id']
            if (m['archived'] and not (s.get('locked') and s['member_id']==mid)) or reasons(m,s,custom): continue
            if s.get('locked') and s['member_id']!=mid: continue
            if any(t.get('member_id')==mid and shifts_conflict(s,t) for t in external): continue
            v=model.new_bool_var(f"repair_{s['id']}_{mid}")
            variables[s['id'],mid]=v; candidates.append(v)
            model.add_hint(v,int(s['member_id']==mid))
            if s['member_id']!=mid: changes.append(v)
        model.add(sum(candidates)==1)
    months=sorted({s['date'][:7] for s in slots})
    exact={month:{m['id'] for m in exact_month_members(plan,members,month)} for month in months}
    ordered=sorted(filled,key=lambda s:s['date'])
    for m in members:
        mid=m['id']; lo,hi=bounds[mid]
        count=sum(v for (sid,member_id),v in variables.items() if member_id==mid)
        model.add(count>=lo); model.add(count<=hi)
        for month in months:
            count=sum(variables.get((s['id'],mid),0) for s in filled if s['date'].startswith(month))
            if month>=YEAR2.strftime('%Y-%m'): model.add(count<=4)
            if mid in exact[month]: model.add(count==4)
        for i,a in enumerate(ordered):
            for b in ordered[i+1:]:
                if (date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days>1: break
                if shifts_conflict(a,b):
                    model.add(variables.get((a['id'],mid),0)+variables.get((b['id'],mid),0)<=1)
    # Preserve as much of the category/spacing optimization as possible while
    # satisfying the strict total quotas. A feasible solution already guarantees them.
    model.minimize(sum(changes))
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    solver.parameters.num_search_workers=4
    solver.parameters.random_seed=seed
    status=solve_with_progress(solver,model,progress,stage='全月をまとめて回数差を調整中',month=None)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        detail=('現在の配置枠・固定勤務・研修条件では全期間の公平な回数配分を満たせません。'
                if status==cp_model.INFEASIBLE else '時間内に全期間の公平な回数配分を確認できませんでした。')
        raise ValueError(detail+'対象日数が同じメンバーの合計差は1回以内を必須としています。偏りのある案は保存していません。固定勤務や条件を確認してください。')
    result=[dict(s) for s in slots]
    filled_ids={s['id'] for s in filled}
    for s in result:
        if s['id'] in filled_ids:
            s['member_id']=next(m['id'] for m in members if (s['id'],m['id']) in variables
                                and solver.value(variables[s['id'],m['id']]))
    if not balanced(result) or validate(result+external,members,custom):
        raise ValueError('全期間の公平性または勤務条件の検証に失敗しました。変更は保存していません。')
    return result
