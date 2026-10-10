"""D05: safe, branch-specific diagnostics for real OBS Vendor API responses.

Do not include RTMP URLs, credentials, target payloads, or underlying OBS
exception text in outward-facing error messages or operation status.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from streamops.server.errors import (
    ObsPluginError,
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
)
from streamops.server.services.obs_plugin import ObsPluginService
from streamops.server.obs.client import ObsClient


SECRET = "stream_key=should-never-appear"


class _VendorClient:
    def __init__(self, response=None, *, connect_error=None, request_error=None, close_error=None):
        self.response = response
        self.connect_error = connect_error
        self.request_error = request_error
        self.close_error = close_error
        self.connected = False
        self.closed = False
        self.calls = []

    def connect(self):
        self.connected = True
        if self.connect_error is not None:
            raise self.connect_error

    def request(self, operation, payload):
        self.calls.append((operation, payload))
        if self.request_error is not None:
            raise self.request_error
        return self.response

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _service(client: _VendorClient) -> ObsPluginService:
    return ObsPluginService(SimpleNamespace(client_factory=lambda: client), object())


@pytest.mark.parametrize("targets", [[], [{"id": "target-1", "server": SECRET}]])
def test_d05_vendor_probe_accepts_valid_target_arrays_without_returning_data(targets):
    # Contract: OBS WebSocket CallVendorRequest returns responseData,
    # not vendorResponseData, after ObsClient.request unwraps the envelope.
    client = _VendorClient({
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "list_targets",
        "responseData": {"targets": targets},
    })
    assert _service(client)._verify_vendor() is None
    assert client.connected is True
    assert client.closed is True
    assert client.calls == [("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "list_targets",
        "requestData": {},
    })]


@pytest.mark.parametrize(("response", "reason"), [
    (None, "response_invalid"),
    ([], "response_invalid"),
    ({}, "vendor_response_missing"),
    ({"responseData": None}, "vendor_response_missing"),
    ({"vendorResponseData": {"targets": []}}, "vendor_response_missing"),
    ({"responseData": {"error": SECRET}}, "vendor_error"),
    ({"responseData": {"targets": None}}, "targets_invalid"),
    ({"responseData": {"targets": {"id": SECRET}}}, "targets_invalid"),
])
def test_d05_vendor_probe_classifies_malformed_replies_without_exposing_data(response, reason):
    client = _VendorClient(response)
    with pytest.raises(ObsPluginError) as failure:
        _service(client)._verify_vendor()
    assert failure.value.code == "plugin_verify_failed"
    assert failure.value.status_code == 409
    assert f"({reason})" in str(failure.value)
    assert SECRET not in str(failure.value)
    assert client.closed is True


@pytest.mark.parametrize(("connect_error", "request_error", "reason"), [
    (ObsWebSocketConnectionError(SECRET), None, "connection_failed"),
    (RuntimeError(SECRET), None, "connection_failed"),
    (None, ObsWebSocketRequestError(SECRET), "request_rejected"),
    (None, RuntimeError(SECRET), "request_failed"),
])
def test_d05_vendor_probe_sanitizes_transport_or_request_failure(connect_error, request_error, reason):
    client = _VendorClient(
        {"responseData": {"targets": []}},
        connect_error=connect_error,
        request_error=request_error,
    )
    with pytest.raises(ObsPluginError) as failure:
        _service(client)._verify_vendor()
    assert failure.value.code == "plugin_verify_failed"
    assert failure.value.status_code == 409
    assert f"({reason})" in str(failure.value)
    assert SECRET not in str(failure.value)
    assert client.closed is True


def test_d05_vendor_probe_ignores_close_failure_after_successful_probe():
    client = _VendorClient(
        {"responseData": {"targets": []}},
        close_error=RuntimeError(SECRET),
    )
    assert _service(client)._verify_vendor() is None
    assert client.closed is True


def test_d05_vendor_probe_without_client_factory_is_noop_for_existing_test_doubles():
    assert ObsPluginService(SimpleNamespace(), object())._verify_vendor() is None


def test_d05_real_obsclient_request_envelope_uses_response_data(monkeypatch):
    """Exercise the v5 op=7 envelope rather than only a mocked client.reply."""
    client = ObsClient()
    client._ws = object()
    sent = []
    monkeypatch.setattr("streamops.server.obs.client.uuid.uuid4", lambda: "d05")
    monkeypatch.setattr(client, "_send", lambda message: sent.append(message))
    monkeypatch.setattr(client, "_recv", lambda: {
        "op": 7,
        "d": {
            "requestType": "CallVendorRequest",
            "requestId": "streamops-d05",
            "requestStatus": {"result": True, "code": 100},
            "responseData": {
                "vendorName": "sorayuki.multi_rtmp",
                "requestType": "list_targets",
                "responseData": {"targets": [{"server": SECRET}]},
            },
        },
    })
    reply = client.request("CallVendorRequest", {
        "vendorName": "sorayuki.multi_rtmp",
        "requestType": "list_targets",
        "requestData": {},
    })
    assert reply["responseData"]["targets"][0]["server"] == SECRET
    assert sent[0]["d"]["requestType"] == "CallVendorRequest"
    # The verification boundary must validate the documented response shape
    # without reflecting secrets back to the caller.
    vendor_client = _VendorClient(reply)
    assert _service(vendor_client)._verify_vendor() is None
