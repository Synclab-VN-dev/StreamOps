import { useCallback, useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import './RuntimeManager.css';

type Service = 'backend' | 'capture';
type Operation = 'start' | 'stop' | 'restart';
type Capture = {speechEvents:number|null; dataRootReceipt:string;state:string; detail:string; pid:number|null; manualPause:boolean; mode:string;
  controllerProfile:string; lastEventAt:string|null; inputObserved:boolean;
  dependencies:Record<string,string>; observedAt:string|null};
type Runtime = {pid:number; uptimeSeconds:number; dataRoot:string; webSocket:string|null; capture:Capture|null};
type Status = {state:string; ready?:{childInstanceId:string;generation:number}};
function Metric({title,value}:{title:string;value:unknown}) {
  return <div><dt>{title}</dt><dd>{value === null || value === undefined || value === '' ? 'Unavailable' : String(value)}</dd></div>;
}
function Badge({state}:{state:string}) { return <span className="runtime-badge" data-state={state}>{state}</span>; }

export function RuntimeManager({onClose,onOpenLogs,onChanged}:{onClose:()=>void;onOpenLogs:()=>void;onChanged:()=>void}) {
  const [backend,setBackend] = useState<Status|null>(null);
  const [runtime,setRuntime] = useState<Runtime|null>(null);
  const [error,setError] = useState<string|null>(null);
  const [busy,setBusy] = useState(false);
  const [pending,setPending] = useState<{service:Service;operation:Operation}|null>(null);
  const [activity,setActivity] = useState('No runtime action in this session.');
  const mounted = useRef(true), operating = useRef(false), reading = useRef(false);
  const dialog = useRef<HTMLElement>(null);
  const refresh = useCallback(async () => {
    if (reading.current || operating.current) return;
    reading.current = true;
    try {
      const status = await invoke<Status>('get_backend_status');
      if (mounted.current && !operating.current) setBackend(status);
      try {
        const value = status.state === 'READY'
          ? await invoke<Runtime>('backend_command',{method:'runtime.status',params:{}}) : null;
        if (mounted.current && !operating.current) {setRuntime(value);setError(null);}
      } catch {
        // Keep native lifecycle controls available even if business/status IPC fails.
        if (mounted.current && !operating.current) {setRuntime(null);setError('Capture status unavailable. Backend controls remain available; collect logs for details.');}
      }
    } catch {
      if (mounted.current && !operating.current) {setRuntime(null);setBackend(null);setError('Runtime status unavailable. Open logs for details.');}
    } finally {reading.current = false;}
  },[]);
  useEffect(() => {
    mounted.current = true; void refresh();
    const timer = setInterval(() => void refresh(),2000);
    dialog.current?.focus();
    return () => {mounted.current = false;clearInterval(timer);};
  },[refresh]);
  useEffect(() => {
    const key = (event:KeyboardEvent) => {
      if(event.key === 'Escape') {event.preventDefault(); if(!operating.current) {if(pending) setPending(null);else onClose();}}
      if(event.key === 'Tab') {
        const scope = dialog.current?.querySelector('[role="alertdialog"]') ?? dialog.current;
        const items = Array.from(scope?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
        if(!items.length) return;
        const index = items.indexOf(document.activeElement as HTMLButtonElement);
        if(event.shiftKey && index <= 0) {event.preventDefault();items.at(-1)?.focus();}
        else if(!event.shiftKey && (index < 0 || index === items.length-1)) {event.preventDefault();items[0].focus();}
      }
    };
    document.addEventListener('keydown',key);return () => document.removeEventListener('keydown',key);
  },[pending,onClose]);
  async function apply(service:Service, operation:Operation) {
    if(operating.current) return;
    operating.current = true;setBusy(true);setPending(null);setError(null);
    try {
      if(service === 'backend') await invoke(`${operation}_backend`);
      else await invoke('backend_command',{method:`capture.${operation}`,params:{}});
      if(mounted.current) setActivity(`${service === 'backend' ? 'Backend' : 'Capture'} ${operation} request completed. Status below reflects the runtime.`);
      onChanged();
    } catch {
      if(mounted.current) setActivity('Command failed. Check runtime status and collect logs before retrying.');
    } finally {
      operating.current = false;
      if(mounted.current) {setBusy(false);void refresh();}
    }
  }
  function request(service:Service,operation:Operation) {
    if(operation === 'start') void apply(service,operation);else setPending({service,operation});
  }
  const online = backend?.state === 'READY';
  const capture = runtime?.capture;
  const controllable = online && !!capture;
  const captureLive = capture?.pid != null;
  const backendLabel = online ? 'RUNNING' : backend?.state ?? 'UNKNOWN';
  return <div className="runtime-backdrop" onMouseDown={event => {if(event.target === event.currentTarget && !busy) onClose();}}>
    <section className="runtime-manager" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Runtime Manager" aria-busy={busy}>
      <header><div className="runtime-title"><span aria-hidden="true">⌁</span><div><h2>Runtime Manager</h2><p>D4Planner HUD · Process &amp; Capture Control</p></div></div>
        <button aria-label="Close Runtime Manager" disabled={busy} onClick={onClose}>×</button></header>
      <div className="runtime-body">
        <div className="runtime-notice">Only D4Planner-owned Backend and Capture are controlled here. NVDA, Steam and Diablo IV remain running.</div>
        {error && <p role="alert" className="runtime-warning">{error}</p>}
        <div className="runtime-grid">
          <article className="runtime-card"><div className="runtime-card-heading"><h3>Backend Service</h3><Badge state={backendLabel}/></div><p>Owned by HUD native</p>
            <dl><Metric title="Process ID" value={runtime?.pid}/><Metric title="Uptime" value={runtime && `${runtime.uptimeSeconds}s`}/><Metric title="WebSocket" value={runtime?.webSocket}/><Metric title="Owner" value="HUD native"/><Metric title="DataRoot" value={runtime?.dataRoot}/><Metric title="Last error" value={error ?? (backend?.state === 'FAILED' ? 'Backend failed — collect logs' : 'None observed')}/></dl>
            <div className="runtime-actions">{online ? <><button disabled={busy || !!pending} onClick={()=>request('backend','restart')}>Restart Backend</button><button disabled={busy || !!pending} onClick={()=>request('backend','stop')}>Stop Backend</button></> : <button className="primary" disabled={busy || !!pending || !backend} onClick={()=>request('backend','start')}>Start Backend</button>}</div>
          </article>
          <article className="runtime-card"><div className="runtime-card-heading"><h3>Capture Daemon</h3><Badge state={capture?.state ?? (backend?.state === 'STOPPED' ? 'STOPPED' : 'UNKNOWN')}/></div><p>Speech and controller input</p>
            <dl><Metric title="Process ID" value={capture?.pid}/><Metric title="Capture mode" value={capture?.mode}/><Metric title="Controller profile" value={capture?.controllerProfile}/><Metric title="Speech events" value={capture?.speechEvents}/><Metric title="Last capture event" value={capture?.lastEventAt}/><Metric title="Input markers" value={capture ? capture.inputObserved ? 'OBSERVED · not physically verified' : 'NOT OBSERVED' : 'UNKNOWN'}/><Metric title="Status detail" value={capture?.detail}/></dl>
            {capture?.manualPause && <p className="runtime-warning">AUTO-START PAUSED · Use Start Capture to resume.</p>}
            <div className="runtime-actions">
              {!captureLive && <button className="primary" disabled={busy || !!pending || !controllable} onClick={()=>request('capture','start')}>Start Capture</button>}
              {(captureLive || capture?.state === 'BLOCKED') && <button disabled={busy || !!pending || !controllable} onClick={()=>request('capture','restart')}>{capture?.state === 'BLOCKED' ? 'Retry' : 'Restart Capture'}</button>}
              {controllable && !capture?.manualPause && <button disabled={busy || !!pending || !controllable} onClick={()=>request('capture','stop')}>Stop Capture</button>}
            </div>
            <p>RUNNING does not prove character identity, equipment projection, or controller input.</p>
          </article>
          <section className="runtime-card"><h3>Dependencies</h3>{[['nvda','NVDA'],['tolk','Tolk'],['game','Diablo IV']].map(([key,label])=><div className="runtime-dependency" key={key}><b>{label}</b><span>{capture?.dependencies[key] ?? 'UNKNOWN'}</span></div>)}<div className="runtime-dependency"><b>Controller input</b><span>{capture?.inputObserved ? 'OBSERVED' : 'UNVERIFIED'}</span></div><p>Last runtime observation: {capture?.observedAt ?? 'Unavailable'}</p></section>
          <section className="runtime-card"><h3>Diagnostics</h3><div className="runtime-activity" role="status"><b>Recent activity</b><p>{busy ? 'Applying request…' : activity}</p><p>DataRoot receipt: {capture?.dataRootReceipt ?? 'UNAVAILABLE'}</p></div><button className="runtime-logs" disabled={busy} onClick={onOpenLogs}>View / Collect Logs</button></section>
        </div>
      </div>
      {pending && <div className="runtime-confirm-backdrop"><div role="alertdialog" aria-modal="true" aria-labelledby="runtime-confirm"><h3 id="runtime-confirm">{pending.operation === 'stop' ? 'Stop' : 'Restart'} {pending.service === 'backend' ? 'Backend Service' : 'Capture Daemon'}?</h3><p>{pending.service === 'backend' ? 'The owned Capture child will also stop. External NVDA, Steam and Diablo IV remain running.' : 'Speech and input capture will stop. NVDA and Diablo IV remain running.'}</p>{pending.service === 'capture' && pending.operation === 'stop' && <p className="runtime-warning">Auto-start stays paused across Backend restarts until Start Capture.</p>}<div className="runtime-actions"><button onClick={()=>setPending(null)}>Cancel</button><button className="primary" onClick={()=>void apply(pending.service,pending.operation)}>Confirm {pending.operation === 'stop' ? 'Stop' : 'Restart'}</button></div></div></div>}
    </section>
  </div>;
}
