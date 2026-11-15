#!/usr/bin/env python3
"""Exercise an isolated Windows HUD + Edge via explicitly enabled CDP.
Never enable remote debugging on the owner's normal runtime. Evidence is private.
"""
import argparse, pathlib, json
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--native-cdp',required=True)
parser.add_argument('--browser-cdp',required=True)
parser.add_argument('--url',required=True)
parser.add_argument('--token-file',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
from playwright.sync_api import sync_playwright
out=args.output;out.mkdir(parents=True,exist_ok=True);token=args.token_file.read_text().strip()
with sync_playwright() as p:
 pc=p.chromium.connect_over_cdp(args.native_cdp);edge=p.chromium.connect_over_cdp(args.browser_cdp)
 native=pc.contexts[0].pages[0];web=edge.contexts[0].pages[0]
 frames=[]
 web.on('websocket',lambda ws:ws.on('framereceived',lambda data:frames.append(json.loads(data))))
 web.goto(args.url);
 if web.get_by_label('Access token').count():
  web.get_by_label('Access token').fill(token);web.get_by_role('button',name='Connect',exact=True).click()
 web.get_by_role('tab',name='Current',exact=True).wait_for()
 errors=[];web.on('pageerror',lambda e:errors.append(str(e)))
 result=[]
 def req(action):
  return web.evaluate('''async action=>{const s=await(await fetch('/api/v1/session')).json();const r=await fetch('/api/v1/runtime/backend/'+action,{method:'POST',headers:{'x-hud-csrf':s.csrf}});return {status:r.status,body:await r.json()}}''',action)
 for action,state in [('stop','EXITED'),('start','READY'),('restart','READY')]:
  r=req(action);assert r['status']==200,r;assert r['body']['backend']['state']==state,r
  n=native.evaluate("()=>window.__TAURI_INTERNALS__.invoke('get_backend_status')");assert n['state']==state,n
  result.append({'action':action,'web':state,'native':n['state'],'status':'PASS'})
 web.get_by_role('button',name='Open target menu').click();web.get_by_role('menuitem',name='Runtime Manager').click();web.get_by_role('button',name='Stop Backend',exact=True).wait_for(timeout=15000);web.screenshot(path=str(out/'windows-web-runtime.png'))
 web.get_by_role('button',name='Close Runtime Manager').click();web.get_by_role('button',name='Open target menu').click();web.get_by_role('menuitem',name='Report Issue',exact=True).click();web.get_by_role('button',name='Preview collection',exact=True).click();web.get_by_label('Collection preview').wait_for();web.screenshot(path=str(out/'windows-web-report.png'));web.get_by_role('button',name='Discard unsent draft').click();web.get_by_role('button',name='Close report').click()
 web.wait_for_timeout(2500)
 assert any(f.get('connected') and f.get('snapshot',{}).get('hudRevision',-1)>=0 for f in frames), 'No connected full projection received'
 projection=native.evaluate("()=>window.__TAURI_INTERNALS__.invoke('read_hud_database')")
 assert frames[-1]['snapshot']['dbId']==projection['dbId']
 assert frames[-1]['snapshot']['hudRevision']==projection['hudRevision']
 assert not errors,errors
 (out/'workflow.json').write_text(json.dumps({'classification':'WINDOWS_NATIVE_TAURI_WITH_REAL_BE','checks':result,'reportPreviewCancel':'PASS','fullWebSocketProjection':'PASS','nativeProjectionEquality':'PASS','scriptErrors':errors,'browser':edge.version},indent=2))
 print('WINDOWS_NATIVE_WEB_CONTROL_PASS');edge.close();pc.close()
