import json
import sqlite3

import pytest
from fastapi import HTTPException
from app.db import SCHEMA
from scripts.import_members import run


def prepare(tmp_path, records):
    db = tmp_path / 'test.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
    source = tmp_path / 'members.json'
    source.write_text(json.dumps({'members': records}), encoding='utf-8')
    return source, db


def record(name='Test'):
    return {'name': name, 'periods': [{'start': '2026-04-01', 'end': '2027-03-28'}],
            'rotations': [{'kind': 'anesthesia', 'start': '2026-10-12', 'end': '2026-12-06'}]}


def test_preview_apply_repeat_and_backup(tmp_path):
    source, db = prepare(tmp_path, [record()])
    before = db.read_bytes()
    run(source, db)
    assert db.read_bytes() == before
    backup = run(source, db, apply=True)
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT COUNT(*) FROM members').fetchone()[0] == 0
    run(source, db, apply=True)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM members').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM rotations').fetchone()[0] == 1


def test_unique_surname_preserves_identity_and_unrelated_members(tmp_path):
    entry = record('Example'); entry['surname_only'] = True
    source, db = prepare(tmp_path, [entry])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO members VALUES(1,'Example Person','#ffffff',1)")
        conn.execute("INSERT INTO members VALUES(2,'Other Person','#ffffff',0)")
    run(source, db, apply=True)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT name,archived FROM members WHERE id=1').fetchone() == ('Example Person', 1)
        assert conn.execute('SELECT COUNT(*) FROM members').fetchone()[0] == 2


def test_ambiguous_surname_does_not_write(tmp_path):
    entry = record('Example'); entry['surname_only'] = True
    source, db = prepare(tmp_path, [entry])
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO members(name,color) VALUES(?,?)', [('Example One','#ffffff'), ('Example Two','#ffffff')])
    before = db.read_bytes()
    with pytest.raises(ValueError, match='候補が複数'):
        run(source, db, apply=True)
    assert db.read_bytes() == before


def test_conflicting_assignment_rolls_back_entire_batch(tmp_path):
    source, db = prepare(tmp_path, [record('New'), record('Existing')])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO members VALUES(1,'Existing','#ffffff',0)")
        conn.execute("INSERT INTO eligibility(member_id,start,end) VALUES(1,'2026-04-01','2028-03-28')")
        conn.execute("INSERT INTO plans(id,name,start,end) VALUES(1,'Plan','2027-04-01','2027-04-30')")
        conn.execute("INSERT INTO slots(id,plan_id,date,kind,number,enabled) VALUES(1,1,'2027-04-03','day',1,1)")
        conn.execute('INSERT INTO assignments(slot_id,member_id) VALUES(1,1)')
    with pytest.raises(HTTPException):
        run(source, db, apply=True)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM members').fetchone()[0] == 1
        assert conn.execute('SELECT end FROM eligibility WHERE member_id=1').fetchone()[0] == '2028-03-28'
        assert conn.execute('SELECT version FROM plans').fetchone()[0] == 1
