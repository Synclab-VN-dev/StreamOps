"""Read-only, secret-safe real OBS multi-RTMP Vendor probe for issue #47.

Run with a commit-pinned StreamOps deployment venv while OBS is READY:
    python scripts/e2e/issue47_probe_vendor.py

Only calls CallVendorRequest/list_targets. Does NOT log response payload,
target URLs, stream keys, credentials, OBS exception text, or take actions.
Exit 0 = Vendor OK, 2 = typed diagnostic failure.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from streamops.server.errors import ObsPluginError
from streamops.server.obs.client import ObsClient
from streamops.server.services.obs_plugin import ObsPluginService


def main() -> int:
    manager = SimpleNamespace(client_factory=ObsClient.from_env)
    probe = ObsPluginService(manager, object())
    try:
        probe._verify_vendor()
    except ObsPluginError as exc:
        # _verify_vendor emits a fixed allowlisted reason, not raw OBS data.
        print(json.dumps({
            "result": "FAIL",
            "error_code": exc.code,
            "diagnostic": str(exc),
        }, sort_keys=True))
        return 2
    print(json.dumps({
        "result": "PASS",
        "vendor": "sorayuki.multi_rtmp",
        "request": "list_targets",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
