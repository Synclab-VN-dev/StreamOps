'use strict';
const assert=require('node:assert/strict');
const {selectClass}=require('./ui-scenarios');
const dialog=p=>p.locator('[class*="_Dialog_"]').last();
const slot=(p,id)=>p.locator('[class*=Slot__item][class*="slot-'+id+'__"]').first();
async function close(p){await dialog(p).locator(':scope > [class*=DialogHeader] button').last().click();}
async function picker(p,id){await slot(p,id).click();const select=dialog(p).getByText('Select',{exact:true});if(await select.count())await select.click();await p.locator('.d4t-library-ex').waitFor();}
async function imageEvidence(locator){
  return locator.evaluate(async el=>{
    const url=getComputedStyle(el).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
    if(!url)throw Error('Artwork has no computed URL');const image=new Image();image.src=url;await image.decode();
    const rect=el.getBoundingClientRect();if(!image.naturalWidth||!rect.width||!rect.height)throw Error('Artwork is not decodable/renderable');
    return {url,width:image.naturalWidth,height:image.naturalHeight,box:{width:rect.width,height:rect.height}};
  });
}
async function fullScenarios(p,{checkpoint=async()=>{}}={}){
  const touch=await p.evaluate(()=>navigator.maxTouchPoints>0);
  const activate=locator=>touch?locator.tap():locator.click();
  await activate(p.getByRole('button',{name:'New Profile',exact:true}));
  if(await p.getByText('Discard unsaved changes and start from a blank profile?',{exact:true}).isVisible())await p.getByRole('button',{name:'Yes',exact:true}).click();
  const rows=[];
  const cases=[['Sorcerer',4,'Starfall Coronet'],['Rogue',5,'Razorplate'],['Rogue',5,"Scoundrel's Leathers"],['Rogue',4,'Runic Skullcap'],['Rogue',4,'Harlequin Crest'],
    ['Rogue',13],['Rogue',14],['Rogue',15],['Rogue',16],['Rogue',18],['Rogue',10],['Rogue',11],['Rogue',12],['Necromancer',6],['Barbarian',8],['Druid',6],['Spiritborn',7],['Paladin',6],['Warlock',6],['Rogue',20],['Rogue',21]];
  for(let index=0;index<cases.length;index++){
    const [className,id,name]=cases[index];await selectClass(p,className);
    const level=p.locator('input[type=number][min="1"][max="70"]');await level.fill('70');await level.press('Enter');
    await picker(p,id);
    const search=p.locator('.d4t-library-search input');
    const initial=p.locator('.d4t-library-ex .d4t-item');
    // Exercise last-row scrolling before search, not just the first above-the-fold card.
    await initial.last().scrollIntoViewIfNeeded();await initial.first().scrollIntoViewIfNeeded();
    if(name)await search.fill(name);
    const row=name?initial.filter({has:p.locator('.d4t-title').getByText(name,{exact:true})}).first():initial.first();
    await row.waitFor();await row.scrollIntoViewIfNeeded();
    const title=await row.locator('.d4t-title').first().innerText();
    const icon=row.locator('.d4t-top-right-icon').first();
    const image=await imageEvidence(icon);
    const key='equipment-'+index+'-'+className+'-'+id;
    await checkpoint(key+'-picker',row,{icon});
    await activate(row);await dialog(p).getByRole('button',{name:'Unequip',exact:true}).waitFor();
    await checkpoint(key+'-editor',dialog(p));await close(p);
    await slot(p,id).scrollIntoViewIfNeeded();await checkpoint(key+'-equipped',slot(p,id));
    await slot(p,id).evaluate(el=>window.scrollTo(0,el.getBoundingClientRect().top+window.scrollY-200));
    await slot(p,id).hover();
    // Tooltip portals differ between captured frontends; select visible native tooltip, never a label.
    const tips=p.locator('.d4t-GameTooltip:visible');await tips.last().waitFor();
    assert((await tips.last().innerText()).includes(title),'Tooltip belongs to the selected item');
    await checkpoint(key+'-tooltip',tips.last(),{tooltip:true,title});
    assert((await tips.last().innerText()).includes(title),'Screenshot must not change the hovered item');
    if(index===3){await slot(p,id).click();await dialog(p).getByRole('button',{name:'Unequip',exact:true}).click();if(await dialog(p).count())await close(p);assert(await slot(p,id).locator('[class*=Slot__empty]').count(),'Unequip restores empty slot');}
    rows.push({className,slot:id,title,image});
  }
  await selectClass(p,'Rogue');await picker(p,4);await p.locator('.d4t-library-search input').fill('Runic Skullcap');await p.locator('.d4t-library-ex .d4t-title').getByText('Runic Skullcap',{exact:true}).click();
  const editor=dialog(p);
  await editor.getByText('900',{exact:true}).click();const power=editor.locator('input[type=number][max="900"]');await power.fill('850');await power.press('Enter');
  await editor.getByText('Add Modifier',{exact:true}).nth(0).click();await editor.getByText('Toughened',{exact:true}).click();
  await editor.getByText('Tempering',{exact:true}).locator('..').getByText('Add Modifier',{exact:true}).click();
  await editor.getByText('Fire Resistance',{exact:true}).click();
  await editor.getByText('Legendary Aspect',{exact:true}).locator('..').getByText('Add Modifier',{exact:true}).click();
  await editor.getByText('Aspect of Might',{exact:true}).click();
  await editor.getByText('Empty Socket',{exact:true}).first().click();
  await editor.locator('.d4t-ModSelect input').fill('Ruby');
  await editor.getByText('Royal Ruby',{exact:true}).first().click();
  assert.equal(await editor.getByText('Empty Socket',{exact:true}).count(),1);
  await checkpoint('edited-affix-temper-aspect-gem',editor);
  await close(p);
  const skills=p.locator('[class*=PlannerSkillsV2]');await skills.getByText('List',{exact:true}).locator('..').click();
  const skill=skills.getByText('Puncture',{exact:true}).locator('..').locator('[class*=Skill__icon]');await activate(skill);assert.match(await skills.innerText(),/1 points spent/);await skill.click({button:'right'});assert.match(await skills.innerText(),/0 points spent/);await skill.click();await checkpoint('skill-allocate-refund',skills);
  await skills.getByText('Tree',{exact:true}).locator('..').click();
  await checkpoint('skill-tree',skills);
  const treeNodes=skills.locator('.d4t-TreeGraph .d4t-node:not(.d4t-node-root)');
  const visibleNode=await treeNodes.evaluateAll(nodes=>nodes.findIndex(el=>{const b=el.getBoundingClientRect(),v=el.closest('.d4t-PlannerTreeScroll').getBoundingClientRect();return b.left>=Math.max(v.left,0)&&b.right<=Math.min(v.right,innerWidth)&&b.top>=Math.max(v.top,0)&&b.bottom<=Math.min(v.bottom,innerHeight);}));
  assert(visibleNode>=0,'A real skill tree node is visible in the native viewport');
  const treeSkill=treeNodes.nth(visibleNode);await imageEvidence(treeSkill.locator('.d4t-icon'));await treeSkill.hover();
  const description=p.locator('.d4t-GameTooltip:visible').last();await description.waitFor();assert((await description.innerText()).length>50,'Native skill description rendered');await checkpoint('skill-tooltip',description,{tooltip:true});
  const paragon=p.locator('[class*=ParagonView]');const node=paragon.locator('.d4t-node[style="left: 10em; top: 13em;"]');await node.click();assert.match(await paragon.innerText(),/1 points spent/);await node.click({button:'right'});assert.match(await paragon.innerText(),/0 points spent/);await node.click();await checkpoint('paragon-allocate-refund',paragon);
  await paragon.locator('.d4t-node.d4t-socket').click();await activate(p.getByText('Combat',{exact:true}));
  if(await p.getByText('Select Glyph',{exact:true}).isVisible())await close(p);
  assert.match(await paragon.innerText(),/Combat/);
  await checkpoint('paragon-glyph',paragon);
  const boards=paragon.locator('.d4t-boards');const before=await boards.getAttribute('style');
  await paragon.locator('[class*=controls_Button__]').nth(0).click();
  await p.waitForFunction(before=>document.querySelector('.d4t-boards').getAttribute('style')!==before,before);
  assert.notEqual(await boards.getAttribute('style'),before,'Zoom changes native board transform');
  await paragon.locator('[class*=controls_Button__]').nth(1).click();
  await checkpoint('paragon-zoom',paragon);
  await paragon.locator('.d4t-node.d4t-gate').first().click();await p.getByText('Cheap Shot',{exact:true}).click();
  assert.equal(await paragon.locator('.d4t-ParagonBoard').count(),2);
  const second=paragon.locator('.d4t-ParagonBoard').last(),grid=second.locator('.d4t-grid');
  const positions=await grid.innerHTML();await second.locator('[data-icon="arrows-rotate"]').click();
  assert.notEqual(await grid.innerHTML(),positions,'Rotation changes native node layout');
  await checkpoint('paragon-board-rotation',paragon);
  // Panning is clamped while the entire board fits; zoom in before testing drag.
  for(let i=0;i<6;i++)await paragon.locator('[class*=controls_Button__]').nth(0).click();
  await p.waitForTimeout(100);
  const view=paragon.locator('.d4t-ParagonScroll');await view.scrollIntoViewIfNeeded();
  const page=typeof p.page==='function'?p.page():p;const box=await view.boundingBox();
  const transform=await boards.getAttribute('style');
  await page.mouse.move(box.x+15,box.y+15);await page.mouse.down();await page.mouse.move(box.x+65,box.y+35,{steps:5});await page.waitForTimeout(60);await page.mouse.up();
  await p.waitForFunction(before=>document.querySelector('.d4t-boards').getAttribute('style')!==before,transform);
  assert.notEqual(await boards.getAttribute('style'),transform,'Pan changes native board transform');
  await checkpoint('paragon-pan',paragon);
  return {equipment:rows,affix:'Toughened',temper:'Fire Resistance',aspect:'Aspect of Might',gem:'Royal Ruby',unequip:true,skillAllocateRefund:true,skillTreeAndDescription:true,paragonAllocateRefund:true,glyph:true,boardAddRotate:true,panZoom:true,touchInput:touch};
}
module.exports={fullScenarios,picker,close,imageEvidence};
