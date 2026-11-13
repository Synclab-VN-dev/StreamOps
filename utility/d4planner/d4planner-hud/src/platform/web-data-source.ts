import validateHudSchema from '../hud-validator.generated';
import type { HudDataEvent, IHudDataSource, WebSocketLike } from '../hud-data-source';
import type { HudSnapshot, SelectionResult, TargetListEntry } from '../hud-model';

type Request = <T>(path: string, body?: unknown) => Promise<T>;
type Projection = {schemaVersion:string;dbId:string;epoch:string;hudRevision:number;hud:HudSnapshot};
export type WebRuntime = {backend:{state:string;ready?:{childInstanceId:string;generation:number}};runtime:unknown};
export class WebHudDataSource implements IHudDataSource {
  private listener:((event:HudDataEvent)=>void)|null=null;
  private socket:WebSocketLike|null=null;
  private timer:ReturnType<typeof setTimeout>|null=null;
  private checkpoint:{dbId:string;epoch:string;revision:number}|null=null;
  private sequence=-1;
  private epoch=0;
  private retry=0;
  private targets:TargetListEntry[]=[];
  private listRevision:number|null=null;
  runtime:WebRuntime|null=null;
  constructor(private readonly endpoint:string,private readonly request:Request,
    private readonly socketFactory:(url:string)=>WebSocketLike=url=>new WebSocket(url) as unknown as WebSocketLike) {}
  async connect(listener:(event:HudDataEvent)=>void):Promise<()=>void>{
    if(this.listener) throw new Error('ALREADY_CONNECTED');
    this.listener=listener;this.open(++this.epoch);
    return ()=>{++this.epoch;this.listener=null;this.runtime=null;if(this.timer)clearTimeout(this.timer);const socket=this.socket;this.socket=null;socket?.close();};
  }
  private offline(reason:string){
    this.runtime=null;this.targets=[];this.listRevision=null;
    this.listener?.({type:'CONNECTION',state:'DISCONNECTED',reason});
    this.listener?.({type:'TARGET_LIST_STATE',status:'IDLE',error:null});
  }
  private open(epoch:number){
    if(!this.listener || epoch!==this.epoch)return;
    const socket=this.socketFactory(this.endpoint);this.socket=socket;this.sequence=-1;
    socket.onmessage=event=>{
      if(this.socket!==socket || epoch!==this.epoch)return;
      try{this.receive(JSON.parse(event.data));this.retry=0;}
      catch{this.offline('INVALID_WEB_MODEL');this.listener?.({type:'ASSESSMENT_INVALIDATED'});socket.close();}
    };
    socket.onclose=()=>{
      if(this.socket!==socket || epoch!==this.epoch)return;
      this.socket=null;this.offline('OFFLINE');
      this.timer=setTimeout(()=>this.open(epoch),Math.min(1000*2**this.retry++,15000));
    };
  }
  private receive(message:{schemaVersion:string;type:string;sequence:number;connected:boolean;snapshot:Projection|null;runtime:WebRuntime}){
    if(message.schemaVersion!=='d4planner-hud-web/v1' || message.type!=='state' || !Number.isSafeInteger(message.sequence) || message.sequence<0 || typeof message.connected!=='boolean')throw new Error('INVALID_ENVELOPE');
    if(message.sequence<this.sequence)throw new Error('SEQUENCE_REGRESSION');
    if(message.sequence===this.sequence)return;
    this.sequence=message.sequence;this.runtime=message.runtime;
    this.listener?.({type:'CONNECTION',state:message.connected?'CONNECTED':'DISCONNECTED'});
    const p=message.snapshot;
    if(!p){this.checkpoint=null;this.listener?.({type:'DATABASE_RESET'});return;}
    if(p.schemaVersion!=='d4planner-hud-db/v1' || !p.dbId || !p.epoch || !Number.isSafeInteger(p.hudRevision) || p.hudRevision<0 || !validateHudSchema(p.hud) || p.hud.hudRevision!==p.hudRevision)throw new Error('INVALID_PROJECTION');
    const same=this.checkpoint?.dbId===p.dbId && this.checkpoint.epoch===p.epoch;
    if(same && p.hudRevision<this.checkpoint!.revision)throw new Error('REVISION_REGRESSION');
    if(!same)this.listener?.({type:'DATABASE_RESET'});
    this.checkpoint={dbId:p.dbId,epoch:p.epoch,revision:p.hudRevision};
    const snapshot=structuredClone(p.hud),backend=message.runtime?.backend;
    const live=message.connected && backend?.state==='READY' && backend.ready?.childInstanceId===snapshot.backend.runtimeInstanceId && backend.ready?.generation===snapshot.backend.generation;
    if(!live && snapshot.health.scoreFreshness==='CURRENT')snapshot.health.scoreFreshness='STALE';
    this.listener?.({type:'SNAPSHOT',snapshot,receivedAt:new Date().toISOString()});
  }
  async refreshTargets(){
    const epoch=this.epoch;
    this.listener?.({type:'TARGET_LIST_STATE',status:'LOADING',error:null});
    try{
      const listing=await this.request<{targets:TargetListEntry[];listRevision:number}>('/api/v1/targets');
      if(epoch!==this.epoch)return;
      if(!Array.isArray(listing.targets) || !Number.isSafeInteger(listing.listRevision) || listing.listRevision<0)throw new Error('INVALID_TARGET_LIST');
      this.targets=listing.targets;this.listRevision=listing.listRevision;this.listener?.({type:'TARGETS',targets:this.targets});
    }catch(error){if(epoch===this.epoch)this.listener?.({type:'TARGET_LIST_STATE',status:'ERROR',error:String(error)});throw error;}
  }
  async selectTarget(request:{targetId:string;expectedSha256:string}):Promise<SelectionResult>{
    if(this.listRevision===null || !this.targets.some(target=>target.targetId===request.targetId && target.contentSha256===request.expectedSha256))return {status:'TARGET_CHANGED',targetId:request.targetId,message:'Refresh Target list before activation.'};
    return this.request<SelectionResult>('/api/v1/targets/select',{...request,expectedListRevision:this.listRevision});
  }
}
