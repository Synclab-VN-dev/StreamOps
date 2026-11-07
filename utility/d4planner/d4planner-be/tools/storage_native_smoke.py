"""Native migration smoke using only a newly created disposable sandbox."""
from __future__ import annotations
import argparse
import csv
import subprocess
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import sys

from d4planner.runtime import migration



def secure_new_sandbox(path):
    """Provision ACL only on the fresh, empty test sandbox we just created."""
    identity = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'], text=True)
    sid = next(csv.reader(identity.splitlines()))[1]
    subprocess.run(['icacls.exe', str(path), '/inheritance:r', '/grant:r',
                    '*'+sid+':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
                   check=True, capture_output=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('isolated Windows VM required')
    args.sandbox.mkdir(parents=True, exist_ok=False)
    secure_new_sandbox(args.sandbox)
    source, target = args.sandbox / 'legacy', args.sandbox / 'canonical'
    (source / 'state').mkdir(parents=True)
    with closing(sqlite3.connect(source/'state/character.db')) as db, db:
        db.execute('CREATE TABLE equipment(revision INTEGER)')
        db.execute('INSERT INTO equipment VALUES(42)')
    (source/'state/capture.json').write_text('{"enabled":false}')
    report = {'id':'UDR-06', 'classification':'WINDOWS_NATIVE_ISOLATED_FIXTURE', 'status':'RUNNING'}
    try:
        plan = migration.plan(source, target)
        (args.sandbox/'plan.json').write_text(json.dumps(plan, indent=2))
        assert not target.exists(), 'dry-run mutated destination'
        applied = migration.apply(json.loads(json.dumps(plan)))
        migration.verify(applied)
        report['manifest'] = json.loads(json.dumps(applied))
        report['repeat'] = migration.plan(source, target)
        assert all(f['action'] == 'SKIP_IDENTICAL' for f in report['repeat']['files'])
        migration.rollback(applied)
        assert not (target/'state/character.db').exists()
        assert migration.database_check(source/'state/character.db')['rowCounts'] == {'equipment':1}
        report['phases'] = ['PREFLIGHT_PASS','APPLY_VERIFIED','VERIFY_PASS','IDEMPOTENT_PLAN_PASS','ROLLBACK_PASS']
        report['sourceAfterRollback'] = {p.relative_to(source).as_posix():migration.sha(p) for p in source.rglob('*') if p.is_file()}
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=repr(error))
    (args.sandbox/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
