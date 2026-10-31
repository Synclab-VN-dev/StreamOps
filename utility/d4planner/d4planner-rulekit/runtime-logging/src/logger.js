'use strict';
// Single writer thread; producer never blocks application IPC on filesystem I/O.
const {Worker,isMainThread,parentPort,workerData}=require('node:worker_threads');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const CODES=new Set('INTERNAL TIMEOUT TARGET_INVALID TARGET_CHANGED SNAPSHOT_MISMATCH UNAVAILABLE CLEANUP_PENDING IO_ERROR STARTUP_FAILED INVALID_CONFIG UNKNOWN'.split(' '));
const TAGS=new Set('logger launcher native webview websocket hud lifecycle capture target sqlite worker browser snapshot session api'.split(' '));
const EVENTS=new Set('SESSION_HEADER START READY STOP ERROR RESTART EXIT CONNECT DISCONNECT RECONNECT STATE_CHANGE REQUEST RESULT TIMEOUT QUARANTINE CREATE CLOSE RECOVERY UNAVAILABLE LOG_TRIMMED LOG_DROPPED LEGACY_FROZEN DEBUG_PROBE'.split(' '));
const KEYS=new Set('durationMs bytes count dropped trimmed exitCode revision queueDepth active ok retryable'.split(' '));
function clean(fields){const out=Object.fromEntries(Object.entries(fields||{}).filter(([k,v])=>KEYS.has(k)&&(typeof v==='boolean'||typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e15)));if(CODES.has(fields?.errorCode))out.errorCode=fields.errorCode;if(typeof fields?.correlationId==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(fields.correlationId))out.correlationId=fields.correlationId;return out;}
function safe(p){for(let q=p;;q=path.dirname(q)){try{if(fs.lstatSync(q).isSymbolicLink())return false;}catch(e){if(e.code!=='ENOENT')return false;}if(path.dirname(q)===q)return true;}}
class Sink{
 constructor(dir,runId,generation=0,policy={}){if(!path.isAbsolute(dir)||!safe(dir)||!/^[a-f0-9-]{36}$/.test(runId))throw Error('LOG_UNSAFE');Object.assign(this,{dir,runId,generation,policy,cap:15000000,dropped:0,trimmed:0});this.file=path.join(dir,'rulekit.log');this.temp=path.join(path.dirname(dir),'.control',`${runId}-RULEKIT.tmp`);}
 record(level,tag,event,fields){const f=clean(fields),correlation=f.correlationId;delete f.correlationId;return {...(correlation?{correlationId:crypto.createHash("sha256").update(correlation).digest("hex")}:{}),schemaVersion:'d4planner-runtime-log/v1',ts:new Date().toISOString(),level,component:'RULEKIT',tag,event,runId:this.runId,pid:process.pid,generation:this.generation,fields:f};}
 emit(level,tag,event,fields={}){try{
 if(!['DEBUG','INFO','WARN','ERROR'].includes(level)||!TAGS.has(tag)||!EVENTS.has(event)){this.dropped++;return;}
 const levels=['DEBUG','INFO','WARN','ERROR'];const minimum=this.policy?.RULEKIT?.[tag]??this.policy?.RULEKIT?.['*']??'INFO';const threshold=levels.includes(minimum)?levels.indexOf(minimum):1;if(event!=='LOG_DROPPED'&&levels.indexOf(level)<threshold)return;
 const b=Buffer.from(JSON.stringify(this.record(level,tag,event,fields))+'\n');if(b.length>4096||!safe(this.file)||!safe(this.temp)||!fs.statSync(this.file).isFile()||(fs.existsSync(this.temp)&&!fs.statSync(this.temp).isFile()))throw Error('LOG_UNSAFE');
 const n=fs.statSync(this.file).size;if(n>this.cap)throw Error('LOG_CAP');const fd=fs.openSync(this.file,'r');const end=Buffer.alloc(1);try{if(n)fs.readSync(fd,end,0,1,n-1);}finally{fs.closeSync(fd);}
 if(n+b.length>this.cap||n&&end[0]!==10){const raw=fs.readFileSync(this.file,'utf8');const lines=raw.split('\n').slice(0,-1).filter(l=>{try{JSON.parse(l);return true;}catch{return false;}});const keep=Math.floor(Math.max(0,lines.length-1)*.7),start=Math.max(1,lines.length-keep);let nextTrimmed=this.trimmed+start-1;const retained=lines.slice(start);let size=retained.reduce((n,l)=>n+Buffer.byteLength(l)+1,0);const header=lines.slice(0,1);while(retained.length&&Buffer.byteLength(header.join('\n'))+size+b.length+1024>this.cap){size-=Buffer.byteLength(retained.shift())+1;nextTrimmed++;}const out=Buffer.from([...header,...retained,JSON.stringify(this.record('WARN','logger','LOG_TRIMMED',{trimmed:nextTrimmed}))].join('\n')+'\n');if(out.length+b.length>this.cap)throw Error('LOG_CAP');const t=fs.openSync(this.temp,'w',0o600);try{fs.writeFileSync(t,out);fs.fsyncSync(t);}finally{fs.closeSync(t);}fs.renameSync(this.temp,this.file);this.trimmed=nextTrimmed;}
 fs.appendFileSync(this.file,b);
 if(this.dropped&&event!=='LOG_DROPPED'){const lost=this.dropped;this.dropped=0;this.emit('WARN','logger','LOG_DROPPED',{dropped:lost});}
 }catch{this.dropped+=event==='LOG_DROPPED'?Math.max(1,Number(fields.dropped)||1):1;}}
}
if(!isMainThread&&workerData?.d4log){let sink;try{sink=new Sink(workerData.dir,workerData.runId,workerData.generation,workerData.policy);}catch{}parentPort.on('message',m=>{if(m.close){parentPort.close();return;}sink?.emit(m.level,m.tag,m.event,m.fields);parentPort.postMessage({ack:true,dropped:sink?.dropped||0});});}
let logger;
function configure(){if(logger)return logger;let pending=0,dropped=0,worker;try{if(!process.env.D4_LOG_DIR)return;worker=new Worker(__filename,{workerData:{d4log:true,dir:process.env.D4_LOG_DIR,runId:process.env.D4_LOG_RUN_ID,generation:Number(process.env.D4_RULEKIT_WORKER_GENERATION)||0,policy:JSON.parse(process.env.D4_LOG_POLICY||'{}')}});worker.unref();worker.on('error',()=>{worker=null;});worker.on('message',()=>{pending=Math.max(0,pending-1);});}catch{return;}
 logger={emit(level,tag,event,fields={}){if(!worker)return;if(!TAGS.has(tag)||!EVENTS.has(event)||pending>=256){dropped++;return;}if(dropped&&pending<255){worker.postMessage({level:'WARN',tag:'logger',event:'LOG_DROPPED',fields:{dropped}});pending++;dropped=0;}worker.postMessage({level,tag,event,fields:clean(fields)});pending++;},async close(){if(!worker)return;const w=worker;worker=null;await Promise.race([new Promise(resolve=>{w.once('exit',resolve);w.postMessage({close:true});}),new Promise(resolve=>setTimeout(resolve,500))]);await w.terminate();}};return logger;}
function emit(...args){configure()?.emit(...args);}
// Composition-owned adapter: browser infrastructure only knows its neutral callback.
function browserEvent(record){
 const events={request:['DEBUG','REQUEST'],starting:['INFO','START'],started:['INFO','READY'],stopping:['INFO','STOP'],stopped:['INFO','CLOSE'],error:['ERROR','ERROR'],quarantine:['WARN','QUARANTINE'],disconnected:['WARN','DISCONNECT'],acquired:['DEBUG','CREATE'],released:['DEBUG','CLOSE'],queued:['DEBUG','STATE_CHANGE'],cleanup_failed:['ERROR','ERROR'],recovery_failed:['ERROR','ERROR']};
 const mapped=events[record?.event];if(mapped)emit(mapped[0],'browser',mapped[1],{queueDepth:record.pendingQueue,errorCode:record.code});
}
module.exports={Sink,clean,configure,emit,browserEvent};
