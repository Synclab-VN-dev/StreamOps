"""Hosting-neutral S9 service. No deployment, repository provisioning or client credentials.

The host supplies an authenticated subject and a GitHub App installation token.
SQLite BEGIN IMMEDIATE serializes report mutations (one durable service database).
Ambiguous Issue POSTs NEVER repeat: reconciliation or operator resolution is required.
"""

from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

REPO = "Synclab-VN-dev/StreamOps"
TAG = "d4planner-bug-report-logs"
NAME = "D4Planner Bug Report Logs"
PREFIX = "<!-- d4planner-diagnostic/v1 "
MAX_BYTES = 64_000_000


class Rejected(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def report_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise Rejected("INVALID_REPORT_ID", 400)
    return value


def validate_release(release, release_id):
    if (
        release.get("id") != release_id
        or release.get("tag_name") != TAG
        or release.get("name") != NAME
        or release.get("prerelease") is not True
        or release.get("draft") is not False
        or release.get("immutable") is not False
    ):
        raise Rejected("RELEASE_IDENTITY_OR_IMMUTABILITY_BLOCKED")


def mapping_text(mapping):
    return PREFIX + json.dumps(mapping, sort_keys=True, separators=(",", ":")) + " -->"


def read_mapping(comment, bot_id):
    if comment.get("user", {}).get("id") != bot_id:
        return None
    body = comment.get("body", "")
    if not body.startswith(PREFIX) or not body.endswith(" -->") or len(body) > 4096:
        return None
    try:
        value = json.loads(body[len(PREFIX) : -4])
        report_id(value["reportId"])
        if value["schemaVersion"] != "d4planner-issue-asset/v1":
            return None
        return value
    except (ValueError, KeyError, TypeError, Rejected):
        return None


def verify_mapping(m, issue, release_id, asset):
    return (
        m is not None
        and m.get("diagnosticStatus") == "UPLOADED"
        and m.get("issueNumber") == issue.get("number")
        and m.get("releaseId") == release_id
        and m.get("releaseTag") == TAG
        and m.get("assetId") == asset.get("id")
        and m.get("assetName") == asset.get("name")
        and m.get("assetName") == f'issue-{issue["number"]}-{m["reportId"]}.zip.age'
        and isinstance(m.get("assetSha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", m["assetSha256"]) is not None
        and asset.get("digest") == "sha256:" + m["assetSha256"]
        and m.get("bytes") == asset.get("size")
        and asset.get("state") == "uploaded"
    )


def age_envelope(data):
    # Format check only, never a claim that the server can decrypt/authenticate ciphertext.
    # Native encryption is the trust boundary; authenticated malicious uploaders remain a hosting risk.
    return (
        re.match(
            rb"age-encryption\.org/v1\n-> X25519 [A-Za-z0-9+/]{43}\n[A-Za-z0-9+/]{43}\n--- [A-Za-z0-9+/]{43}\n",
            data,
        )
        is not None
        and len(data) >= 200
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Rejected("GITHUB_REDIRECT_REFUSED", 503)


class GitHub:
    """Only fixed repository endpoints; token callback is server-only App custody."""

    def __init__(self, token):
        self.token = token

    def request(self, method, path, body=None, upload=False):
        if not path.startswith(f"/repos/{REPO}/"):
            raise Rejected("INVALID_GITHUB_PATH")
        raw = (
            body
            if isinstance(body, bytes)
            else (json.dumps(body).encode() if body is not None else None)
        )
        base = "https://uploads.github.com" if upload else "https://api.github.com"
        req = Request(
            base + path,
            data=raw,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token(),
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": (
                    "application/octet-stream" if upload else "application/json"
                ),
                "User-Agent": "D4Planner-Report-Gateway",
            },
        )
        try:
            with build_opener(NoRedirect()).open(req, timeout=30) as response:
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise Rejected("GITHUB_RESPONSE_LIMIT")
                return json.loads(data) if data else None
        except HTTPError as exc:
            raise Rejected(
                (
                    "GITHUB_RATE_LIMIT"
                    if exc.code == 429
                    or exc.code == 403
                    and exc.headers.get("X-RateLimit-Remaining") == "0"
                    else f"GITHUB_{exc.code}"
                ),
                503,
            ) from None

    def pages(self, path):
        # Bounded enumeration: never conclude absent on truncated coverage.
        result = []
        for page in range(1, 101):
            batch = self.request(
                "GET",
                path + ("&" if "?" in path else "?") + f"per_page=100&page={page}",
            )
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise Rejected("GITHUB_ENUMERATION_LIMIT")

    def release(self, rid):
        return self.request("GET", f"/repos/{REPO}/releases/{rid}")

    def assets(self, rid):
        return self.pages(f"/repos/{REPO}/releases/{rid}/assets")

    def issues(self):
        return self.pages(f"/repos/{REPO}/issues?state=all")

    def issue(self, n):
        return self.request("GET", f"/repos/{REPO}/issues/{n}")

    def comments(self, n):
        return self.pages(f"/repos/{REPO}/issues/{n}/comments")

    def create_issue(self, title, body):
        return self.request(
            "POST", f"/repos/{REPO}/issues", {"title": title, "body": body}
        )

    def upload(self, rid, name, data):
        return self.request(
            "POST", f"/repos/{REPO}/releases/{rid}/assets?name={name}", data, True
        )

    def comment(self, n, body):
        return self.request(
            "POST", f"/repos/{REPO}/issues/{n}/comments", {"body": body}
        )

    def delete(self, aid):
        return self.request("DELETE", f"/repos/{REPO}/releases/assets/{aid}")


class Service:
    def __init__(self, db, github, release_id, bot_id, max_bytes, clock=time.time):
        if not (0 < max_bytes <= MAX_BYTES and release_id > 0 and bot_id > 0):
            raise Rejected("INVALID_CONFIGURATION")
        (
            self.db,
            self.github,
            self.release_id,
            self.bot_id,
            self.max_bytes,
            self.clock,
        ) = (Path(db), github, release_id, bot_id, max_bytes, clock)
        with self.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS request_budget(subject TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, subject TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, issue INTEGER, created REAL NOT NULL)"
            )
        self.db.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.db, timeout=5)

    def authorize_request(self, subject):
        if not isinstance(subject, str) or not subject or len(subject) > 256:
            raise Rejected("UNAUTHENTICATED", 401)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT started,count FROM request_budget WHERE subject=?", (subject,)
            ).fetchone()
            now = self.clock()
            if row and row[0] > now - 3600 and row[1] >= 60:
                raise Rejected("RATE_LIMIT", 429)
            started, count = (
                (row[0], row[1] + 1) if row and row[0] > now - 3600 else (now, 1)
            )
            c.execute(
                "INSERT OR REPLACE INTO request_budget VALUES(?,?,?)",
                (subject, started, count),
            )

    def prepare(self, subject, rid, request):
        report_id(rid)
        if not subject or len(subject) > 256:
            raise Rejected("UNAUTHENTICATED", 401)
        if set(request) != {"description", "artifact"}:
            raise Rejected("INVALID_REQUEST", 400)
        d, a = request["description"], request["artifact"]
        if set(d) != {"issueType", "title", "actual", "expected", "steps"} or any(
            not isinstance(v, str) or len(v.encode("utf-8")) > 8000 or "\x00" in v
            for v in d.values()
        ):
            raise Rejected("INVALID_FORM", 400)
        if (
            d["issueType"]
            not in [
                "Incorrect Equipment",
                "Crash / Startup",
                "HUD / Display",
                "Rule Kit / Calculation",
                "Other",
            ]
            or not all(d[k].strip() for k in ["title", "actual", "expected"])
            or len(d["title"]) > 100
        ):
            raise Rejected("INVALID_FORM", 400)
        if (
            set(a) != {"reportId", "bytes", "sha256"}
            or a["reportId"] != rid
            or type(a["bytes"]) is not int
            or not 0 < a["bytes"] <= self.max_bytes
            or not isinstance(a["sha256"], str)
            or not re.fullmatch("[0-9a-f]{64}", a["sha256"])
        ):
            raise Rejected("INVALID_ARTIFACT", 400)
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute(
                "SELECT subject,request FROM reports WHERE id=?", (rid,)
            ).fetchone()
            if existing:
                if existing != (subject, canonical):
                    raise Rejected("IDEMPOTENCY_CONFLICT")
            else:
                if (
                    c.execute(
                        "SELECT COUNT(*) FROM reports WHERE subject=? AND created>?",
                        (subject, self.clock() - 3600),
                    ).fetchone()[0]
                    >= 5
                ):
                    raise Rejected("RATE_LIMIT", 429)
                c.execute(
                    "INSERT INTO reports VALUES(?,?,?,'PREPARED',NULL,?)",
                    (rid, subject, canonical, self.clock()),
                )
        return {"reportId": rid, "status": "PREPARED"}

    def upload(self, subject, rid, data):
        report_id(rid)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT subject,request,state,issue FROM reports WHERE id=?", (rid,)
            ).fetchone()
            if not row or row[0] != subject:
                raise Rejected("REPORT_NOT_FOUND", 404)
            req, state, number = json.loads(row[1]), row[2], row[3]
            if (
                len(data) > self.max_bytes
                or len(data) != req["artifact"]["bytes"]
                or hashlib.sha256(data).hexdigest() != req["artifact"]["sha256"]
                or not age_envelope(data)
            ):
                raise Rejected("INVALID_CIPHERTEXT", 400)
            validate_release(self.github.release(self.release_id), self.release_id)
            marker = f"<!-- d4planner-report:{rid} -->"
            if number is None:
                if state == "CREATING":
                    matches = [
                        i
                        for i in self.github.issues()
                        if i.get("body", "").startswith(marker + "\n")
                        and i.get("user", {}).get("id") == self.bot_id
                        and "pull_request" not in i
                    ]
                    if len(matches) != 1:
                        raise Rejected("CREATE_OUTCOME_UNCERTAIN")
                    number = matches[0]["number"]
                else:
                    c.execute("UPDATE reports SET state='CREATING' WHERE id=?", (rid,))
                    c.commit()
                    # Persist intent before POST. Crash/ambiguous response cannot cause another POST.
                    c.execute("BEGIN IMMEDIATE")
                    d = req["description"]
                    body = f'{marker}\nDiagnostic status: LOG_UPLOAD_PENDING until the bot mapping comment confirms upload.\n\nType: {d["issueType"]}\n\nActual:\n{d["actual"]}\n\nExpected:\n{d["expected"]}\n\nSteps:\n{d["steps"]}'
                    number = self.github.create_issue(d["title"], body)["number"]
                c.execute(
                    "UPDATE reports SET issue=?,state='UPLOAD_PENDING' WHERE id=?",
                    (number, rid),
                )
                c.commit()
                c.execute("BEGIN IMMEDIATE")
            name = f"issue-{number}-{rid}.zip.age"
            assets = self.github.assets(self.release_id)
            matches = [a for a in assets if a.get("name") == name]
            if len(matches) > 1:
                raise Rejected("DUPLICATE_ASSET")
            if not matches and state == "COMPLETE":
                return {
                    "reportId": rid,
                    "issueUrl": f"https://github.com/{REPO}/issues/{number}",
                    "status": "EXPIRED",
                }
            if not matches:
                if len(assets) >= 1000:
                    raise Rejected("RELEASE_ASSET_LIMIT")
                asset = self.github.upload(self.release_id, name, data)
            else:
                asset = matches[0]
            mapping = {
                "schemaVersion": "d4planner-issue-asset/v1",
                "reportId": rid,
                "issueNumber": number,
                "releaseId": self.release_id,
                "releaseTag": TAG,
                "assetId": asset["id"],
                "assetName": name,
                "assetSha256": req["artifact"]["sha256"],
                "bytes": len(data),
                "uploadedAt": asset.get("created_at"),
                "diagnosticStatus": "UPLOADED",
            }
            issue = self.github.issue(number)
            if (
                not issue.get("body", "").startswith(marker + "\n")
                or issue.get("user", {}).get("id") != self.bot_id
                or asset.get("uploader", {}).get("id") != self.bot_id
                or not verify_mapping(mapping, issue, self.release_id, asset)
            ):
                raise Rejected("REMOTE_BINDING_MISMATCH")
            mappings = [
                read_mapping(x, self.bot_id) for x in self.github.comments(number)
            ]
            valid = [m for m in mappings if m and m.get("reportId") == rid]
            if valid and any(m != mapping for m in valid):
                raise Rejected("MAPPING_CONFLICT")
            if not valid:
                self.github.comment(number, mapping_text(mapping))
            c.execute("UPDATE reports SET state='COMPLETE' WHERE id=?", (rid,))
            return {
                "reportId": rid,
                "issueUrl": f"https://github.com/{REPO}/issues/{number}",
                "status": "COMPLETE",
                "mapping": mapping,
            }


class Application:
    """WSGI adapter. Authentication MUST validate signature/issuer/audience/expiry upstream.
    No development auth bypass or production credential defaults. No CORS/web bearer storage.
    """

    def __init__(self, service, authenticate):
        self.service, self.authenticate = service, authenticate

    def __call__(self, environ, start_response):
        try:
            subject = self.authenticate(environ.get("HTTP_AUTHORIZATION", ""))
            self.service.authorize_request(subject)
            path = environ.get("PATH_INFO", "")
            match = re.fullmatch(r"/reports/([0-9a-f-]{36})(/asset)?", path)
            if not match:
                raise Rejected("NOT_FOUND", 404)
            rid, asset = match.groups()
            limit = self.service.max_bytes if asset else 30_000
            n = int(environ.get("CONTENT_LENGTH", "0"))
            if n < 1 or n > limit:
                raise Rejected("REQUEST_TOO_LARGE", 413)
            data = environ["wsgi.input"].read(n)
            if len(data) != n:
                raise Rejected("INVALID_LENGTH", 400)
            if asset and environ["REQUEST_METHOD"] == "POST":
                result = self.service.upload(subject, rid, data)
            elif not asset and environ["REQUEST_METHOD"] == "PUT":
                result = self.service.prepare(subject, rid, json.loads(data))
            else:
                raise Rejected("METHOD_NOT_ALLOWED", 405)
            status = 200
        except Rejected as exc:
            status, result = exc.status, {"error": exc.code}
        except (ValueError, TypeError, KeyError):
            status, result = 400, {"error": "INVALID_REQUEST"}
        except Exception:
            status, result = 503, {"error": "RETRY_RECONCILE"}
        body = json.dumps(result).encode()
        start_response(
            f"{status} Result",
            [
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]
