"""Private provider capture history and UI selection; never calculation compatibility."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    stat = path.lstat()
    if path.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError('Private directory must be owned by current user, mode 0700: ' + str(path))
    return path


def atomic(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextlib.contextmanager
def locked(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


class State:
    def __init__(self, root):
        self.root = private_dir(root)
        self.file = self.root / 'capture-state.json'

    def read(self):
        if not self.file.exists():
            return {'schemaVersion': 'maxroll-capture-state/v1', 'revision': 0,
                    'runs': {}, 'packages': {}, 'activeUi': None, 'previousActiveUi': None,
                    'history': [], 'transition': None}
        if self.file.is_symlink():
            raise ValueError('CAPTURE_STATE_CORRUPT: symlink')
        envelope = json.loads(self.file.read_text())
        data = envelope['payload']
        if (hashlib.sha256(canonical(data)).hexdigest() != envelope['sha256'] or
                data['schemaVersion'] != 'maxroll-capture-state/v1' or
                type(data['revision']) is not int or data['revision'] < 1):
            raise ValueError('CAPTURE_STATE_CORRUPT')
        for field in ('activeUi', 'previousActiveUi'):
            if data[field] and (data[field] not in data['packages'] or
                               data['packages'][data[field]]['kind'] != 'ui' or
                               data['packages'][data[field]]['validationStatus'] != 'VALIDATED'):
                raise ValueError('CAPTURE_STATE_CORRUPT: selection')
        return data

    def transact(self, fn):
        with locked(self.root / 'capture-state.lock'):
            data = self.read()
            fn(data)
            data['revision'] += 1
            atomic(self.file, {'payload': data, 'sha256': hashlib.sha256(canonical(data)).hexdigest()})
            return data

    def command(self, command):
        op = command['operation']
        if op == 'read':
            with locked(self.root / 'capture-state.lock'):
                return self.read()

        def change(data):
            if op == 'begin':
                run = command['run']
                if run['id'] in data['runs']:
                    raise ValueError('Capture run already exists')
                data['runs'][run['id']] = run
                for package in command['packages']:
                    key = package['snapshotId']
                    if key in data['packages']:
                        raise ValueError('Snapshot already registered')
                    data['packages'][key] = package
            elif op == 'package':
                package = data['packages'][command['snapshotId']]
                patch = command['patch']
                allowed = {'validationStatus', 'identity', 'manifestSha256', 'coverageSha256',
                           'validationSha256', 'config', 'error', 'compatibility', 'finishedAt', 'capturedAt'}
                if set(patch) - allowed or package['snapshotId'] in (data['activeUi'], data['previousActiveUi']):
                    raise ValueError('Immutable active identity / unsupported metadata field')
                if patch.get('validationStatus') not in (None, 'CAPTURED_UNVALIDATED', 'VALIDATING', 'VALIDATED', 'UNSUPPORTED_VERSION', 'FAILED'):
                    raise ValueError('Invalid capture validation status')
                if package['kind'] == 'calculation' and patch.get('validationStatus') == 'VALIDATED':
                    raise ValueError('Calculation capture cannot grant compatibility')
                package.update(patch)
            elif op == 'finish':
                data['runs'][command['runId']].update(command['result'])
            elif op == 'adopt':
                if data['activeUi'] or data['transition']:
                    raise ValueError('Selection already exists')
                package = command['package']
                if package['kind'] != 'ui' or package['validationStatus'] != 'VALIDATED':
                    raise ValueError('Only validated UI may be adopted')
                data['packages'].setdefault(package['snapshotId'], package)
                data['activeUi'] = package['snapshotId']
                data['history'].append({'operation': 'ADOPT', 'snapshotId': package['snapshotId']})
            elif op == 'prepare':
                if data['transition'] or data['activeUi'] != command['oldId']:
                    raise ValueError('Selection changed / transition pending')
                target = data['packages'][command['targetId']]
                run = data['runs'].get(target['runId'])
                if (target['kind'] != 'ui' or target['validationStatus'] != 'VALIDATED' or
                        (run and run.get('status') != 'COMPLETE')):
                    raise ValueError('Candidate is not eligible')
                data['transition'] = {k: command[k] for k in ('oldId', 'targetId', 'action')}
            elif op == 'commit':
                transition = data['transition']
                if transition != command['transition']:
                    raise ValueError('Transition changed')
                old, target = transition['oldId'], transition['targetId']
                if old != target:
                    data['previousActiveUi'], data['activeUi'] = old, target
                    if old and transition['action'] == 'rollback':
                        data['packages'][old]['activationRejected'] = True
                data['packages'][target].pop('activationRejected', None)
                data['history'].append({**transition, 'operation': 'COMMIT'})
                data['transition'] = None
            elif op == 'abort':
                transition = data['transition']
                if transition:
                    # With no previous service there is nothing to fall back to. A later
                    # explicit start may retry all verification/probe gates for this candidate.
                    data['packages'][transition['targetId']]['activationRejected'] = bool(transition['oldId'])
                    data['history'].append({**transition, 'operation': 'ROLLBACK_AFTER_FAILURE'})
                data['transition'] = None
            else:
                raise ValueError('Unsupported capture state operation')
        return self.transact(change)


def eligible(data):
    active = data['packages'].get(data['activeUi'])
    candidates = [p for p in data['packages'].values() if p['kind'] == 'ui' and
                  p['validationStatus'] == 'VALIDATED' and not p.get('activationRejected') and
                  data['runs'].get(p['runId'], {}).get('status') == 'COMPLETE' and
                  (not active or p['capturedAt'] > active['capturedAt'])]
    return max(candidates, key=lambda p: (p['capturedAt'], p['snapshotId'])) if candidates else active


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(State(sys.argv[1]).command(json.load(sys.stdin))))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('CAPTURE_STATE_ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
