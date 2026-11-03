'use strict';
const assert=require('node:assert/strict');
const {CLASSES,selectClass}=require('./ui-scenarios');
// Read-only inspection of the native category model, not a duplicate selectable-item filter.
// The renderer's item list is inspected before layout/virtualization and no selection callback is called.
async function nativeCategories(page){
  return page.locator('.d4t-library-ex').evaluate(el=>{
    let fiber=el[Object.keys(el).find(k=>k.startsWith('__reactFiber'))];
    while(fiber&&!Array.isArray(fiber.memoizedProps?.list))fiber=fiber.return;
    if(!fiber)throw Error('Unsupported native picker category model');
    return fiber.memoizedProps.list.filter(c=>typeof c.items==='function').map(c=>({name:c.name,
      entities:c.items().map(entry=>{const rendered=entry.render();if(rendered?.props?.id===undefined)throw Error('Native category entity ID unavailable');return rendered.props.id;})}));
  });
}
async function collectSelectable(page){
  const groups=[];
  for(const className of CLASSES){
    await selectClass(page,className);
    const level=page.locator('input[type=number][min="1"][max="70"]');await level.fill('70');await level.press('Enter');
    const seen=new Set();
    for(let pass=0;pass<2;pass++){
    const slots=await page.locator('[class*=Slot__item]').evaluateAll(elements=>elements.map(e=>({
      slot:Number(e.className.match(/slot-(\d+)__/)[1]),clickable:e.className.includes('clickable'),visible:!!e.getClientRects().length
    })));
    assert(slots.length,'Native equipment slots missing');
    for(const slot of slots.filter(s=>s.clickable&&s.visible&&!seen.has(s.slot))){
      const target=page.locator('[class*=Slot__item][class*="slot-'+slot.slot+'__"]').first();
      await target.click();
      const select=page.locator('[class*="_Dialog_"]').last().getByText('Select',{exact:true});
      if(await select.count())await select.click();
      await page.locator('.d4t-library-ex').waitFor();
      seen.add(slot.slot);
      const categories=await nativeCategories(page);groups.push({className,slot:slot.slot,categories});
      if(slot.slot===20){await page.locator('.d4t-library-ex .d4t-item').first().click();}
      await page.locator('[class*="_Dialog_"]').last().locator(':scope > [class*=DialogHeader] button').last().click();
    }
    }
  }
  assert.equal(new Set(groups.map(g=>g.className)).size,CLASSES.length);
  return {schemaVersion:'maxroll-selectable-coverage/v1',method:'READ_ONLY_NATIVE_CATEGORY_MODEL',groups};
}
function entityDependencies(data,coverage){
  const rows=[],unknown=[];
  for(const group of coverage.groups)for(const category of group.categories)for(const id of category.entities){
    // Numeric IDs refer to user-owned/stash instances, not catalog templates.
    if(typeof id!=='string')continue;
    const entity=data.items[id];
    if(!entity){if(data.itemSets?.[id])continue;unknown.push(id);continue;}
    const images=new Set([entity.image,...(entity.images||[]).flatMap(v=>[v.male,v.female])].filter(n=>Number.isInteger(n)&&n>0));
    rows.push({className:group.className,slot:group.slot,category:category.name,entityId:id,type:entity.type,
      images:[...images].map(imageId=>({imageId,url:`https://assets-ng.maxroll.gg/d4-tools/images/webp/${imageId}.webp`}))});
  }
  assert.equal(unknown.length,0,'Unknown selectable catalog IDs');
  assert(rows.length>0,'No selectable catalog templates identified');
  return rows;
}
function auxiliaryDependencies(data){
  const rows=[];
  function emit(value,field){
    if(Number.isInteger(value)&&value>0)rows.push({family:field[0],entityId:field[1],field:field.slice(2).join('.'),imageId:value,url:`https://assets-ng.maxroll.gg/d4-tools/images/webp/${value}.webp`});
    else if(Array.isArray(value))value.forEach((v,i)=>emit(v,[...field,String(i)]));
    else if(value&&typeof value==='object')for(const [k,v]of Object.entries(value))emit(v,[...field,k]);
  }
  function walk(value,field=[]){
    if(!value||typeof value!=='object')return;
    for(const [key,entry]of Object.entries(value)){
      if(['icon','iconMask','image'].includes(key))emit(entry,[...field,key]);
      else walk(entry,[...field,key]);
    }
  }
  // Supplemental catalog references, not a claim that every raw record is selectable.
  for(const [family,values]of Object.entries(data))if(family!=='items')walk(values,[family]);
  for(const [id,item]of Object.entries(data.items||{})){
    if(['Gem','ConditionRune','EffectRune','HoradricSeal','Charm','ParagonGlyph'].includes(item.type)||item.type?.includes('Socketable'))walk(item,['socket-and-talisman-catalog',id]);
  }
  return rows;
}
function profileDependencies(data,state){
  const ids=new Set();
  for(const profile of state.profiles||[])for(const ref of Object.values(profile.items||{})){
    if(!ref)continue;const item=state.items?.[ref];if(item?.id)ids.add(item.id);
  }
  return entityDependencies(data,{groups:[{className:'CAPTURED_PROFILE',slot:'all',categories:[{name:'Referenced native equipment',entities:[...ids]}]}]});
}
function normalizeCoverage(coverage){
  return coverage.groups.map(g=>({className:g.className,slot:g.slot,categories:g.categories.map(c=>({name:c.name,entities:c.entities.filter(id=>typeof id==='string').sort()})).filter(c=>c.entities.length)}));
}
module.exports={profileDependencies,normalizeCoverage,nativeCategories,collectSelectable,entityDependencies,auxiliaryDependencies};
