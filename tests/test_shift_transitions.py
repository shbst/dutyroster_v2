import pytest
from app.rules import validate, shifts_conflict
from app.solver import generate
from test_app import client, member, plan, edit


PAIRS = [('day', 'day', True), ('day', 'night', True),
         ('night', 'day', False), ('night', 'night', False)]


def person():
    return dict(id=1, name='Test', archived=False, color='#ffffff',
                periods=[dict(start='2026-04-01', end='2028-03-28')], rotations=[], events=[])


def slot(sid, ds, kind, locked=True):
    return dict(id=sid, date=ds, kind=kind, number=1, enabled=1,
                origin='manual', member_id=1 if locked else None, locked=locked)


@pytest.mark.parametrize('first,second,allowed', PAIRS)
@pytest.mark.parametrize('days', [('2026-10-17', '2026-10-18'), ('2027-07-31', '2027-08-01')])
def test_manual_edit_transitions(client, first, second, allowed, days):
    mid=member(client)
    p=plan(client, *days)
    for index, (ds, kind) in enumerate(zip(days, (first, second))):
        s=next(s for s in p['slots'] if s['date']==ds and s['kind']==kind and s['number']==1)
        response=edit(client, p, s['id'], member_id=mid)
        assert response.status_code == (200 if index==0 or allowed else 422), response.text
        if response.status_code==200:
            p=response.json()


@pytest.mark.parametrize('first,second,allowed', PAIRS)
@pytest.mark.parametrize('days', [('2026-10-17', '2026-10-18'), ('2027-07-31', '2027-08-01')])
@pytest.mark.parametrize('locked', [True, False])
def test_solver_transitions(first, second, allowed, days, locked):
    # With an unlocked second slot, the only candidate must be used iff allowed.
    slots=[slot(1, days[0], first), slot(2, days[1], second, locked)]
    p=dict(start=days[0], end=days[1])
    if locked and not allowed:
        with pytest.raises(ValueError, match='矛盾'):
            generate(p, slots, [], [person()], {}, 42)
    else:
        result, _ = generate(p, slots, [], [person()], {}, 42)
        assert result[0]['member_id']==1
        assert result[1]['member_id']==(1 if allowed else None)
        assert not validate(result, [person()], {})


@pytest.mark.parametrize('first,second', [('day','day'), ('day','night'), ('night','night')])
def test_same_day_remains_forbidden(first, second):
    a=slot(1, '2026-10-17', first)
    b=slot(2, '2026-10-17', second)
    assert shifts_conflict(a,b)
    assert validate([a,b], [person()], {})
