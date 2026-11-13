import type { HudPlatform } from './index';
import { WebHudDataSource } from './web-data-source';

class WebFailure extends Error {
  constructor(readonly code:string,readonly state?:string){super(code);}
  toString(){return this.code;}
}
type Session = {subject:string;csrf:string;permissions:string[]};
export async function webPlatform(root:HTMLElement):Promise<HudPlatform>{
  document.documentElement.dataset.hudPlatform="web";
  let session:Session;
  async function load():Promise<Session>{
    const response=await fetch('/api/v1/session',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('AUTH_REQUIRED');return response.json();
  }
  try{session=await load();}catch{
    session=await new Promise<Session>(resolve=>{
      root.replaceChildren();
      const form=document.createElement('form'),title=document.createElement('h1'),input=document.createElement('input'),button=document.createElement('button'),status=document.createElement('p');
      title.textContent='Connect to D4Planner';input.type='password';input.autocomplete='off';input.placeholder='Access token';input.setAttribute('aria-label','Access token');input.required=true;button.textContent='Connect';status.setAttribute('role','alert');
      form.style.cssText='margin:24px;max-width:360px;font:16px system-ui;color:white';form.append(title,input,button,status);root.append(form);
      form.onsubmit=async event=>{
        event.preventDefault();button.disabled=true;status.textContent='Connecting…';
        try{
          const response=await fetch('/api/v1/session',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify({token:input.value})});
          input.value='';if(!response.ok)throw new Error('Connection refused. Check the token and host configuration.');
          resolve(await load());
        }catch(error){status.textContent=String(error);button.disabled=false;}
      };
    });
  }
  if(!session.subject || !session.csrf || !Array.isArray(session.permissions))throw new Error('INVALID_SESSION');
  const request=async<T>(path:string,body?:unknown,method=body===undefined?'GET':'POST'):Promise<T>=>{
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',headers:{'content-type':'application/json','x-hud-csrf':session.csrf},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(70000)});
    const value=response.status===204?null:await response.json();
    if(!response.ok){const e=value?.error;throw new WebFailure(typeof e?.code==='string' && /^[A-Z0-9_]{1,80}$/.test(e.code)?e.code:'WEB_REQUEST_FAILED',e?.state);}return value as T;
  };
  const endpoint=new URL('/api/v1/hud/stream',location.href);endpoint.protocol=location.protocol==='https:'?'wss:':'ws:';
  const source=new WebHudDataSource(endpoint.href,request);
  window.__D4PLANNER_HUD_DATA_SOURCE__=source;
  const reportKey=`d4planner.pendingReportId.web.${session.subject}`;
  const invoke:HudPlatform['invoke']=async<T>(command:string,args?:Parameters<HudPlatform['invoke']>[1])=>{
    const p=(args ?? {}) as Record<string,unknown>;
    switch(command){
      case 'get_backend_status':if(!source.runtime)throw new Error('RUNTIME_UNAVAILABLE');return source.runtime.backend as T;
      case 'backend_command':{
        const method=String(p.method);
        if(method==='runtime.status'){if(!source.runtime)throw new Error('RUNTIME_UNAVAILABLE');return source.runtime.runtime as T;}
        if(method==='target.list')return request<T>('/api/v1/targets');
        if(method==='target.select')return request<T>('/api/v1/targets/select',p.params);
        if(['capture.start','capture.stop','capture.restart'].includes(method))return request<T>(`/api/v1/runtime/capture/${method.split('.')[1]}`,{});
        throw new Error('COMMAND_NOT_AVAILABLE');
      }
      case 'start_backend':case 'stop_backend':case 'restart_backend':{
        const result=await request<{backend:unknown}>(`/api/v1/runtime/backend/${command.split('_')[0]}`,{});return result.backend as T;
      }
      case 'open_local_planner':{
        // Create synchronously in the user gesture, then navigate only after READY.
        const tab=window.open('about:blank','_blank');
        if(!tab)throw new Error('Allow pop-ups to open Local Planner.');
        tab.opener=null;
        try{
          const result=await request<{status:string;url:string}>('/api/v1/planner/open',{});
          const url=new URL(result.url);
          if(result.status!=='READY' || url.protocol!==location.protocol || url.hostname!==location.hostname || url.port===location.port || url.username || url.password || url.pathname!=='/')throw new Error('PLANNER_HEALTH_FAILED');
          tab.location.replace(url.href);return result as T;
        }catch(error){tab.close();throw error;}
      }
      case 'collect_issue_report':return request<T>('/api/v1/reports/preview',{selection:p.selection});
      case 'resume_issue_report':return request<T>(`/api/v1/reports/${encodeURIComponent(String(p.reportId))}`);
      case 'submit_issue_report':return request<T>(`/api/v1/reports/${encodeURIComponent(String(p.reportId))}/submit`,{description:p.description,consent:p.consent});
      case 'cancel_issue_report':{
        const id=localStorage.getItem(reportKey);if(!id)throw new Error('REPORT_NOT_COLLECTED');
        return request<T>(`/api/v1/reports/${encodeURIComponent(id)}`,undefined,'DELETE');
      }
      // Native diagnostics and window sizing have no browser equivalent.
      case 'runtime_log_event':case 'report_webview_diagnostic':case 'report_hud_pipeline':case 'set_overlay_extent':return undefined as T;
      default:throw new Error('COMMAND_NOT_AVAILABLE');
    }
  };
  return {kind:'web',nativeWindow:false,reportStorageKey:reportKey,invoke};
}
