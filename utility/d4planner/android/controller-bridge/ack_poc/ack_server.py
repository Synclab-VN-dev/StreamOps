"""Standalone LAN ACK receiver for #79, NOT the canonical D4Planner EventStore.

A sends COMMITTED only after sqlite transaction commit (WAL + FULL sync).
Uses only the Python standard library. Intended for controlled LAN POC only.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from typing import Any


MAX_PAYLOAD_BYTES = 4096
MAX_SESSION_CHARS = 64


class AckStore:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ack_events (
                    receipt_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    client_seq INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    source_timestamp_c INTEGER NOT NULL,
                    capture_timestamp_c INTEGER NOT NULL,
                    received_wall_ns INTEGER NOT NULL,
                    received_mono_ns INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(session_id, client_seq)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS ix_ack_events_time ON ack_events(received_wall_ns)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=0.5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def record(self, payload: dict[str, Any], wall_ns: int, mono_ns: int) -> tuple[int, bool]:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        session = payload["sessionId"]
        sequence = payload["clientSeq"]
        with self._connect() as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO ack_events
                (session_id, client_seq, payload_sha256, source_timestamp_c,
                 capture_timestamp_c, received_wall_ns, received_mono_ns, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session, sequence, digest, payload["sourceTimestampC"],
                    payload["captureTimestampC"], wall_ns, mono_ns, canonical,
                ),
            )
            inserted = cur.rowcount == 1
            row = db.execute(
                "SELECT receipt_seq, payload_sha256 FROM ack_events WHERE session_id=? AND client_seq=?",
                (session, sequence),
            ).fetchone()
            if row is None:
                raise RuntimeError("ACK transaction missing row")
            if row[1] != digest:
                raise ValueError("sequence_reused_with_different_payload")
            receipt_seq = int(row[0])
        # The SQLite transaction has committed successfully before returning.
        return receipt_seq, not inserted


def validate_payload(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("payload_not_object")
    allowed = {
        "version", "sessionId", "clientSeq", "sourceTimestampC",
        "captureTimestampC", "sendTimestampC", "deviceId",
        "vendorId", "productId", "sources", "source", "keyCode",
        "scanCode", "action", "repeatCount", "edge", "foreground",
    }
    if set(item) != allowed:
        raise ValueError("unexpected_or_missing_fields")
    if item["version"] != 1:
        raise ValueError("unsupported_version")
    sid = item["sessionId"]
    if not isinstance(sid, str) or not (8 <= len(sid) <= MAX_SESSION_CHARS):
        raise ValueError("invalid_session")
    for key in (
        "clientSeq", "sourceTimestampC", "captureTimestampC", "sendTimestampC",
        "deviceId", "vendorId", "productId", "sources", "source",
        "keyCode", "scanCode", "action", "repeatCount",
    ):
        if type(item[key]) is not int:
            raise ValueError("invalid_" + key)
    if item["clientSeq"] <= 0 or min(
        item["sourceTimestampC"], item["captureTimestampC"], item["sendTimestampC"]
    ) < 0:
        raise ValueError("invalid_sequence_or_timestamp")
    if not (
        item["sourceTimestampC"] <= item["captureTimestampC"] <= item["sendTimestampC"]
    ):
        raise ValueError("invalid_clock_order")
    if item["edge"] not in ("DOWN", "UP", "REPEAT", "UNKNOWN"):
        raise ValueError("invalid_edge")
    if not isinstance(item["foreground"], str) or len(item["foreground"]) > 128:
        raise ValueError("invalid_foreground")
    return item


def make_handler(store: AckStore, expected_token: str):
    class AckHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/ack":
                self._reply(404, {"error": "not_found"})
                return
            provided = self.headers.get("X-XC-Token", "")
            if not hmac.compare_digest(provided, expected_token):
                self._reply(403, {"error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not (0 < length <= MAX_PAYLOAD_BYTES):
                    raise ValueError("invalid_content_length")
                body = self.rfile.read(length)
                # Reject bools/malformed types via validate_payload.
                payload = validate_payload(json.loads(body))
                received_wall = time.time_ns()
                received_mono = time.perf_counter_ns()
                receipt_seq, duplicate = store.record(payload, received_wall, received_mono)
            except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._reply(400, {"error": str(exc)})
                return
            except sqlite3.Error:
                self._reply(503, {"error": "db_unavailable"})
                return
            self._reply(200, {
                "status": "COMMITTED",
                "sessionId": payload["sessionId"],
                "clientSeq": payload["clientSeq"],
                "receiptSeq": receipt_seq,
                "duplicate": duplicate,
            })

        def do_GET(self):
            self._reply(404, {"error": "not_found"})

        def _reply(self, code: int, data: dict[str, Any]):
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # C may have timed out and failed open; late COMMITTED is possible.
                pass

        def log_message(self, fmt: str, *args):
            # Do not log the shared token or raw body.
            return

    return AckHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="XC / D4Planner #79 ACK-before-forward POC")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind to A LAN IP explicitly for Android C")
    parser.add_argument("--port", type=int, default=18795)
    parser.add_argument(
        "--db", default=str(Path.home() / "xc-ack-poc.sqlite"),
        help="Isolated ACK POC SQLite database. NOT canonical events.db.",
    )
    args = parser.parse_args()
    token = os.environ.get("XC_ACK_TOKEN", "")
    if len(token) < 16:
        parser.error("Set XC_ACK_TOKEN in the environment to a random token >= 16 characters")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    store = AckStore(args.db)
    httpd = ThreadingHTTPServer((args.bind, args.port), make_handler(store, token))
    httpd.daemon_threads = True
    print(f"XC ACK POC listening at http://{args.bind}:{args.port}/ack", flush=True)
    print(f"Isolated SQLite file: {store.db_path}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

