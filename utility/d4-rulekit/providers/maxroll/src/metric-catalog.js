'use strict';

const rows = [
  [900, 'summary', 'Weapon Damage'], [901, 'summary', 'Toughness'],
  [279, 'core', 'Level'], [108, 'core', 'Strength'], [109, 'core', 'Intelligence'],
  [110, 'core', 'Willpower'], [111, 'core', 'Dexterity'],
  [2036494626, 'resistances', 'Toughness'], [480, 'resistances', 'Armor'],
  [439, 'resistances', 'Physical Resistance'], [446, 'resistances', 'Fire Resistance'],
  [453, 'resistances', 'Lightning Resistance'], [460, 'resistances', 'Cold Resistance'],
  [467, 'resistances', 'Poison Resistance'], [474, 'resistances', 'Shadow Resistance'],
  [93, 'offensive', 'Base Ranged Weapon Damage'], [46, 'offensive', 'Base Dual Wielded Weapon Damage'],
  [114, 'offensive', 'Weapon Speed'], [3, 'offensive', 'Attack Speed Bonus'],
  [4, 'offensive', 'Critical Strike Chance'], [347, 'offensive', 'Critical Strike Damage'],
  [349, 'offensive', 'Vulnerable Damage'], [1, 'offensive', 'All Damage'],
  [49, 'offensive', 'Damage with Fire'], [50, 'offensive', 'Damage with Lightning'],
  [51, 'offensive', 'Damage with Cold'], [52, 'offensive', 'Damage with Holy'],
  [71041540, 'offensive', 'Damage with Poison'], [53, 'offensive', 'Damage with Shadow'],
  [251, 'offensive', 'Damage with Imbued'], [2, 'offensive', 'Damage vs Elites'],
  [25, 'offensive', 'Damage vs Crowd Controlled'], [56, 'offensive', 'Damage vs Healthy'],
  [166, 'offensive', 'Damage vs Poisoned'], [299, 'offensive', 'Thorns'],
  [58, 'defensive', 'Maximum Life'], [78, 'defensive', 'Potion Capacity'],
  [180, 'defensive', 'Healing Received'], [431, 'defensive', 'Armor'],
  [357, 'defensive', 'All Damage Reduction'], [104, 'defensive', 'Barrier Bonus'],
  [61, 'defensive', 'Dodge Chance'], [81, 'utility', 'Maximum Energy'],
  [286, 'utility', 'Energy Regeneration'], [80, 'utility', 'Movement Speed'],
  [92, 'utility', 'Cooldown Reduction'], [152, 'utility', 'Imbuement Cooldown Reduction'],
  [181, 'utility', 'Lucky Hit Chance Bonus'], [367, 'utility', 'Experience Bonus'],
  [70, 'pvp', 'Damage Reduction'],
];

const METRIC_CATALOG = Object.freeze(rows.map(([internalId, category, name]) => Object.freeze({
  id: `maxroll.heroDetails.${internalId}`,
  internalId,
  category,
  name,
  rawValueType: 'finite-number',
})));

module.exports = { METRIC_CATALOG };
