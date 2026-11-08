"""Test-only Python startup fixture; never packaged. No production auth bypass."""
import os

if os.environ.get('D4PLANNER_REPORT_FAKE_STATE'):
    import sys
    import json
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'report-gateway/tests'))
    from test_reports import FakeGitHub
    import d4planner.reporting.gateway as gateway
    from d4planner.reporting.gateway import REPO, TAG

    class PersistentFake(FakeGitHub):
        def __init__(self, token):
            super().__init__()
            self.state = Path(os.environ['D4PLANNER_REPORT_FAKE_STATE'])
            assert token() == 'SYNTHETIC_GITHUB_PAT_NEVER_EXPORT'
            if self.state.exists():
                saved = json.loads(self.state.read_text())
                self.items, self.uploads = saved['items'], saved['uploads']
                self.notes = {int(k):v for k,v in saved['notes'].items()}
        def save(self):
            self.state.write_text(json.dumps({'items':self.items,'uploads':self.uploads,'notes':self.notes}))
        def request(self, method, path):
            assert method == 'GET'
            if path == '/user': return {'id':42}
            assert path == f'/repos/{REPO}/releases/tags/{TAG}'
            return self.r
        def create_issue(self, title, body):
            value=super().create_issue(title,body);self.save();return value
        def upload(self, rid, name, data):
            self.state.with_suffix('.age').write_bytes(data)
            value=super().upload(rid,name,data);self.save();return value
        def comment(self, n, body):
            value=super().comment(n,body);self.save();return value
    gateway.GitHub = PersistentFake
