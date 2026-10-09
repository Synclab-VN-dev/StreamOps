"""HTTP/SQLite integration tests for ACK's durable-commit contract."""
import http.client
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ack_server import AckStore, make_handler, ThreadingHTTPServer, validate_payload

TOKEN = "test-token-at-least-16-bytes"
PAYLOAD = {
    "version": 1, "sessionId": "f77c1bee-51d9-4f9d-aedb-22721691dc44",
    "clientSeq": 5, "sourceTimestampC": 1001, "captureTimestampC": 1004,
    "sendTimestampC": 1005, "deviceId": 2, "vendorId": 1118, "productId": 736,
    "sources": 1025, "source": 1025, "keyCode": 96,
    "scanCode": 304, "action": 0, "repeatCount": 0,
    "edge": "DOWN", "foreground": "com.valvesoftware.steamlink",
}


class AckServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temporary.name) / "ack.sqlite")
        self.store = AckStore(self.db_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, payload, token=TOKEN):
        import json
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        conn.request(
            "POST", "/ack", json.dumps(payload).encode("utf-8"),
            headers={"X-XC-Token": token, "Content-Type": "application/json"},
        )
        result = conn.getresponse()
        body = json.loads(result.read().decode("utf-8"))
        status = result.status
        conn.close()
        return status, body

    def count(self):
        with sqlite3.connect(self.db_path) as db:
            return db.execute("SELECT count(*) FROM ack_events").fetchone()[0]

    def test_ack_only_after_durable_insert_and_preserves_both_c_timestamps(self):
        status, body = self.request(PAYLOAD)
        self.assertEqual(200, status)
        self.assertEqual("COMMITTED", body["status"])
        self.assertEqual(PAYLOAD["sessionId"], body["sessionId"])
        self.assertEqual(PAYLOAD["clientSeq"], body["clientSeq"])
        self.assertFalse(body["duplicate"])
        self.assertEqual(1, self.count())
        with sqlite3.connect(self.db_path) as db:
            src, captured, json_payload = db.execute(
                "SELECT source_timestamp_c, capture_timestamp_c, payload_json FROM ack_events"
            ).fetchone()
        self.assertEqual(1001, src)
        self.assertEqual(1004, captured)
        self.assertIn('"sendTimestampC":1005', json_payload)

    def test_retry_same_seq_is_idempotent_and_conflict_is_rejected(self):
        first = self.request(PAYLOAD)
        second = self.request(PAYLOAD)
        self.assertEqual(first[1]["receiptSeq"], second[1]["receiptSeq"])
        self.assertTrue(second[1]["duplicate"])
        conflict = dict(PAYLOAD, keyCode=97)
        self.assertEqual(400, self.request(conflict)[0])
        self.assertEqual(1, self.count())

    def test_rejected_auth_does_not_write(self):
        self.assertEqual(403, self.request(PAYLOAD, "wrong")[0])
        self.assertEqual(0, self.count())

    def test_invalid_payload_does_not_write(self):
        self.assertEqual(400, self.request(dict(PAYLOAD, captureTimestampC=999))[0])
        self.assertEqual(400, self.request(dict(PAYLOAD, clientSeq=True))[0])
        self.assertEqual(0, self.count())

    def test_clear_with_new_session_id_does_not_collide(self):
        self.assertEqual(200, self.request(PAYLOAD)[0])
        next_session = dict(
            PAYLOAD, sessionId="597a9da1-e7ea-4e4b-a731-49e11e5b2600", clientSeq=1
        )
        self.assertEqual(200, self.request(next_session)[0])
        self.assertEqual(2, self.count())


if __name__ == "__main__":
    unittest.main()

