import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from gateway import Service, Application, Rejected, TAG, NAME, read_mapping
from cleanup import cleanup


class FakeGitHub:
    def __init__(self):
        self.r = {
            "id": 77,
            "tag_name": TAG,
            "name": NAME,
            "prerelease": True,
            "draft": False,
            "immutable": False,
        }
        self.items = []
        self.uploads = []
        self.notes = {}
        self.deleted = []
        self.fail = ""
        self.reopen = False
        self.comment_changed = False

    def release(self, rid):
        return copy.deepcopy(self.r)

    def assets(self, rid):
        return copy.deepcopy(self.uploads)

    def issues(self):
        return copy.deepcopy(self.items)

    def issue(self, n):
        result = copy.deepcopy(next(x for x in self.items if x["number"] == n))
        if self.reopen:
            result["state"] = "open"
        return result

    def comments(self, n):
        return copy.deepcopy(self.notes.get(n, []))

    def create_issue(self, title, body):
        i = {
            "number": len(self.items) + 1,
            "body": body,
            "state": "open",
            "user": {"id": 42},
            "closed_at": None,
        }
        self.items.append(i)
        if self.fail == "create":
            self.fail = ""
            raise OSError("ambiguous")
        return i

    def upload(self, rid, name, data):
        a = {
            "id": 100 + len(self.uploads),
            "name": name,
            "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "uploader": {"id": 42},
            "state": "uploaded",
            "created_at": "2026-10-31T00:00:00Z",
        }
        self.uploads.append(a)
        if self.fail == "upload":
            self.fail = ""
            raise OSError("ambiguous")
        return a

    def comment(self, n, body):
        self.notes.setdefault(n, []).append(
            {"id": len(self.notes.get(n, [])) + 1, "user": {"id": 42}, "body": body}
        )
        if self.fail == "mapping":
            self.fail = ""
            raise OSError("ambiguous")

    def complete_issue(self, n, body):
        next(i for i in self.items if i["number"] == n)["body"] = body.replace(
            "\nLOG_UPLOAD_PENDING\n",
            "\nDIAGNOSTICS_UPLOADED (see bot mapping comment)\n",
            1,
        )

    def delete(self, aid):
        self.deleted.append(aid)
        self.uploads = [x for x in self.uploads if x["id"] != aid]


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gh = FakeGitHub()
        self.path = Path(self.tmp.name) / "state.db"
        self.s = Service(self.path, self.gh, 77, 42, 10000)
        self.rid = str(uuid.uuid4())
        self.data = base64.b64decode(
            "YWdlLWVuY3J5cHRpb24ub3JnL3YxCi0+IFgyNTUxOSBiaHRZb3F3RXlrbzUwMXhKWVVnbGhjaDBqRUVhMTlpd1dIM0tNaWFteVJzCnJwTEdJSXVCYi9RdXZBNWJ5Qjk0bWNCbEprVXNVU2Y0MVFnUThFcGZmOUEKLS0tIFNOL0ZTY1R0MWdQWFRWQTlFNEt5aXF3S1dsWDJsOC9DM1ZwRGhuL0puOXMKxhAh8o2pjFPuL+nHtPqhYE7lv1CYC8Vk7frRS75PQEj0GjKJPXrkMfG7MIkkLh+mcdiQYShAyomJmGgY4Q3W0Kk="
        )
        self.request = {
            "description": {
                "issueType": "Other",
                "title": "Example",
                "actual": "Fails",
                "expected": "Works",
                "steps": "Reproduce",
            },
            "artifact": {
                "reportId": self.rid,
                "bytes": len(self.data),
                "sha256": hashlib.sha256(self.data).hexdigest(),
            },
        }

    def ready(self):
        self.s.prepare("alice", self.rid, self.request)
        return self.s.upload("alice", self.rid, self.data)

    def test_success_and_idempotent_retries(self):
        one = self.ready()
        self.s.prepare("alice", self.rid, self.request)
        two = self.s.upload("alice", self.rid, self.data)
        self.assertEqual(one, two)
        self.assertEqual(len(self.gh.items), 1)
        self.assertEqual(len(self.gh.uploads), 1)
        self.assertEqual(len(self.gh.notes[1]), 1)

    def test_crash_after_remote_mutations_reconciles(self):
        for failure in ["create", "upload", "mapping"]:
            with self.subTest(failure=failure):
                self.setUp()
                self.s.prepare("alice", self.rid, self.request)
                self.gh.fail = failure
                with self.assertRaises(OSError):
                    self.s.upload("alice", self.rid, self.data)
                restarted = Service(self.path, self.gh, 77, 42, 10000)
                self.assertEqual(
                    restarted.upload("alice", self.rid, self.data)["status"], "COMPLETE"
                )
                self.assertEqual(len(self.gh.items), 1)
                self.assertEqual(len(self.gh.uploads), 1)
                self.assertEqual(len(self.gh.notes[1]), 1)

    def test_unknown_create_never_repeats_post(self):
        self.s.prepare("alice", self.rid, self.request)
        with self.s.connect() as c:
            c.execute("UPDATE reports SET state='CREATING'")
        with self.assertRaisesRegex(Rejected, "CREATE_OUTCOME_UNCERTAIN"):
            self.s.upload("alice", self.rid, self.data)
        self.assertEqual(self.gh.items, [])

    def test_subject_and_payload_binding(self):
        self.s.prepare("alice", self.rid, self.request)
        with self.assertRaises(Rejected):
            self.s.prepare("bob", self.rid, self.request)
        with self.assertRaises(Rejected):
            self.s.upload("bob", self.rid, self.data)
        self.request["description"]["title"] = "Changed"
        with self.assertRaises(Rejected):
            self.s.prepare("alice", self.rid, self.request)

    def test_plaintext_tamper_size(self):
        self.s.prepare("alice", self.rid, self.request)
        for data in [b"raw secret", self.data + b"X", b"x" * 10001]:
            with self.assertRaises(Rejected):
                self.s.upload("alice", self.rid, data)
        self.assertEqual(self.gh.items, [])

    def test_immutable_wrong_release_fail_before_issue(self):
        self.s.prepare("alice", self.rid, self.request)
        for key, value in [
            ("immutable", True),
            ("tag_name", "d4planner-uat/v1.2.8"),
            ("id", 88),
            ("prerelease", False),
            ("draft", True),
        ]:
            old = self.gh.r[key]
            self.gh.r[key] = value
            with self.assertRaises(Rejected):
                self.s.upload("alice", self.rid, self.data)
            self.gh.r[key] = old
        self.assertEqual(self.gh.items, [])

    def test_rate_limit(self):
        for n in range(6):
            rid = str(uuid.uuid4())
            request = copy.deepcopy(self.request)
            request["artifact"]["reportId"] = rid
            if n < 5:
                self.s.prepare("alice", rid, request)
            else:
                with self.assertRaisesRegex(Rejected, "RATE_LIMIT"):
                    self.s.prepare("alice", rid, request)

    def test_mapping_tamper_blocks_reconciliation(self):
        self.ready()
        self.gh.uploads[0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(Rejected, "REMOTE_BINDING_MISMATCH"):
            self.s.upload("alice", self.rid, self.data)

    def test_auth_wsgi_no_leak(self):
        app = Application(self.s, lambda token: None)
        status = []
        raw = b"".join(
            app({"HTTP_AUTHORIZATION": "Bearer CANARY"}, lambda s, h: status.append(s))
        )
        self.assertTrue(status[0].startswith("401"))
        self.assertNotIn(b"CANARY", raw)
        self.assertEqual(self.gh.items, [])

    def test_wsgi_authenticated_contract(self):
        app = Application(
            self.s, lambda token: "alice" if token == "Bearer short-lived" else None
        )
        body = json.dumps(self.request).encode()
        status = []
        result = b"".join(
            app(
                {
                    "HTTP_AUTHORIZATION": "Bearer short-lived",
                    "PATH_INFO": f"/reports/{self.rid}",
                    "REQUEST_METHOD": "PUT",
                    "CONTENT_LENGTH": str(len(body)),
                    "wsgi.input": io.BytesIO(body),
                },
                lambda s, h: status.append(s),
            )
        )
        self.assertTrue(status[0].startswith("200"))
        self.assertEqual(json.loads(result)["reportId"], self.rid)

    def test_cleanup_boundaries_and_reopen(self):
        self.ready()
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        for hours in [23, 24, 25]:
            self.gh.items[0].update(
                state="closed", closed_at=(now - timedelta(hours=hours)).isoformat()
            )
            audit = cleanup(self.gh, 77, 42, now)
            self.assertEqual(len(audit), int(hours > 24))
            self.assertEqual(self.gh.deleted, [])
        self.gh.reopen = True
        self.assertEqual(cleanup(self.gh, 77, 42, now, False), [])
        self.gh.reopen = False
        self.assertEqual(len(cleanup(self.gh, 77, 42, now, False)), 1)
        self.assertEqual(cleanup(self.gh, 77, 42, now, False), [])
        self.assertEqual(self.gh.deleted, [100])

    def test_open_orphan_foreign_mapping_never_deleted(self):
        self.ready()
        now = datetime(2026, 11, 5, tzinfo=timezone.utc)
        self.assertEqual(cleanup(self.gh, 77, 42, now, False), [])
        self.gh.items[0].update(state="closed", closed_at="2026-10-31T00:00:00Z")
        self.gh.notes[1][0]["user"]["id"] = 999
        self.assertEqual(cleanup(self.gh, 77, 42, now, False), [])
        self.gh.notes[1] = []
        self.assertEqual(cleanup(self.gh, 77, 42, now, False), [])
        self.assertEqual(self.gh.deleted, [])

    def test_changed_mapping_during_cleanup(self):
        self.ready()
        self.gh.items[0].update(state="closed", closed_at="2026-10-31T00:00:00Z")
        original = self.gh.comments
        count = 0

        def comments(n):
            nonlocal count
            count += 1
            return original(n) if count == 1 else []

        self.gh.comments = comments
        self.assertEqual(
            cleanup(self.gh, 77, 42, datetime(2026, 11, 5, tzinfo=timezone.utc), False),
            [],
        )

    def test_permission_failure_safe(self):
        self.s.prepare("alice", self.rid, self.request)

        def blocked(rid):
            raise Rejected("GITHUB_403")

        self.gh.release = blocked
        with self.assertRaisesRegex(Rejected, "GITHUB_403"):
            self.s.upload("alice", self.rid, self.data)
        self.assertEqual(self.gh.items, [])

    def test_concurrent_retries_one_issue_one_asset(self):
        from concurrent.futures import ThreadPoolExecutor

        self.s.prepare("alice", self.rid, self.request)

        def submit(_):
            try:
                return self.s.upload("alice", self.rid, self.data)
            except Rejected as e:
                self.assertEqual(e.code, "CREATE_OUTCOME_UNCERTAIN")

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(submit, range(8)))
        self.s.upload("alice", self.rid, self.data)
        self.assertEqual(len(self.gh.items), 1)
        self.assertEqual(len(self.gh.uploads), 1)

    def test_expired_complete_report_is_not_reuploaded(self):
        self.ready()
        self.gh.uploads = []
        result = self.s.upload("alice", self.rid, self.data)
        self.assertEqual(result["status"], "EXPIRED")
        self.assertEqual(self.gh.uploads, [])

    def test_all_requests_are_rate_limited(self):
        for _ in range(60):
            self.s.authorize_request("alice")
        with self.assertRaisesRegex(Rejected, "RATE_LIMIT"):
            self.s.authorize_request("alice")

    def test_plaintext_with_age_prefix_is_rejected(self):
        data = b"age-encryption.org/v1\nPRIVATE_SECRET_CANARY"
        self.request["artifact"].update(
            bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
        )
        self.s.prepare("alice", self.rid, self.request)
        with self.assertRaisesRegex(Rejected, "INVALID_CIPHERTEXT"):
            self.s.upload("alice", self.rid, data)
        self.assertEqual(self.gh.uploads, [])


if __name__ == "__main__":
    unittest.main()
