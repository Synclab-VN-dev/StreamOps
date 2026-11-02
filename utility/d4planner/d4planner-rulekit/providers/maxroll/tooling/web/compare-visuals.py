#!/usr/bin/env python3
"""Compare private online-capture references with HTTP replay at identical inner viewports."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops
p=argparse.ArgumentParser()
p.add_argument('reference',type=Path)
p.add_argument('actual',type=Path)
args=p.parse_args()
results=[]
for expected in sorted(args.reference.glob('*.png')):
    if not expected.name.startswith(('desktop-','mobile-')):
        continue
    actual=args.actual/expected.name
    result={'state':expected.name,'expected':'same native state and inner viewport'}
    if not actual.exists():
        result.update(status='NOT_RUN',reason='actual screenshot absent')
    else:
        a=Image.open(expected).convert('RGB');b=Image.open(actual).convert('RGB')
        result.update(expectedSize=a.size,actualSize=b.size)
        if a.size!=b.size:
            result.update(status='FAIL',reason='geometry mismatch')
        else:
            diff=ImageChops.difference(a,b)
            # Small anti-aliasing differences are reported separately; no content masks.
            pixels=list(diff.getdata());changed=sum(max(c)>16 for c in pixels)
            result.update(changedFraction=changed/len(pixels),meanChannelError=sum(sum(c) for c in pixels)/(len(pixels)*3),status='PASS' if changed/len(pixels)<=0.005 else 'FAIL')
            diff.save(args.actual/('diff-'+expected.name))
    results.append(result)
(args.actual/'visual-report.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
raise SystemExit(0 if results and all(r['status']=='PASS' for r in results) else 1)
