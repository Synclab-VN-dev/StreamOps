#!/usr/bin/env python3
"""HTTPS browser regression against a provisioned, isolated test runtime.

The browser must already trust its certificate. No TLS bypass, protocol override,
SSH tunnel, request interception, or production runtime should be used. The test
stops/starts the backend. It does not submit a GitHub issue. Artifacts stay private.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def run(args):
    origin = args.url.rstrip("/")
    assert urlsplit(origin).scheme == "https", "HTTPS required"
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    checks, protocols, frames, errors, sockets = [], [], [], [], []

    def check(name, expected, actual):
        checks.append(dict(name=name, expected=expected, actual=actual,
                           status="PASS" if actual == expected else "FAIL"))
        assert actual == expected, (name, expected, actual)

    try:
        with sync_playwright() as p:
            launch = {"headless": True}
            if args.chromium:
                launch["executable_path"] = args.chromium
            browser = p.chromium.launch(**launch)
            try:
                context = browser.new_context(viewport={"width": 960, "height": 720})
                page = context.new_page()
                cdp = context.new_cdp_session(page)
                cdp.send("Network.enable")

                def response(event):
                    r = event["response"]
                    # Never persist request headers, session cookies or payloads.
                    protocols.append(dict(path=urlsplit(r["url"]).path,
                                          protocol=r["protocol"], status=r["status"]))

                def websocket(ws):
                    sockets.append(ws.url)
                    ws.on("framereceived", lambda data: frames.append(json.loads(data)))

                cdp.on("Network.responseReceived", response)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("websocket", websocket)
                page.goto(origin)
                page.get_by_label("Access token").fill(args.token_file.read_text().strip())
                page.get_by_role("button", name="Connect", exact=True).click()
                page.get_by_role("tab", name="Current", exact=True).wait_for(timeout=30000)
                deadline = 30
                while not any(f.get("connected") and f.get("snapshot") for f in frames) and deadline:
                    page.wait_for_timeout(1000)
                    deadline -= 1
                check("WSS connected HUD projection", True,
                      any(f.get("connected") and f.get("snapshot") for f in frames))
                check("WSS exact origin", True,
                      bool(sockets) and all(u == origin.replace("https:", "wss:", 1)
                                            + "/api/v1/hud/stream" for u in sockets))
                cookie = next(c for c in context.cookies() if c["name"] == "d4hud_session")
                check("secure session", [True, True, "Strict"],
                      [cookie["secure"], cookie["httpOnly"], cookie["sameSite"]])
                check("session invisible to script", False,
                      page.evaluate("document.cookie.includes('d4hud_session')"))
                rejected = page.evaluate("""async () => {
                    const r = await fetch('/api/v1/runtime/backend/stop', {method:'POST'});
                    return {status:r.status, code:(await r.json()).error.code};
                }""")
                check("cookie mutation without CSRF rejected", 403, rejected["status"])
                page.get_by_role("button", name="Open target menu").click()
                page.get_by_role("menuitem", name="Runtime Manager", exact=True).click()
                page.get_by_role("button", name="Stop Backend", exact=True).click()
                page.get_by_role("button", name="Confirm Stop", exact=True).click()
                page.get_by_role("button", name="Start Backend", exact=True).wait_for(timeout=75000)
                page.screenshot(path=str(args.output / "https-stopped.png"))
                page.get_by_role("button", name="Start Backend", exact=True).click()
                page.get_by_role("button", name="Stop Backend", exact=True).wait_for(timeout=75000)
                check("authenticated runtime stop/start", True, True)
                page.get_by_role("button", name="Close Runtime Manager").click()
                old_count = len(frames)
                page.reload()
                page.get_by_role("tab", name="Current", exact=True).wait_for(timeout=30000)
                deadline = 30
                while not any(f.get("connected") for f in frames[old_count:]) and deadline:
                    page.wait_for_timeout(1000)
                    deadline -= 1
                check("reload reconnects WSS", True,
                      any(f.get("connected") for f in frames[old_count:]))
                page.screenshot(path=str(args.output / "https-desktop.png"))
                page.set_viewport_size({"width": 412, "height": 915})
                page.screenshot(path=str(args.output / "https-mobile-emulation.png"))
                check("document uses HTTP/2", True,
                      any(r["path"] == "/" and r["protocol"] == "h2" and r["status"] == 200
                          for r in protocols))
                check("authenticated API uses HTTP/2", True,
                      any(r["path"] == "/api/v1/session" and r["protocol"] == "h2"
                          and r["status"] == 200 for r in protocols))
                check("no script errors", [], errors)
                if args.planner_url:
                    # Optional transport fixture; not evidence of native Planner UI coverage.
                    relay = context.new_page()
                    result = relay.goto(args.planner_url)
                    check("authenticated relay", 200, result.status)
                    relay.get_by_text(args.planner_text, exact=True).wait_for()
                    relay.screenshot(path=str(args.output / "https-relay.png"))
                checks.append(dict(name="browser version", status="PASS", actual=browser.version))
            finally:
                browser.close()
    except Exception as error:
        checks.append(dict(name="workflow", status="FAIL", actual=str(error)))
        raise
    finally:
        report = dict(status="PASS" if checks and all(c["status"] == "PASS" for c in checks)
                      else "FAIL", classification=args.classification, checks=checks,
                      responses=protocols, wssConnections=len(sockets),
                      android="NOT_RUN", ci="CI_NOT_CHECKED")
        (args.output / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium", default=os.environ.get("CHROMIUM_EXECUTABLE"))
    parser.add_argument("--classification", required=True,
                        choices=["SYNTHETIC_NATIVE_HOST", "WINDOWS_INSTALLED"])
    parser.add_argument("--planner-url")
    parser.add_argument("--planner-text", default="Synthetic Planner transport fixture")
    run(parser.parse_args())
