#!/usr/bin/env python3
"""HTTP/browser acceptance with explicit synthetic native callbacks (not Windows UAT).
Run after npm run build and cargo build --example browser_fixture. Output stays private.
"""
import argparse, hashlib, json, os, pathlib, secrets, socket, subprocess, time
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(__file__).resolve().parents[1]
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def run(out):
 out.mkdir(parents=True,exist_ok=False);os.chmod(out,0o700)
 token=secrets.token_urlsafe(48);hud_port,planner_port=port(),port()
 cfg={'address':'127.0.0.1','port':hud_port,'plannerPort':planner_port,'credentials':[{'subject':'fixture-owner','sha256':hashlib.sha256(token.encode()).hexdigest(),'permissions':['hud.read','runtime.control','planner.open','target.select','report.preview','report.read','report.submit']}]}
 (out/'config.json').write_text(json.dumps(cfg));(out/'data').mkdir()
 binary=ROOT/'src-hud-server/target/debug/examples/browser_fixture'
 fixture=ROOT.parent/'d4planner-be/contracts/release1/v1/fixtures/hud.partial.synthetic.json'
 process=subprocess.Popen([str(binary),str(out/'config.json'),str(ROOT/'dist'),str(fixture),str(out/'data')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(out/'server.log').open('w'),text=True)
 checks=[]
 def check(name,expected,actual):
  checks.append({'name':name,'expected':expected,'actual':actual,'status':'PASS' if actual==expected else 'FAIL'})
  assert actual==expected,(name,expected,actual)
 try:
  start=json.loads(process.stdout.readline());url=start['url'];check('same-process listener',process.pid,start['pid'])
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,executable_path=os.environ.get("CHROMIUM_EXECUTABLE"))
   context=browser.new_context(viewport={'width':960,'height':720})
   page=context.new_page();errors=[];external=[];api=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:external.append(r.url) if not r.url.startswith(url) and not r.url.startswith('data:') else None)
   page.on('request',lambda r:api.append(r.url) if '/api/' in r.url else None)
   page.goto(url);page.get_by_label('Access token').fill(token);page.get_by_role('button',name='Connect',exact=True).click()
   page.get_by_role('tab',name='Current',exact=True).wait_for(timeout=15000)
   page.screenshot(path=str(out/'web-current.png'))
   page.get_by_role('button',name='Open target menu').click()
   page.get_by_role('menuitem',name='Runtime Manager').click()
   page.get_by_role('button',name='Stop Backend',exact=True).click();page.get_by_role('button',name='Confirm Stop',exact=True).click()
   page.get_by_role('button',name='Start Backend',exact=True).wait_for(timeout=15000)
   page.screenshot(path=str(out/'web-stopped.png'))
   page.get_by_role('button',name='Start Backend',exact=True).click();page.get_by_role('button',name='Stop Backend',exact=True).wait_for(timeout=15000)
   check('runtime start/stop through authenticated HTTP',True,True)
   page.get_by_role('button',name='Close Runtime Manager').click();page.get_by_role('button',name='Open target menu').click();page.get_by_role('menuitem',name='Report Issue',exact=True).click()
   page.get_by_role('button',name='Preview collection',exact=True).click();page.get_by_label('Collection preview').wait_for()
   page.screenshot(path=str(out/'web-report.png'));page.get_by_role('button',name='Discard unsent draft').click()
   check('real Report collection and cancellation',0,len(list((out/'data/private').glob('report-????????-*'))))
   page.get_by_role('button',name='Close report').click()
   page.reload();page.get_by_role('tab',name='Current',exact=True).wait_for(timeout=15000)
   check('reload preserves authenticated session',True,True)
   page.set_viewport_size({'width':412,'height':915});page.screenshot(path=str(out/'web-mobile.png'))
   check('no REST display polling',[],[u for u in api if '/snapshot' in u or '/runtime/status' in u])
   check('no browser script errors',[],errors);check('zero external requests',[],external)
   browser.close()
 except Exception as error:
  checks.append({'name':'browser workflow','status':'FAIL','actual':str(error)})
  raise
 finally:
  if process.poll() is None:process.stdin.write('\n');process.stdin.flush()
  process.wait(timeout=80)
  with socket.socket() as s:check('HUD listener released',True,s.connect_ex(('127.0.0.1',hud_port))!=0)
  with socket.socket() as s:check('Planner relay listener released',True,s.connect_ex(('127.0.0.1',planner_port))!=0)
  report={'status':'PASS' if checks and all(c['status']=='PASS' for c in checks) else 'FAIL','classification':'HTTP_BROWSER_SYNTHETIC_NATIVE_HOST','checks':checks,'windows':'NOT_RUN','android':'NOT_RUN','ci':'CI_NOT_CHECKED'}
  (out/'report.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args();run(args.output.resolve())
