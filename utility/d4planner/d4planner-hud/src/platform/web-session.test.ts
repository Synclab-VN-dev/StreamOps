// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {BrowserSession} from './web-session';
afterEach(()=>{vi.unstubAllGlobals();document.body.replaceChildren();});
it('coalesces expired session authentication, preserves workspace, and replaces CSRF',async()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 HTMLDialogElement.prototype.close=function(){this.open=false;};
 const session={subject:'owner',csrf:'old',permissions:['hud.read']};
 const fetchMock=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(session)))
 .mockResolvedValueOnce(new Response('',{status:401}))
 .mockResolvedValueOnce(new Response('{}'))
 .mockResolvedValueOnce(new Response(JSON.stringify({...session,csrf:'new'})));
 vi.stubGlobal('fetch',fetchMock);
 const workspace=document.createElement('textarea');workspace.value='unsent description';document.body.append(workspace);
 const auth=new BrowserSession();await auth.ensure();
 const first=auth.ensure(),second=auth.ensure();expect(first).toBe(second);
 await vi.waitFor(()=>expect(document.querySelectorAll('dialog')).toHaveLength(1));
 const input=document.querySelector('input')!;input.value='private-token';document.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}));
 expect((await first).csrf).toBe('new');expect(workspace.value).toBe('unsent description');
 expect(document.querySelector('dialog')).toBeNull();expect(input.value).toBe('');
 expect(fetchMock).toHaveBeenCalledTimes(4);
});
it('does not replay a rejected mutation after reauthentication',async()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true;};HTMLDialogElement.prototype.close=function(){this.open=false;};
 const value={subject:'owner',csrf:'old',permissions:['hud.read','runtime.control']};
 const fetchMock=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(value)))
 .mockResolvedValueOnce(new Response('{}',{status:401}))
 .mockResolvedValueOnce(new Response('{}',{status:401}))
 .mockResolvedValueOnce(new Response('{}'))
 .mockResolvedValueOnce(new Response(JSON.stringify({...value,csrf:'new'})));
 vi.stubGlobal('fetch',fetchMock);
 const {webPlatform}=await import('./web');const platform=await webPlatform(document.createElement('div'));
 const rejection=expect(platform.invoke('stop_backend')).rejects.toMatchObject({code:'SESSION_REAUTHENTICATED_RETRY_REQUIRED'});
 await vi.waitFor(()=>expect(document.querySelector('dialog')).not.toBeNull());
 document.querySelector('input')!.value='private-token';document.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}));
 await rejection;
 expect(fetchMock.mock.calls.filter(([url])=>url==='/api/v1/runtime/backend/stop')).toHaveLength(1);
});
