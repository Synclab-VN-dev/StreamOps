"""Game mutation gate: local operator CLI or authenticated remote control.

Only GameService explicitly enables loopback access without a token. The peer
IP is taken from the ASGI socket, never from Host or forwarded headers. Browser
Origin requests and forwarded requests still require a token. Steam Restart
remains token-gated. Never accept credentials in URLs or request bodies.
"""
import hmac
import ipaddress
import os

class GameAccessDenied(Exception):
    code = "capability_disabled"

def authorized(headers) -> bool:
    token = os.environ.get("STREAMOPS_GAME_CONTROL_TOKEN")
    if not token or len(token) < 24:
        return False
    direct = headers.get("x-streamops-game-token","")
    protocols = headers.get("sec-websocket-protocol","")
    values = [direct]
    for item in protocols.split(","):
        item = item.strip()
        prefix = "streamops-game-control."
        if item.startswith(prefix):
            values.append(item[len(prefix):])
    return any(hmac.compare_digest(value, token) for value in values if isinstance(value, str))

def _local_cli(headers, client_host: str | None) -> bool:
    if not client_host or any(headers.get(name) for name in ("origin", "forwarded", "x-forwarded-for")):
        return False
    try:
        return ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        return False

def require_mutation(headers, *, client_host: str | None = None, allow_loopback: bool = False) -> None:
    if authorized(headers) or (allow_loopback and _local_cli(headers, client_host)):
        return
    raise GameAccessDenied("Game controls require a local loopback CLI or valid control token.")
