"""One-command isolated local evidence; never operates on machine DataRoot."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'UDR-01': ['tests/test_unified_storage.py'],
    'UDR-02': ['tests/test_unified_storage.py', 'tests/test_controller_cli_e2e.py'],
    'UDR-03': ['tests/test_runtime_store.py', 'tests/test_event_repository.py'],
    'UDR-04': ['tests/test_runtime_logging.py'],
    'UDR-05': [],
    'UDR-06': ['tests/test_unified_storage.py'],
    'UDR-07': ['tests/test_d5_delivery.py'],
    'UDR-08': [],
    'UDR-09': ['tests/test_production_backend.py', 'tests/test_snapshot_backend.py'],
    'UDR-10': ['tests/test_storage_tools.py'],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--only', choices=list(CASES), action='append')
    parser.add_argument('--windows-vm', action='store_true', help='Run the enrolled isolated Windows VM suite')
    parser.add_argument('--setup', type=Path)
    parser.add_argument('--old-setup', type=Path)
    args = parser.parse_args(argv)
    if (args.setup or args.old_setup) and not args.windows_vm:
        parser.error('--setup/--old-setup require --windows-vm')
    args.output = args.output.absolute()
    args.output.mkdir(parents=True, exist_ok=False)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    report = {'head': head, 'dirty': bool(dirty), 'sourceChanges': dirty,
              'timestamp': datetime.now(timezone.utc).isoformat(), 'ci': 'CI_NOT_CHECKED', 'cases': []}
    for identity in args.only or CASES:
        files = CASES[identity]
        item = {'id': identity, 'expected': 'isolated local regression passes',
                'status': 'NOT_RUN', 'ticketGate': 'NOT_RUN', 'scope': 'recorded temporary fixtures only'}
        if files:
            cmd = [sys.executable, '-m', 'pytest', '-q', *files]
            with (args.output / (identity + '.log')).open('w') as log:
                result = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            item.update(command=cmd, subprocessExit=result.returncode,
                        status='PASS' if result.returncode == 0 else 'FAIL')
        else:
            item['actual'] = 'native/export/documentation gate needs dedicated evidence'
        report['cases'].append(item)
        print(identity, item['status'], flush=True)
    if args.windows_vm:
        command = [sys.executable, str(ROOT/'tools/storage_vm_acceptance.py'), '--output', str(args.output/'native')]
        if args.only:
            command += ['--suite','storage']
        if args.setup:
            command += ['--setup',str(args.setup.absolute())]
        if args.old_setup:
            command += ['--old-setup',str(args.old_setup.absolute())]
        result = subprocess.run(command, cwd=ROOT)
        native_path = args.output/'native/report.json'
        native = json.loads(native_path.read_text()) if native_path.exists() else {'status':'FAIL'}
        report['native'] = {'command':command, 'subprocessExit':result.returncode, 'report':str(native_path), **native}
        for item in report['cases']:
            item['nativeStatus'] = 'PASS' if result.returncode == 0 and native.get('status') == 'PASS' else 'FAIL'
            if item['id'] == 'UDR-05':
                item.update(status=item['nativeStatus'], actual='native Report Issue crate regression; selected-log privacy/cleanup')
            if item['id'] == 'UDR-08' and args.setup:
                item.update(status=item['nativeStatus'], actual='packaged VM lifecycle; see setup.json for exact coverage/limits')
        if result.returncode:
            report['nativeFailure'] = True
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    return 1 if report.get('nativeFailure') or any(item['status'] == 'FAIL' for item in report['cases']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
