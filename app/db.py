import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get('DUTY_DB', 'data/duty.sqlite3'))

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS members (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eligibility (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), start TEXT NOT NULL, end TEXT NOT NULL, CHECK(start<=end)
);
CREATE TABLE IF NOT EXISTS rotations (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), kind TEXT NOT NULL, hospital TEXT NOT NULL DEFAULT '',
 start TEXT NOT NULL, end TEXT NOT NULL, CHECK(start<=end)
);
CREATE TABLE IF NOT EXISTS training_events (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), date TEXT NOT NULL, kind TEXT NOT NULL,
 UNIQUE(member_id,date,kind)
);
CREATE TABLE IF NOT EXISTS holidays (date TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(start<=end)
);
CREATE TABLE IF NOT EXISTS slots (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id), date TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('day','night')), number INTEGER NOT NULL CHECK(number IN (1,2)),
 enabled INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT 'auto',
 UNIQUE(plan_id,date,kind,number)
);
CREATE TABLE IF NOT EXISTS assignments (
 slot_id INTEGER PRIMARY KEY REFERENCES slots(id), member_id INTEGER NOT NULL REFERENCES members(id),
 locked INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id), action TEXT NOT NULL,
 snapshot TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS generation_runs (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id), seed INTEGER NOT NULL,
 result TEXT NOT NULL, inputs TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS slots_date ON slots(date);
CREATE INDEX IF NOT EXISTS assignments_member ON assignments(member_id);
'''

def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)
        # Upgrade legacy placements without changing their scheduling meaning.
        db.execute("UPDATE rotations SET kind='community', hospital='remote' WHERE kind='remote'")
        db.execute("UPDATE rotations SET hospital='takatsuki_nearby' WHERE kind='community' AND hospital=''")

@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def all_members(db):
    result = [dict(r) for r in db.execute('SELECT * FROM members ORDER BY id')]
    for m in result:
        for key, table in [('periods','eligibility'),('rotations','rotations'),('events','training_events')]:
            m[key] = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE member_id=? ORDER BY id', (m['id'],))]
    return result

def all_slots(db, plan_id=None):
    query = '''SELECT s.*, a.member_id, COALESCE(a.locked,0) AS locked, a.source FROM slots s
               LEFT JOIN assignments a ON a.slot_id=s.id'''
    if plan_id is not None:
        query += ' WHERE s.plan_id=?'
    return [dict(r) for r in db.execute(query + ' ORDER BY s.date,s.kind,s.number', () if plan_id is None else (plan_id,))]
