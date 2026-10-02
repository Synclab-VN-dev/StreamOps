import json

from streamops.server.obs.client import ObsClient


class _FakeWebSocket:
    def __init__(self) -> None:
        self.messages = iter([
            json.dumps({"op": 0, "d": {"rpcVersion": 1}}),
            json.dumps({"op": 2, "d": {}}),
        ])
        self.sent = []

    def recv(self, timeout=None):
        return next(self.messages)

    def send(self, payload):
        self.sent.append(payload)

    def close(self):
        pass


def test_connect_allows_large_obs_screenshot_messages(monkeypatch):
    captured = {}
    websocket = _FakeWebSocket()

    def fake_connect(uri, **kwargs):
        captured["uri"] = uri
        captured.update(kwargs)
        return websocket

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    client = ObsClient()
    client.connect()

    assert captured["max_size"] == 16 * 1024 * 1024
    assert captured["subprotocols"] == ["obswebsocket.json"]
