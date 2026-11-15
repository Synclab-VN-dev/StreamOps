/** One authentication flow per page; credentials never persist in browser storage. */
export type WebSession = {subject:string;csrf:string;permissions:string[]};
export class BrowserSession {
  current:WebSession|null=null;
  private pending:Promise<WebSession>|null=null;
  ensure():Promise<WebSession>{
    if(this.pending)return this.pending;
    this.pending=this.check().finally(()=>{this.pending=null;});
    return this.pending;
  }
  private async read():Promise<WebSession|null>{
    const response=await fetch('/api/v1/session',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(response.status===401)return null;
    if(!response.ok)throw new Error('SESSION_CHECK_UNAVAILABLE');
    const value=await response.json();
    if(typeof value.subject!=='string' || !value.subject || typeof value.csrf!=='string' || !value.csrf || !Array.isArray(value.permissions))throw new Error('INVALID_SESSION');
    return value;
  }
  private async check():Promise<WebSession>{
    const value=await this.read();
    if(value && (!this.current || this.current.subject===value.subject)){this.current=value;return value;}
    // Reauthentication must not transfer an open Report form to a different actor.
    return new Promise<WebSession>(resolve=>{
      const dialog=document.createElement('dialog'),form=document.createElement('form'),title=document.createElement('h1'),input=document.createElement('input'),button=document.createElement('button'),status=document.createElement('p');
      dialog.setAttribute('aria-label','D4Planner sign in');
      dialog.style.cssText='max-width:360px;background:#222;color:white;font:16px system-ui;border-radius:12px';
      title.textContent=this.current?'Session expired — sign in again':'Connect to D4Planner';
      input.type='password';input.autocomplete='off';input.required=true;input.setAttribute('aria-label','Access token');button.textContent='Connect';status.setAttribute('role','alert');
      form.append(title,input,button,status);dialog.append(form);document.body.append(dialog);
      dialog.oncancel=event=>event.preventDefault();dialog.showModal();
      form.onsubmit=async event=>{
        event.preventDefault();if(button.disabled)return;button.disabled=true;status.textContent='Connecting…';
        try{
          const response=await fetch('/api/v1/session',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify({token:input.value}),signal:AbortSignal.timeout(10000)});input.value='';
          if(!response.ok)throw new Error('Connection refused. Check your access token.');
          const next=await this.read();
          if(!next)throw new Error('Authentication failed. Try again.');
          if(this.current && next.subject!==this.current.subject){
            await fetch('/api/v1/session',{method:'DELETE',credentials:'same-origin',headers:{'x-hud-csrf':next.csrf}});
            throw new Error('Use the same account to recover this open workspace.');
          }
          this.current=next;dialog.close();dialog.remove();resolve(next);
        }catch(error){status.textContent=String(error);button.disabled=false;}
      };
    });
  }
}
