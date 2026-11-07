'use strict';
const assert = require('node:assert/strict');
const CLASSES = ['Barbarian', 'Druid', 'Necromancer', 'Rogue', 'Sorcerer', 'Spiritborn', 'Paladin', 'Warlock'];
async function selectClass(page, name) {
  await page.locator('[class*="header_ClassOption"]').first().click();
  await page.getByText(name, {exact:true}).last().click();
  await page.waitForTimeout(100);
}
async function scenarios(page, { checkpoint = async () => {}, allClasses = true } = {}) {
  await page.getByRole('button',{name:'New Profile',exact:true}).waitFor();
  const newProfile=page.getByRole('button',{name:'New Profile',exact:true});
  if(await newProfile.isDisabled()) {
    const initialLevel=page.locator('input[type=number][min="1"][max="70"]');
    await initialLevel.fill('68');await initialLevel.press('Enter');
  }
  assert.equal(await newProfile.isDisabled(),false,'New Profile must be actionable');
  await newProfile.click();
  const classes = [];
  for (const name of allClasses ? CLASSES : ['Rogue']) {
    await selectClass(page, name);
    await page.locator('[class*=PlannerSkillsV2]').scrollIntoViewIfNeeded();
    await page.locator('[class*=ParagonView]').scrollIntoViewIfNeeded();
    await checkpoint('class-' + name, page.locator('[class*=ParagonView]'));
    classes.push(name);
  }
  await selectClass(page,'Rogue');
  const level=page.locator('input[type=number][min="1"][max="70"]');
  await level.fill('69'); await level.press('Enter'); assert.equal(await level.inputValue(),'69');
  await page.getByText('Helm',{exact:true}).first().locator('..').locator('[class*=Slot__item]').click();
  await checkpoint('helm-picker',page.locator('[class*="_Dialog_"]').last());
  await page.getByText('Runic Skullcap',{exact:true}).first().click();
  const editor=page.locator('[class*="_Dialog_"]').filter({has:page.locator('[class*=ItemEditor]')});
  await editor.getByText('900',{exact:true}).click();
  const power=editor.locator('input[type=number][max="900"]');
  await power.fill('850');await power.press('Enter');
  assert.equal(await editor.getByText('850',{exact:true}).count(),1);
  await checkpoint('helm-editor',editor);
  await editor.locator(':scope > [class*="DialogHeader"] button').click();
  const helm=page.locator('[class*=Slot__item]').first();
  await helm.hover();
  await checkpoint('equipment',page.locator('[class*=PlannerEquipment]').first());
  await helm.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+window.scrollY-150));
  await helm.hover();
  const tooltip=page.locator('.d4t-GameTooltip');
  await tooltip.waitFor({state:'visible'});assert.match(await tooltip.innerText(),/Runic Skullcap/);
  await checkpoint('equipment-tooltip',helm);
  const skills=page.locator('[class*=PlannerSkillsV2]');
  await skills.getByText('List',{exact:true}).locator('..').click();
  await skills.getByText('Puncture',{exact:true}).locator('..').locator('[class*=Skill__icon]').click();
  assert.match(await skills.innerText(),/1 points spent/);
  await checkpoint('skills',skills);
  const paragon=page.locator('[class*=ParagonView]');
  await paragon.locator('.d4t-node[style="left: 10em; top: 13em;"]').click();
  assert.match(await paragon.innerText(),/1 points spent/);
  await checkpoint('paragon',paragon);
  return {classes,level:69,equipment:'Runic Skullcap',itemPower:850,skill:'Puncture',skillPoints:1,paragonNode:283};
}
module.exports={scenarios,selectClass,CLASSES};
