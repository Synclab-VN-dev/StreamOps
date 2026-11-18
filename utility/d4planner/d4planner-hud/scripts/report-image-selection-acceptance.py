#!/usr/bin/env python3
"""F2 renderer regression against a running test HUD over HTTP. Never submits an issue.

Requires Playwright. The HTTP host may be the existing synthetic browser_fixture
(Linux) or an installed native HUD (Windows CDP). Uses real browser file inputs;
asserts both their reset value and the actual outgoing preview JSON. No route mocks.
"""
import argparse
import base64
import json
import struct
import zlib
from pathlib import Path
from playwright.sync_api import sync_playwright


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff\xff')) + chunk(b'IEND', b'')


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    with sync_playwright() as p:
        browser = (p.chromium.connect_over_cdp(args.browser_cdp) if args.browser_cdp
                   else p.chromium.launch(executable_path=args.chromium))
        context = browser.new_context(viewport={'width': 960, 'height': 720})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        payload = {'name': 'screenshot-1.png', 'mimeType': 'image/png', 'buffer': png()}
        consent_label = 'I consent to upload these images as visible Release assets'
        try:
            page.goto(args.url)
            page.get_by_label('Access token').fill(args.token_file.read_text().strip())
            page.get_by_role('button', name='Connect', exact=True).click()
            page.get_by_role('tab', name='Current', exact=True).wait_for()

            def open_report():
                page.get_by_role('button', name='Open target menu').click()
                page.get_by_role('menuitem', name='Report Issue', exact=True).click()

            def choose(file):
                with page.expect_file_chooser() as chooser:
                    page.get_by_label('Attach screenshots').click()
                chooser.value.set_files(file)

            def collect():
                with page.expect_request(lambda r: r.url.endswith('/api/v1/reports/preview') and r.method == 'POST') as request:
                    page.get_by_role('button', name='Preview collection', exact=True).click()
                page.get_by_label('Collection preview').wait_for()
                return request.value.post_data_json

            def discard():
                page.get_by_role('button', name='Discard unsent draft', exact=True).click()
                page.get_by_label('Collection preview').wait_for(state='detached')
                page.get_by_role('button', name='Close report', exact=True).click()

            for name, invalid in [('invalid-type', {'name': 'bad.svg', 'mimeType': 'image/svg+xml', 'buffer': b'<svg/>'}),
                                  ('oversized', {'name': 'large.png', 'mimeType': 'image/png', 'buffer': b'x' * (2 * 1024 * 1024 + 1)})]:
                open_report(); choose(payload)
                page.get_by_alt_text('Selected screenshot 1', exact=True).wait_for()
                page.get_by_label(consent_label).check(); choose(invalid)
                page.get_by_role('alert').wait_for()
                count = page.locator('img[alt^="Selected screenshot"]').count()
                consent = page.get_by_label(consent_label)
                retained_consent = consent.count() > 0 and consent.is_checked()
                page.locator('.report-panel').screenshot(path=str(args.output / f'{name}.png'))
                sent = collect()
                actual = {'selectedImages': count, 'oldConsent': retained_consent,
                          'sentImages': len(sent.get('images', [])), 'sentConsent': sent.get('imageConsent', False)}
                expected = {'selectedImages': 0, 'oldConsent': False, 'sentImages': 0, 'sentConsent': False}
                checks.append({'case': name, 'expected': expected, 'actual': actual, 'status': 'PASS' if actual == expected else 'FAIL'})
                discard()
            open_report(); choose(payload)
            page.get_by_alt_text('Selected screenshot 1', exact=True).wait_for()
            page.get_by_label(consent_label).check()
            page.get_by_role('button', name='Remove screenshot 1', exact=True).click()
            reset = page.get_by_label('Attach screenshots').input_value() == ''
            choose(payload)
            page.get_by_alt_text('Selected screenshot 1', exact=True).wait_for()
            new_consent = not page.get_by_label(consent_label).is_checked()
            blocked = page.get_by_role('button', name='Preview collection', exact=True).is_disabled()
            page.get_by_label(consent_label).check()
            sent = collect()
            same_bytes = sent.get('images') == [{'mediaType': 'image/png', 'base64': base64.b64encode(png()).decode()}]
            actual = {'inputReset': reset, 'freshConsentRequired': new_consent, 'previewBlocked': blocked, 'sameFileBytes': same_bytes}
            checks.append({'case': 'remove-reselect-same-file', 'expected': dict.fromkeys(actual, True), 'actual': actual, 'status': 'PASS' if all(actual.values()) else 'FAIL'})
            discard()
            checks.append({'case': 'browser-errors', 'expected': [], 'actual': errors, 'status': 'PASS' if not errors else 'FAIL'})
        finally:
            (args.output / 'report.json').write_text(json.dumps({'browser': browser.version, 'host': args.host_kind, 'checks': checks}, indent=2))
            context.close()
            if not args.browser_cdp:
                browser.close()
    assert checks and all(c['status'] == 'PASS' for c in checks), checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host-kind', choices=['synthetic', 'installed'], required=True)
    parser.add_argument('--browser-cdp')
    parser.add_argument('--chromium')
    run(parser.parse_args())
