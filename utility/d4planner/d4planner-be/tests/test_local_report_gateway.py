import json
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest

from d4planner.reporting.local import load_config, LocalGateway
from d4planner.reporting.gateway import Rejected


def config(root):
    private = root / 'private'
    private.mkdir()
    (private / 'report-config.json').write_text(json.dumps({
        'githubToken': 'synthetic-github-secret',
        'recipient': 'age1synthetic', 'maxBytes': 10000000,
    }))


def test_missing_and_invalid_config_are_actionable_and_sanitized(tmp_path):
    with pytest.raises(Rejected, match='REPORT_NOT_CONFIGURED'):
        load_config(tmp_path)
    config(tmp_path)
    assert load_config(tmp_path)['githubToken'] == 'synthetic-github-secret'
    path = tmp_path / 'private/report-config.json'
    path.write_text('{"githubToken":"never-echo-this", "gateway":"http://evil"}')
    with pytest.raises(Rejected, match='INVALID_REPORT_CONFIG') as error:
        load_config(tmp_path)
    assert 'never-echo-this' not in str(error.value)


def test_config_symlink_and_size_are_rejected(tmp_path):
    config(tmp_path)
    path = tmp_path / 'private/report-config.json'
    path.write_text('x' * 8193)
    with pytest.raises(Rejected, match='INVALID_REPORT_CONFIG'):
        load_config(tmp_path)
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(Rejected, match='INVALID_REPORT_CONFIG'):
        load_config(tmp_path)


class Service:
    max_bytes = 10000
    def authorize_request(self, subject):
        assert subject == 'github-user:42'
    def prepare(self, subject, rid, data):
        return {'reportId': rid, 'status': 'PREPARED'}


def test_loopback_requires_native_secret_rejects_browser_origin_and_closes():
    server = LocalGateway(Service(), 'github-user:42')
    server.start()
    url = server.endpoint + '/reports/00000000-0000-4000-8000-000000000001'
    def send(headers):
        req = urllib.request.Request(url, b'{}', method='PUT', headers=headers)
        return urllib.request.urlopen(req, timeout=3)
    try:
        assert server.endpoint.startswith('http://127.0.0.1:')
        with pytest.raises(urllib.error.HTTPError) as error:
            send({})
        assert error.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as error:
            send({'Authorization': 'Bearer '+server.credential, 'Origin': 'https://evil.invalid'})
        assert error.value.code == 403
        with send({'Authorization': 'Bearer '+server.credential}) as reply:
            assert json.load(reply)['status'] == 'PREPARED'
    finally:
        server.close()
    with pytest.raises(urllib.error.URLError):
        send({'Authorization': 'Bearer '+server.credential})


def test_actual_http_report_upload_retry_and_secret_not_in_outputs(tmp_path):
    import hashlib
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report-gateway/tests'))
    from test_reports import FakeGitHub
    from d4planner.reporting.gateway import Service as RealService
    gh = FakeGitHub()
    service = RealService(tmp_path / 'reports.sqlite3', gh, 77, 42, 10000)
    server = LocalGateway(service, 'github-user:42')
    server.start()
    rid = '00000000-0000-4000-8000-000000000001'
    data = b'age-encryption.org/v1\n-> X25519 '+b'A'*43+b'\n'+b'B'*43+b'\n--- '+b'C'*43+b'\n'+b'x'*100
    body = {'description': {'issueType': 'Other', 'title': 'Fixture', 'actual': 'actual', 'expected': 'expected', 'steps': 'steps'},
            'artifact': {'reportId': rid, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
    def send(method, suffix, content):
        req = urllib.request.Request(server.endpoint+'/reports/'+rid+suffix, content,
            method=method, headers={'Authorization':'Bearer '+server.credential})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)
    try:
        assert send('PUT', '', json.dumps(body).encode())['status'] == 'PREPARED'
        first = send('POST', '/asset', data)
        assert first['status'] == 'COMPLETE'
        assert send('POST', '/asset', data) == first
        assert len(gh.items) == len(gh.uploads) == 1
        assert server.credential not in json.dumps(gh.items + gh.uploads)
    finally:
        server.close()


def test_provision_binds_token_actor_and_existing_release_only(tmp_path):
    from d4planner.reporting.local import provision
    from d4planner.reporting.gateway import TAG, NAME
    config(tmp_path)
    class GitHub:
        def __init__(self): self.calls = []
        def request(self, method, path):
            self.calls.append((method,path))
            if path == '/user': return {'id':42}
            return {'id':77, 'tag_name':TAG, 'name':NAME, 'prerelease':True, 'draft':False, 'immutable':False}
    github = GitHub()
    server = provision(tmp_path, load_config(tmp_path), github)
    server.server.server_close()
    assert all(method == 'GET' for method, _ in github.calls)
    assert (tmp_path/'private/report-gateway.sqlite3').is_file()


def test_parent_eof_and_bad_config_child_do_not_emit_pat(tmp_path):
    import subprocess
    import sys
    config(tmp_path)
    child = subprocess.Popen([sys.executable, '-m', 'd4planner.reporting.local', '--data-root', str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        public = json.loads(child.stdout.readline())
        assert set(public) == {'recipient','maxBytes'}
        child.stdin.close()  # native owner exits before any GitHub request
        assert child.wait(timeout=5) == 0
        assert 'synthetic-github-secret' not in child.stdout.read() + child.stderr.read()
    finally:
        if child.poll() is None: child.kill(); child.wait()


def test_pat_account_switch_cannot_recreate_same_report(tmp_path):
    import sys
    import hashlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report-gateway/tests'))
    from test_reports import FakeGitHub
    from d4planner.reporting.gateway import Service as RealService
    db = tmp_path / 'report-gateway.sqlite3'
    first = RealService(db, FakeGitHub(), 77, 42, 10000)
    second = RealService(db, FakeGitHub(), 77, 43, 10000)
    rid='00000000-0000-4000-8000-000000000001'
    request={'description':{'issueType':'Other','title':'fixture','actual':'a','expected':'b','steps':''},
             'artifact':{'reportId':rid,'bytes':200,'sha256':hashlib.sha256(b'fixture').hexdigest()}}
    first.prepare('github-user:42',rid,request)
    with pytest.raises(Rejected, match='IDEMPOTENCY_CONFLICT'):
        second.prepare('github-user:43',rid,request)
