#!/usr/bin/env python3
"""Real HTTP/browser clipboard with BE-generated JSON; synthetic native host."""
import argparse
import hashlib
import json
import pathlib
import secrets
import socket
import subprocess
from playwright.sync_api import sync_playwright

ROOT=pathlib.Path(__file__).resolve().parents[1]
def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]
def run(args):
    out=args.output;out.mkdir(parents=True,exist_ok=False)
    data=out/'data';data.mkdir()
    expected=json.loads(args.export.read_text());(data/'character-export.json').write_text(json.dumps(expected))
    token=secrets.token_urlsafe(40);ports=[free_port(),free_port()]
    config={'address':'127.0.0.1','port':ports[0],'plannerPort':ports[1],'credentials':[{'subject':'test','sha256':hashlib.sha256(token.encode()).hexdigest(),'permissions':['hud.read']}]}
    (out/'config.json').write_text(json.dumps(config));checks=[];errors=[]
    process=subprocess.Popen([str(args.server_bin),str(out/'config.json'),str(ROOT/'dist'),str(args.hud),str(data)],stdout=subprocess.PIPE,stdin=subprocess.PIPE,stderr=(out/'server.log').open('w'),text=True)
    try:
        url=json.loads(process.stdout.readline())['url']
        with sync_playwright() as p:
            b=p.chromium.launch(executable_path=args.chromium,headless=True)
            for name,size in [('desktop',{'width':960,'height':800}),('mobile',{'width':412,'height':915})]:
                ctx=b.new_context(viewport=size,is_mobile=name=='mobile',has_touch=name=='mobile',permissions=['clipboard-read','clipboard-write']);page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);page.get_by_label('Access token').fill(token);page.get_by_role('button',name='Connect',exact=True).click()
                page.get_by_role('button',name='Open target menu').click();button=page.get_by_role('menuitem',name='Copy current character JSON for AI analysis');button.click()
                page.get_by_text('Copied to clipboard',exact=True).wait_for();actual=json.loads(page.evaluate('navigator.clipboard.readText()'));assert actual==expected
                page.screenshot(path=str(out/f'{name}-copied.png'));checks.append({'case':name+' actual clipboard equality','status':'PASS'})
                (data/'character-export.json').rename(data/'character-export.saved')
                try:
                    button.click();page.get_by_text('No character data available',exact=True).wait_for();assert json.loads(page.evaluate('navigator.clipboard.readText()'))==expected
                    checks.append({'case':name+' source unavailable leaves clipboard unchanged','status':'PASS'})
                finally:(data/'character-export.saved').rename(data/'character-export.json')
                ctx.close()
            b.close()
        assert not errors,errors
    except Exception as error:
        checks.append({'case':'workflow','status':'FAIL','error':str(error)});raise
    finally:
        if process.poll() is None:process.stdin.write('\n');process.stdin.flush()
        process.wait(timeout=80)
        released=[]
        for port in ports:
            with socket.socket() as s:released.append(s.connect_ex(('127.0.0.1',port))!=0)
        (out/'report.json').write_text(json.dumps({'checks':checks,'errors':errors,'portsReleased':released,'classification':'HTTP_BROWSER_REAL_CLIPBOARD_SYNTHETIC_HOST','android':'NOT_RUN'},indent=2))
        assert all(released)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--export',type=pathlib.Path,required=True);p.add_argument('--hud',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--server-bin',type=pathlib.Path,default=ROOT/'src-hud-server/target/debug/examples/browser_fixture');p.add_argument('--chromium');run(p.parse_args())
