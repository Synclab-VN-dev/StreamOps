"""S8 component-owned bounded writer. Only allowlisted diagnostics, never raw messages."""
from __future__ import annotations
import atexit, datetime, hashlib, json, os, queue, stat, threading
from pathlib import Path
from uuid import UUID

TAGS = {'logger','launcher','native','webview','websocket','hud','lifecycle','capture','target','sqlite','worker','browser','snapshot','session','api'}
EVENTS = {'SESSION_HEADER','START','READY','STOP','ERROR','RESTART','EXIT','CONNECT','DISCONNECT','RECONNECT','STATE_CHANGE','REQUEST','RESULT','TIMEOUT','QUARANTINE','CREATE','CLOSE','RECOVERY','UNAVAILABLE','LOG_TRIMMED','LOG_DROPPED','LEGACY_FROZEN','DEBUG_PROBE'}
CODES = {'INTERNAL','TIMEOUT','TARGET_INVALID','TARGET_CHANGED','SNAPSHOT_MISMATCH','UNAVAILABLE','CLEANUP_PENDING','IO_ERROR','STARTUP_FAILED','INVALID_CONFIG','UNKNOWN'}
FIELDS = {'durationMs','bytes','count','dropped','trimmed','exitCode','revision','queueDepth','active','ok','retryable'}
LIMITS = {'FE':5_000_000,'BE':10_000_000,'RULEKIT':15_000_000}

def safe(path: Path) -> bool:
    for part in (path, *path.parents):
        try:
            st = part.lstat()
            if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
                return False
        except FileNotFoundError:
            continue
    return True

def sanitize(fields):
    out = {k:v for k,v in fields.items() if k in FIELDS and isinstance(v,(bool,int,float)) and abs(v)<=1e15}
    if isinstance(fields.get('errorCode'),str) and fields['errorCode'] in CODES: out['errorCode']=fields['errorCode']
    try:
        value=fields.get('correlationId')
        if isinstance(value,str): UUID(value);out['correlationId']=value
    except ValueError: pass
    return out

class Sink:
    def __init__(self, directory, run_id, component='BE', generation=0, policy=None):
        UUID(run_id)
        self.directory=Path(directory)
        if not self.directory.is_absolute() or not safe(self.directory): raise ValueError('LOG_PATH_UNSAFE')
        self.run_id=run_id; self.component=component; self.generation=generation; self.cap=LIMITS[component]
        self.path=self.directory / {'FE':'fe.log','BE':'be.log','RULEKIT':'rulekit.log'}[component]
        self.temp=self.directory.parent / '.control' / f'{run_id}-{component}.tmp'
        self.policy=policy if isinstance(policy,dict) else {}; self.dropped=0; self.trimmed=0
    def record(self, level, tag, event, fields):
        clean=sanitize(fields); correlation=clean.pop('correlationId',None)
        record = dict(schemaVersion='d4planner-runtime-log/v1',ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds'),level=level,component=self.component,tag=tag,event=event,runId=self.run_id,pid=os.getpid(),generation=self.generation,fields=clean)
        if correlation: record["correlationId"]=hashlib.sha256(correlation.encode()).hexdigest()
        return record
    @staticmethod
    def encode(r): return (json.dumps(r,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
    def emit(self,level,tag,event,**fields):
        try:
            if level not in {'DEBUG','INFO','WARN','ERROR'} or tag not in TAGS or event not in EVENTS:
                self.dropped+=1; return
            levels=('DEBUG','INFO','WARN','ERROR')
            component=self.policy.get(self.component,{})
            if not isinstance(component,dict): component={}
            minimum=component.get(tag,component.get('*','INFO'))
            threshold=levels.index(minimum) if minimum in levels else 1
            if levels.index(level)<threshold:return
            b=self.encode(self.record(level,tag,event,fields))
            if len(b)>4096 or not safe(self.path) or not safe(self.temp) or not self.path.is_file() or (self.temp.exists() and not self.temp.is_file()): raise ValueError('LOG_UNSAFE')
            length=self.path.stat().st_size
            if length>self.cap: raise ValueError('LOG_CAP')
            with self.path.open('rb') as f:
                if length: f.seek(-1,2)
                broken=bool(length and f.read(1)!=b'\n')
            if length+len(b)>self.cap or broken:
                raw=self.path.read_bytes(); lines=[]
                for line in raw.splitlines(keepends=True):
                    if not line.endswith(b'\n'): continue
                    try: json.loads(line)
                    except (ValueError,UnicodeError): continue
                    lines.append(line)
                keep=int(max(0,len(lines)-1)*.7); start=max(1,len(lines)-keep)
                self.trimmed+=start-1
                retained=lines[start:]
                header=b''.join(lines[:1])
                size=sum(map(len,retained))
                while retained and len(header)+size+len(b)+1024>self.cap:
                    size-=len(retained.pop(0));self.trimmed+=1
                marker=self.encode(self.record('WARN','logger','LOG_TRIMMED',dict(trimmed=self.trimmed,dropped=self.dropped)))
                out=header+b''.join(retained)+marker
                if len(out)+len(b)>self.cap: raise ValueError('LOG_CAP')
                fd=os.open(self.temp,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
                with os.fdopen(fd,'wb') as f: f.write(out); f.flush(); os.fsync(f.fileno())
                os.replace(self.temp,self.path)
            with self.path.open('ab') as f: f.write(b)
        except (OSError,ValueError,TypeError,OverflowError): self.dropped+=1

class Logger:
    def __init__(self,sink):
        self.sink=sink; self.queue=queue.Queue(256); self.dropped=0; self.closed=False
        self.thread=threading.Thread(target=self._write,daemon=True,name='d4-log-writer');self.thread.start()
    def emit(self,level,tag,event,**fields):
        if self.closed:return
        if level not in {'DEBUG','INFO','WARN','ERROR'} or tag not in TAGS or event not in EVENTS:self.dropped+=1;return
        try:self.queue.put_nowait((level,tag,event,sanitize(fields)))
        except queue.Full:self.dropped+=1
    def _write(self):
        while True:
            row=self.queue.get()
            try:
                if row is None:return
                if self.dropped:self.sink.emit('WARN','logger','LOG_DROPPED',dropped=self.dropped);self.dropped=0
                l,t,e,f=row;self.sink.emit(l,t,e,**f)
            finally:self.queue.task_done()
    def close(self):
        self.closed=True
        try:self.queue.put(None,timeout=.1)
        except queue.Full:return
        self.thread.join(timeout=.5)

_logger=None

def configure(generation=0):
    global _logger
    if _logger is not None: _logger.sink.generation=generation;return
    try:_logger=Logger(Sink(os.environ['D4_LOG_DIR'],os.environ['D4_LOG_RUN_ID'],'BE',generation,json.loads(os.environ.get('D4_LOG_POLICY','{}'))));atexit.register(_logger.close)
    except (KeyError,ValueError,OSError):pass

def emit(level,tag,event,**fields):
    if _logger is not None:_logger.emit(level,tag,event,**fields)
