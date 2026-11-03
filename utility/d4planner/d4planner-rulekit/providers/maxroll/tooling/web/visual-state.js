'use strict';
const fs=require('node:fs/promises');
// Capture the same visible application viewport online and inside the HTTP shell.
// Element screenshots otherwise enlarge an online page but clip a nested iframe.
async function screenshotState(frame,locator,file){
  const page=typeof frame.page==='function'?frame.page():frame;
  await frame.evaluate(()=>window.scrollTo(0,0));
  await locator.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+window.scrollY-120));
  await page.mouse.move(0,0);
  if(file.includes('equipment-tooltip')) await locator.hover();
  await page.waitForTimeout(500);
  const viewport=await frame.evaluate(()=>({width:innerWidth,height:innerHeight}));
  let clip={x:0,y:0,...viewport};
  if(frame!==page){const box=await (await frame.frameElement()).boundingBox();clip={x:box.x,y:box.y,...viewport};}
  await page.screenshot({path:file,clip,animations:'disabled',scale:'css'});
  if(file.endsWith('-equipment.png')){
    const card=frame.locator('[class*=Slot__item]').first();
    await card.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
    await card.screenshot({path:file.replace('-equipment.png','-equipment-card.png'),animations:'disabled',scale:'css'});
    const images=await card.evaluate(async el=>{
      const results=[];
      for(const node of el.querySelectorAll('*')){
        const css=getComputedStyle(node),match=css.backgroundImage.match(/^url\(["']?(.*?)["']?\)$/);
        if(!match)continue;
        const image=new Image();image.src=match[1];await image.decode();
        results.push({className:node.className,url:new URL(image.src).pathname,width:image.naturalWidth,height:image.naturalHeight});
      }
      return results;
    });
    await fs.writeFile(file+'.assets.json',JSON.stringify(images,null,2));
  }
  if(file.includes('helm-editor')){
    const metadata=await locator.evaluate(el=>({sheets:[...document.styleSheets].map(s=>s.href),fonts:[...document.fonts].map(f=>({family:f.family,status:f.status,weight:f.weight,style:f.style})),controls:[...el.querySelectorAll('button,label')].map(e=>({text:e.textContent.trim(),font:getComputedStyle(e).font,fontWeight:getComputedStyle(e).fontWeight}))}));
    await fs.writeFile(file+'.json',JSON.stringify(metadata,null,2));
  }
}
module.exports={screenshotState};
