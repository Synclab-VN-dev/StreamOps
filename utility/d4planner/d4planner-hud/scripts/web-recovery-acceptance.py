#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
from pathlib import Path
import json,uuid,argparse
parser=argparse.ArgumentParser(description='Run F1/F2/F3 against an isolated real HTTP HUD in Windows Edge via CDP.')
parser.add_argument('--browser-cdp',required=True);parser.add_argument('--url',required=True)
parser.add_argument('--token-file',type=Path,required=True);parser.add_argument('--subject',required=True)
parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
out=args.output;out.mkdir(parents=True,exist_ok=True)
token=args.token_file.read_text().strip();url=args.url
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp(args.browser_cdp);c=b.contexts[0];a=c.pages[0];other=b.new_context();z=other.new_page()
 def wait_js(page,expression):
  for _ in range(250):
   if page.evaluate('()=>('+expression+')'):return
   page.wait_for_timeout(100)
  raise AssertionError('Browser state did not converge')
 def login(page):
  page.goto(url)
  page.locator('[aria-label="Access token"], [role="tab"]').first.wait_for()
  if page.get_by_label('Access token').count():page.get_by_label('Access token').fill(token);page.get_by_role('button',name='Connect',exact=True).click()
  page.get_by_role('tab',name='Current',exact=True).wait_for()
 def call(page,path,body=None,method=None):
  return page.evaluate('''async({path,body,method})=>{const s=await(await fetch('/api/v1/session')).json();const r=await fetch(path,{method:method||(body?'POST':'GET'),headers:{'content-type':'application/json','x-hud-csrf':s.csrf},body:body?JSON.stringify(body):undefined});return {status:r.status,data:await r.json()}}''',{'path':path,'body':body,'method':method})
 login(a);login(z)
 selection={'selection':{'fe':False,'be':False,'rulekit':False,'evidence':False,'evidenceConsent':False}}
 first=call(a,'/api/v1/reports/preview',selection);second=call(z,'/api/v1/reports/preview',selection)
 assert first['status']==second['status']==200
 rid=first['data']['reportId'];assert rid==second['data']['reportId'];assert call(a,'/api/v1/reports/'+rid)['data']['reportId']==rid
 assert call(z,'/api/v1/reports/'+rid,method='DELETE')['status']==200
 assert call(a,'/api/v1/reports/'+rid)['data']['status']=='DISCARDED'
 a.evaluate("({key,id})=>localStorage.setItem(key,id)",{'key':'d4planner.pendingReportId.web.'+args.subject,'id':rid})
 a.get_by_role('button',name='Open target menu').click();a.get_by_role('menuitem',name='Report Issue',exact=True).click()
 a.get_by_role('button',name='Preview collection').wait_for();wait_js(a,"!document.querySelector('.report-panel button[disabled]') || !document.querySelector('.report-panel').textContent.includes('Retry recovery')")
 assert a.get_by_role('button',name='Preview collection').is_enabled()
 title=a.get_by_label('Title',exact=True).element_handle();title.fill('Synthetic unsent description')
 c.clear_cookies();a.evaluate('window.__D4PLANNER_HUD_DATA_SOURCE__.socket.close()')
 a.get_by_label('Access token').wait_for(timeout=25000)
 assert title.evaluate("el=>el.isConnected && el.value==='Synthetic unsent description'")
 a.get_by_label('Access token').fill('wrong-token');a.get_by_role('button',name='Connect',exact=True).click();a.get_by_text('Connection refused.',exact=False).wait_for()
 a.get_by_label('Access token').fill(token);a.get_by_role('button',name='Connect',exact=True).click()
 wait_js(a,"!document.querySelector('dialog') && window.__D4PLANNER_HUD_DATA_SOURCE__.runtime?.backend?.state==='READY'")
 assert title.evaluate("el=>el.isConnected && el.value==='Synthetic unsent description'")
 a.screenshot(path=str(out/'reauth-preserved-form.png'))
 a.get_by_role('button',name='Close report').click();unknown=str(uuid.uuid4());a.evaluate("({key,id})=>localStorage.setItem(key,id)",{'key':'d4planner.pendingReportId.web.'+args.subject,'id':unknown})
 a.get_by_role('button',name='Open target menu').click();a.get_by_role('menuitem',name='Report Issue',exact=True).click()
 a.get_by_role('button',name='Retry recovery').wait_for();a.get_by_role('button',name='Retry recovery').click()
 assert a.get_by_role('button',name='Preview collection').is_disabled()
 assert a.evaluate("key=>localStorage.getItem(key)",'d4planner.pendingReportId.web.'+args.subject)==unknown
 a.get_by_role('button',name='Close report').click();a.evaluate("key=>localStorage.removeItem(key)",'d4planner.pendingReportId.web.'+args.subject) # test-only unknown synthetic reference
 (out/'report.json').write_text(json.dumps({'classification':'REAL_WINDOWS_HTTP_BROWSER','F1_same_subject_two_contexts':'PASS','F2_confirmed_discard_unlock':'PASS','F2_unknown_retained_retry':'PASS','F3_session_cookie_loss_login_resync_preserves_form':'PASS','serverExpiry':'separate auth unit test; browser removes cookie, not a shortened production TTL','browser':b.version},indent=2))
 other.close();b.close();print('F1_F2_F3_WINDOWS_PASS')
