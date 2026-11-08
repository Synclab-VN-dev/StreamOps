"""Short-lived native-owned HTTP gateway. GitHub PAT stays in the backend only."""
from __future__ import annotations

import argparse
import hmac
import json
import secrets
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server, WSGIRequestHandler

from .gateway import Application, GitHub, Service, Rejected, REPO, TAG, MAX_BYTES, validate_release


def load_config(root: Path) -> dict:
    from ..runtime.storage import canonical, check_owner
    path = root / 'private' / 'report-config.json'
    try:
        canonical(path.parent)
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError()
        if not path.is_file():
            raise Rejected('REPORT_NOT_CONFIGURED', 400)
        check_owner(path)
        with path.open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'githubToken', 'recipient', 'maxBytes'}:
            raise ValueError()
        token = value['githubToken']
        if not isinstance(token, str) or not token or len(token) > 4096 or any(c.isspace() or ord(c) < 32 for c in token):
            raise ValueError()
        if not isinstance(value['recipient'], str) or not value['recipient'].startswith('age1') or len(value['recipient']) > 128:
            raise ValueError()
        if type(value['maxBytes']) is not int or not 0 < value['maxBytes'] <= MAX_BYTES:
            raise ValueError()
        return value
    except Rejected:
        raise
    except (OSError, ValueError, TypeError):
        raise Rejected('INVALID_REPORT_CONFIG', 400) from None


class QuietHandler(WSGIRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # no credentials, user form or report IDs in access logs


class LocalGateway:
    def __init__(self, service, subject):
        self.credential = secrets.token_urlsafe(32)
        def authenticate(header):
            if not hmac.compare_digest(header, 'Bearer ' + self.credential):
                raise Rejected('UNAUTHENTICATED', 401)
            return subject
        app = Application(service, authenticate)
        def guarded(environ, start_response):
            if environ.get('HTTP_ORIGIN') or environ.get('HTTP_HOST') != self.authority:
                start_response('403 Forbidden', [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])
                return [b'{"error":"LOCAL_ORIGIN_REJECTED"}']
            return app(environ, start_response)
        self.server = make_server('127.0.0.1', 0, guarded, handler_class=QuietHandler)
        self.authority = f'127.0.0.1:{self.server.server_port}'
        self.endpoint = 'http://' + self.authority
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=35)


def provision(root, config, github=None):
    github = github or GitHub(lambda: config['githubToken'])
    actor = github.request('GET', '/user')
    if type(actor.get('id')) is not int or actor['id'] <= 0:
        raise Rejected('GITHUB_IDENTITY_INVALID')
    try:
        release = github.request('GET', f'/repos/{REPO}/releases/tags/{TAG}')
    except Rejected as exc:
        if exc.code == 'GITHUB_404':
            raise Rejected('DIAGNOSTIC_RELEASE_NOT_CONFIGURED') from None
        raise
    rid = release.get('id')
    if type(rid) is not int or rid <= 0:
        raise Rejected('RELEASE_IDENTITY_OR_IMMUTABILITY_BLOCKED')
    validate_release(release, rid)
    # One shared ledger preserves report-ID ownership when the configured PAT account changes.
    from ..runtime.storage import canonical, check_owner
    private = canonical(root / 'private')
    check_owner(private)
    database = private / 'report-gateway.sqlite3'
    for suffix in ('', '-journal', '-wal', '-shm'):
        candidate = Path(str(database) + suffix)
        if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
            raise Rejected('INVALID_REPORT_STATE')
        if candidate.exists():
            check_owner(candidate)
    service = Service(database,
                      github, rid, actor['id'], config['maxBytes'])
    return LocalGateway(service, f'github-user:{actor["id"]}')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', required=True, type=Path)
    args = parser.parse_args(argv)
    server = None
    try:
        config = load_config(args.data_root)
        # Let native validate the age recipient before any GitHub request.
        print(json.dumps({'recipient': config['recipient'], 'maxBytes': config['maxBytes']}), flush=True)
        if sys.stdin.readline(32) != 'START\n':
            return 0
        server = provision(args.data_root, config)
        server.start()
        print(json.dumps({'gateway': server.endpoint, 'accessToken': server.credential}), flush=True)
        # Only the native owner holds this pipe; EOF means owner exited/crashed.
        sys.stdin.read()
        return 0
    except Rejected as exc:
        print(json.dumps({'error': exc.code}), flush=True)
        return 2
    except Exception:
        print(json.dumps({'error': 'LOCAL_GATEWAY_FAILED'}), flush=True)
        return 2
    finally:
        if server:
            server.close()


if __name__ == '__main__':
    raise SystemExit(main())
