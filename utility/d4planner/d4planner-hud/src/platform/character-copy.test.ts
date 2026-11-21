// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {webPlatform} from './web';
afterEach(()=>vi.unstubAllGlobals());
it('copies the BE document to browser clipboard, preserving nulls and Unicode',async()=>{
 const value={schemaVersion:'d4planner-character-observations/v1',equipment:[{sockets:[null,null],name:'Tiếng Việt'}]};
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({subject:'owner',csrf:'c',permissions:['hud.read']}))).mockResolvedValueOnce(new Response(JSON.stringify(value)));
 const writeText=vi.fn().mockResolvedValue(undefined);vi.stubGlobal('fetch',fetch);vi.stubGlobal('isSecureContext',true);vi.stubGlobal('navigator',{clipboard:{writeText}});
 const platform=await webPlatform(document.createElement('div'));await platform.invoke('copy_character_json');
 expect(fetch.mock.calls[1][0]).toBe('/api/v1/character/export');expect(JSON.parse(writeText.mock.calls[0][0])).toEqual(value);
});
it('does not report success for denied clipboard or unavailable export',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({subject:'owner',csrf:'c',permissions:['hud.read']}))).mockResolvedValueOnce(new Response('{}')).mockResolvedValueOnce(new Response(JSON.stringify({error:{code:'CHARACTER_NO_DATA'}}),{status:503}));
 const writeText=vi.fn().mockRejectedValue(new Error('denied'));vi.stubGlobal('fetch',fetch);vi.stubGlobal('isSecureContext',true);vi.stubGlobal('navigator',{clipboard:{writeText}});
 const platform=await webPlatform(document.createElement('div'));await expect(platform.invoke('copy_character_json')).rejects.toThrow('CLIPBOARD_UNAVAILABLE');await expect(platform.invoke('copy_character_json')).rejects.toMatchObject({code:'CHARACTER_NO_DATA'});expect(writeText).toHaveBeenCalledTimes(1);
});
