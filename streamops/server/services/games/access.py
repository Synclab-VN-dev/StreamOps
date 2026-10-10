"""Game mutation access gate, additive to the existing trusted-LAN read policy.

A mutation token is required even when legacy require_access trusts LAN.
Never accept credentials in query strings or lifecycle request bodies.
"""
import hmac
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

def require_mutation(headers) -> None:
    if not authorized(headers):
        raise GameAccessDenied("Game controls are disabled until a valid control token is supplied.")
