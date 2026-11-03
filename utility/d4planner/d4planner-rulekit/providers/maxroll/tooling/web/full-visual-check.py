#!/usr/bin/env python3
"""Unmasked same-version comparisons, including mutations of the actual picker icon."""
import json
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageChops
reference, actual = map(Path, sys.argv[1:3])
result = subprocess.run([sys.executable, str(Path(__file__).with_name('compare-visuals.py')), str(reference), str(actual)], capture_output=True, text=True)
normal = json.loads((actual / 'visual-report.json').read_text())
negative = []
for file in sorted(actual.glob('negative-*-picker-artwork.png')):
    expected = reference / file.name.removeprefix('negative-')
    a, b = Image.open(expected).convert('RGB'), Image.open(file).convert('RGB')
    fraction = None
    if a.size == b.size:
        pixels = list(ImageChops.difference(a, b).getdata())
        fraction = sum(max(p) > 16 for p in pixels) / len(pixels)
    negative.append({'state': file.name, 'expected': 'Hidden picker artwork must fail the normal visual gate', 'changedFraction': fraction, 'status': 'PASS' if fraction is not None and fraction > .005 else 'FAIL'})
expected_count = len([r for r in normal if r['state'].endswith('-picker-artwork.png')])
report = {'status': 'PASS' if result.returncode == 0 and expected_count >= 42 and len(negative) == expected_count and all(r['status'] == 'PASS' for r in negative) else 'FAIL', 'normal': normal, 'negative': negative}
(actual / 'full-visual-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps({'status': report['status'], 'normal': len(normal), 'negative': len(negative), 'failures': [r for r in normal + negative if r['status'] != 'PASS']}))
sys.exit(0 if report['status'] == 'PASS' else 1)
