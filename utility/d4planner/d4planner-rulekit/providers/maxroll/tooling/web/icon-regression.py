#!/usr/bin/env python3
"""Compare an original online capture card crop; prove missing artwork fails the same gate."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageChops
p=argparse.ArgumentParser();p.add_argument('reference',type=Path);p.add_argument('actual',type=Path);p.add_argument('missing',type=Path);p.add_argument('--crop',required=True,help='x,y,width,height from original online reference geometry');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
x,y,w,h=map(int,a.crop.split(','));expected=Image.open(a.reference).convert('RGB').crop((x,y,x+w,y+h))
def fraction(file):
    actual=Image.open(file).convert('RGB')
    if actual.size!=expected.size: raise ValueError('Card geometry mismatch')
    return sum(max(pixel)>16 for pixel in ImageChops.difference(expected,actual).getdata())/(w*h)
normal=fraction(a.actual);missing=fraction(a.missing)
report={'expected':'original online capture card ROI','normalChangedFraction':normal,'missingArtworkChangedFraction':missing,'threshold':0.005,'status':'PASS' if normal<=0.005 and missing>0.005 else 'FAIL'}
a.report.write_text(json.dumps(report,indent=2));print(json.dumps(report));raise SystemExit(0 if report['status']=='PASS' else 1)
