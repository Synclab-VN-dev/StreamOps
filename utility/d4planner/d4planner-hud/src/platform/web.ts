import type { HudPlatform } from './index';
import { WebHudDataSource } from './web-data-source';
import { BrowserSession } from './web-session';

class WebFailure extends Error {
  constructor(readonly code:string,readonly state?:string){super(code);}
  toString(){return this.code;}
}
export async function webPlatform(_root:HTMLElement):Promise<HudPlatform>{
  document.documentElement.dataset.hudPlatform="web";
  const authentication=new BrowserSession();
  const session=await authentication.ensure();
  const request=async<T>(path:string,body?:unknown,method=body===undefined?'GET':'POST'):Promise<T>=>{
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',headers:{'content-type':'application/json','x-hud-csrf':authentication.current!.csrf},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(70000)});
    if(response.status===401){
      await authentication.ensure();
      // A timed-out or rejected mutation must never be replayed implicitly.
      throw new WebFailure('SESSION_REAUTHENTICATED_RETRY_REQUIRED');
    }
    const value=response.status===204?null:await response.json();
    if(!response.ok){const e=value?.error;throw new WebFailure(typeof e?.code==='string' && /^[A-Z0-9_]{1,80}$/.test(e.code)?e.code:'WEB_REQUEST_FAILED',e?.state);}return value as T;
  };
  const endpoint=new URL('/api/v1/hud/stream',location.href);endpoint.protocol=location.protocol==='https:'?'wss:':'ws:';
  const source=new WebHudDataSource(endpoint.href,request,undefined,()=>authentication.ensure().then(()=>{}));
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
