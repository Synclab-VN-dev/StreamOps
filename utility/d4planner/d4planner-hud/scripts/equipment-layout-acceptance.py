#!/usr/bin/env python3
"""Private BE projection through real HTTP; fixture native host is synthetic."""
import argparse, hashlib, json, os, pathlib, secrets, socket, subprocess
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(__file__).resolve().parents[1]
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def run(current,out):
    out.mkdir(parents=True,exist_ok=False);os.chmod(out,0o700)
    value=json.loads(current.read_text());expected={i['slotFamily']:i for i in value['items']}
    assert set(expected)>={'ranged','main_hand','off_hand'} and value['layout']['status']=='VERIFIED'
    hud=json.loads((ROOT.parent/'d4planner-be/contracts/release1/v1/fixtures/hud.no-data.synthetic.json').read_text())
    hud['currentEquipment']=value;hud['health']['captureRuntime']={'state':'RUNNING','detail':'Recorded offline replay'}
    (out/'hud.json').write_text(json.dumps(hud));(out/'data').mkdir()
    token=secrets.token_urlsafe(48);ports=[port(),port()]
    cfg={'address':'127.0.0.1','port':ports[0],'plannerPort':ports[1],'credentials':[{'subject':'fixture-owner','sha256':hashlib.sha256(token.encode()).hexdigest(),'permissions':['hud.read']}]}
    (out/'config.json').write_text(json.dumps(cfg));checks=[];errors=[];external=[]
    process=subprocess.Popen([str(ROOT/'src-hud-server/target/debug/examples/browser_fixture'),str(out/'config.json'),str(ROOT/'dist'),str(out/'hud.json'),str(out/'data')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(out/'server.log').open('w'),text=True)
    try:
        url=json.loads(process.stdout.readline())['url']
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_EXECUTABLE'))
            for name,size in [('desktop',{'width':960,'height':800}),('mobile',{'width':412,'height':915})]:
                context=browser.new_context(viewport=size,is_mobile=name=='mobile',has_touch=name=='mobile');page=context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:external.append(r.url) if not r.url.startswith(url) and not r.url.startswith('data:') else None)
                page.goto(url);page.screenshot(path=str(out/f'{name}-loaded.png'));(out/f'{name}-loaded.html').write_text(page.content());page.get_by_label('Access token').fill(token);page.get_by_role('button',name='Connect',exact=True).click()
                page.get_by_text('Layout · Verified slot layout',exact=True).wait_for()
                for family,label in [('ranged','Ranged'),('main_hand','Main Hand'),('off_hand','Off Hand')]:
                    item=expected[family];row=page.locator('.current-row').filter(has_text=item['name'])
                    assert row.count()==1 and label in row.inner_text()
                    row.click();detail=page.get_by_label('Current equipment detail')
                    assert detail.get_by_role('heading',name=item['name'],exact=True).count()==1
                    assert detail.get_by_text(item['itemType'],exact=False).count()>0
                    page.screenshot(path=str(out/f'{name}-{family}.png'))
                    page.get_by_role('button',name='Close current equipment detail').click()
                page.reload();page.get_by_text('Layout · Verified slot layout',exact=True).wait_for()
                assert page.locator('.current-row').filter(has_text=expected['ranged']['name']).count()==1
                checks.append({'viewport':name,'weapons':'PASS','detail':'PASS','reload':'PASS'});context.close()
            browser.close()
        assert not errors,errors
        assert not external,external
    except Exception as error:
        checks.append({"workflow":"FAIL","error":str(error)})
        raise
    finally:
        if process.poll() is None:process.stdin.write('\n');process.stdin.flush()
        process.wait(timeout=80);released=[]
        for n in ports:
            with socket.socket() as s:released.append(s.connect_ex(('127.0.0.1',n))!=0)
        (out/'report.json').write_text(json.dumps({'checks':checks,'errors':errors,'external':external,'portsReleased':released,'classification':'REAL_HTTP_RECORDED_BE_PROJECTION_SYNTHETIC_NATIVE_HOST','android':'NOT_RUN'},indent=2))
        assert all(released)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--current',type=pathlib.Path,required=True);ap.add_argument('--output',type=pathlib.Path,required=True);a=ap.parse_args();run(a.current,a.output)
