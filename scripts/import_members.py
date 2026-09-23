"""Preview/apply a private member JSON file to an existing, stopped server DB."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import Member, check_all
from fastapi import HTTPException


def normalized(name):
    return ''.join(name.split())


def load_records(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    records = raw['members']
    if not records:
        raise ValueError('取込データが空です')
    result = []
    names = set()
    for record in records:
        member = Member.model_validate(record)
        key = normalized(member.name)
        if key in names:
            raise ValueError(f'取込データ内の氏名が重複しています: {member.name}')
        names.add(key)
        for period in member.rotations:
            if not any(p.start <= period.start <= period.end <= p.end for p in member.periods):
                raise ValueError(f'{member.name}: 研修期間が当直対象期間外です')
        for event in member.events:
            if not any(p.start <= event.date <= p.end for p in member.periods):
                raise ValueError(f'{member.name}: 研修日が当直対象期間外です')
        result.append((record, member))
    return result


def resolve(conn, records):
    existing = [dict(row) for row in conn.execute('SELECT * FROM members')]
    resolved = []
    used = set()
    for raw, member in records:
        if 'member_id' in raw:
            matches = [m for m in existing if m['id'] == raw['member_id']]
            if not matches:
                raise ValueError(f'{member.name}: 指定IDが存在しません')
        else:
            matches = [m for m in existing if normalized(m['name']) == normalized(member.name)]
            if raw.get('surname_only'):
                matches = [m for m in existing if normalized(m['name']).startswith(normalized(member.name))]
        if len(matches) > 1:
            raise ValueError(f'{member.name}: 候補が複数あります。JSONにmember_idを指定してください')
        old = matches[0] if matches else None
        if old and old['id'] in used:
            raise ValueError('複数の取込レコードが同じ既存メンバーに一致しました')
        if old:
            used.add(old['id'])
        resolved.append((old, member))
    return resolved


def write_records(conn, resolved):
    for old, member in resolved:
        if old:
            # Preserve existing full name, color and archived state.
            mid = old['id']
        else:
            mid = conn.execute('INSERT INTO members(name,color,archived) VALUES(?,?,?)',
                               (member.name, member.color, member.archived)).lastrowid
        for table in ('eligibility', 'rotations', 'training_events'):
            conn.execute(f'DELETE FROM {table} WHERE member_id=?', (mid,))
        for p in member.periods:
            conn.execute('INSERT INTO eligibility(member_id,start,end) VALUES(?,?,?)',
                         (mid, p.start.isoformat(), p.end.isoformat()))
        for r in member.rotations:
            conn.execute('INSERT INTO rotations(member_id,kind,hospital,start,end) VALUES(?,?,?,?,?)',
                         (mid, r.kind, r.hospital, r.start.isoformat(), r.end.isoformat()))
        for e in member.events:
            conn.execute('INSERT OR IGNORE INTO training_events(member_id,date,kind) VALUES(?,?,?)',
                         (mid, e.date.isoformat(), e.kind))
    check_all(conn)
    conn.execute('UPDATE plans SET version=version+1')


def run(input_path, db_path, apply=False):
    records = load_records(input_path)
    target = Path(db_path).resolve()
    if not target.is_file():
        raise ValueError(f'DBがありません。対象アプリを一度起動して停止してください: {target}')
    conn = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    backup = None
    try:
        conn.execute('BEGIN IMMEDIATE')
        resolved = resolve(conn, records)
        print(f'対象DB: {target}')
        for old, member in resolved:
            label = f'更新 ID={old["id"]} {old["name"]}' if old else f'新規 {member.name}'
            print(f'{label}: ' + ', '.join(f'{p.start}〜{p.end}' for p in member.periods)
                  + f' / 研修{len(member.rotations)}件 / 研修日{len(member.events)}件')
            if old and old['archived']:
                print('  注意: 既存の非表示状態を維持します')
        if apply:
            backup_dir = target.parent / 'backups'
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / f'{target.name}.{datetime.now():%Y%m%d-%H%M%S-%f}.backup'
            # A separate read connection can snapshot while the writer holds RESERVED.
            with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as source:
                with sqlite3.connect(backup) as dest:
                    source.backup(dest)
            print(f'変更前バックアップ: {backup}')
        write_records(conn, resolved)
        if apply:
            conn.commit()
            print(f'登録完了: {len(resolved)}名')
        else:
            conn.rollback()
            print('確認完了。DBは変更していません。登録には --apply を指定してください。')
        return backup
    finally:
        conn.rollback()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='非公開のメンバーJSONファイル')
    parser.add_argument('--db', default=os.environ.get('DUTY_DB', 'data/duty.sqlite3'))
    parser.add_argument('--apply', action='store_true', help='バックアップ後、一括登録する')
    args = parser.parse_args()
    try:
        run(args.input, args.db, args.apply)
    except (ValueError, OSError, sqlite3.Error, HTTPException) as exc:
        print(f'登録中止（変更は保存されません）: {getattr(exc, "detail", str(exc))}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
