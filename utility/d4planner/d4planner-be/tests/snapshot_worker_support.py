"""Bounded, allowlisted startup evidence for synthetic snapshot IPC tests."""
import re

from d4planner.rulekit import RuleKitProcessWrapper as ProductionWrapper


class RuleKitProcessWrapper(ProductionWrapper):
    async def _drain_stderr(self, stream):
        # These tests intentionally replace the sink, not process startup/IPC.
        # Never print raw child stderr, paths, payloads or arbitrary exceptions.
        tail = b""
        while chunk := await stream.read(4096):
            tail = (tail + chunk)[-8192:]
            match = re.search(
                rb"Rule Kit worker startup failed: (SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN"
                rb"(?::(?:TIMEOUT|OUTPUT_LIMIT|INVALID_RESPONSE|QUERY_FAILED))?)(?:\r?\n)", tail
            )
            if match:
                print("Snapshot Worker startup: " + match[1].decode("ascii"), flush=True)
                tail = b""
