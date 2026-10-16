import pytest
from ortools.sat.python import cp_model
from app.solver import enforce_plan_fairness, fairness_bounds
from app.rules import validate


def fixture():
    p={'start':'2026-06-01','end':'2026-07-31'}
    ms=[{'id':i,'name':str(i),'archived':False,'periods':[p.copy()],
         'rotations':[],'events':[]} for i in (1,2)]
    ss=[]
    for month in (6,7):
        for i,day in enumerate((1,5,9,13,17,21,25)):
            ss.append({'id':len(ss)+1,'date':f'2026-{month:02}-{day:02}',
                       'kind':'night','number':1,'enabled':1,'origin':'auto',
                       'member_id':1 if i<4 else 2,'locked':i==0})
    return p,ss,ms


@pytest.mark.parametrize('seed',[1,42,98765])
def test_hard_quota_repairs_eight_six_without_changing_coverage_or_locks(seed):
    p,ss,ms=fixture()
    result=enforce_plan_fairness(p,ss,[],ms,{},seed)
    assert [sum(s['member_id']==i for s in result) for i in (1,2)]==[7,7]
    assert not validate(result,ms,{})
    assert all(a['enabled']==b['enabled'] for a,b in zip(ss,result))
    assert all(a['member_id']==b['member_id'] for a,b in zip(ss,result) if a['locked'])
    assert sum(s['member_id']==1 for s in ss)==8


def test_unavoidable_fixed_imbalance_is_rejected():
    p,ss,ms=fixture()
    for s in ss: s['locked']=True
    with pytest.raises(ValueError,match='公平な回数配分を満たせません'):
        enforce_plan_fairness(p,ss,[],ms,{},42)


def test_timeout_never_returns_unbalanced_fallback(monkeypatch):
    p,ss,ms=fixture()
    monkeypatch.setattr(cp_model.CpSolver,'solve',lambda *args,**kwargs:cp_model.UNKNOWN)
    with pytest.raises(ValueError,match='公平な回数配分を確認できません'):
        enforce_plan_fairness(p,ss,[],ms,{},42)


def test_quotas_account_for_different_eligible_days():
    p,ss,ms=fixture()
    ms[1]['periods']=[{'start':'2026-06-01','end':'2026-06-30'}]
    assert fairness_bounds(p,ss,ms)=={1:(9,10),2:(4,5)}
