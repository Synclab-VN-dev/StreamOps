'use strict';

const APPLICABILITY = Object.freeze({ kind: 'pinned-engine-rendered-control',
  authority: 'sha256:891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db:effects-ui-option-identity' });
const flag = (group, label) => Object.freeze({ group, labels: Object.freeze([label]),
  types: Object.freeze(['boolean']), applicability: APPLICABILITY });
const number = (group, label, min, max, extra = {}) => Object.freeze({ group,
  labels: Object.freeze(Array.isArray(label) ? label : [label]), applicability: APPLICABILITY,
  types: Object.freeze(['number']), min, max, ...extra });

// Versioned from export-D12aM6KT.js sharedFlags/sharedParams/sharedOptions. These
// identities are provider data, not client-owned trust metadata.
const definitions = {
  barrier: Object.freeze({ group: 'Player',
    labels: Object.freeze(['Barrier (%)', 'Barrier active']),
    types: Object.freeze(['boolean', 'number']), min: 0, max: 100,
    applicability: APPLICABILITY }),
  unhindered: flag('Player', 'Unhindered'),
  unstoppable: flag('Player', 'Unstoppable'),
  weapon_swapping: flag('Misc', 'Weapon swapping'),
  crowd_controlled: flag('Player', 'Crowd controlled'),
  moving: flag('Player', 'Moving'),
  paragon_level: number('Player', 'Paragon Level', 0, 300),
  health: number('Player', 'Health (%)', 0, 100),
  fortify: number('Player', 'Fortify (%)', 0, 100),
  primary_resource: number('Player', ['Fury', 'Mana', 'Spirit', 'Essence', 'Energy',
    'Vigor', 'Faith', 'Offering', 'Primary Resource'], 0, 100,
  { normalize: 'percent-of-max' }),
  secondary_resource: number('Player', 'Secondary Resource', 0, 100,
    { normalize: 'percent-of-max' }),
  shapeshift_form: number('Player', 'Shapeshift Form', 0, 2,
    { options: Object.freeze(['Human', 'Werebear', 'Werewolf']) }),
  active_minions: number('Player', 'Active Minions', 0, 15),
  kill_streak: number('Misc', 'Kill Streak', 0, 6, { options: Object.freeze([
    'None', 'Killstreak', 'Carnage (100+)', 'Devastation (250+)', 'Bloodbath (500+)',
    'Massacre (1000+)', 'Fresh Meat! (9001+)',
  ]) }),
  enemy_near: flag('Distance', 'Close'), enemy_far: flag('Distance', 'Distant'),
  enemy_health: number('Enemy', 'Health (%)', 0, 100),
  enemy_type: number('Enemy', 'Type', 0, 3,
    { options: Object.freeze(['Normal', 'Champion', 'Elite', 'Boss']) }),
};

for (const [key, label] of Object.entries({
  enemy_slow: 'Slowed', enemy_immobilize: 'Immobilized', enemy_stun: 'Stunned',
  enemy_charm: 'Charmed', enemy_taunt: 'Taunted', enemy_weakened: 'Weakened',
  enemy_confused: 'Confused', enemy_disabled: 'Disabled', enemy_knockback: 'Knocked back',
  enemy_chill: 'Chilled', enemy_frozen: 'Frozen', enemy_knockdown: 'Knocked down',
  enemy_tethered: 'Tethered', enemy_fear: 'Feared', enemy_bleeding: 'Bleeding',
  enemy_burning: 'Burning', enemy_poisoned: 'Poisoned', enemy_corrupted: 'Corrupted',
  enemy_cursed: 'Cursed', enemy_trapped: 'Trapped',
  enemy_blooded: 'Affected by Blood skills', enemy_unstoppable: 'Unstoppable',
  enemy_staggered: 'Staggered', enemy_vulnerable: 'Vulnerable', enemy_moving: 'Moving',
})) definitions[key] = flag('Enemy', label);

definitions.enemy_hexed = Object.freeze({ group: 'Enemy', labels: Object.freeze(['Hexed']),
  types: Object.freeze(['boolean', 'number']), min: 0, max: 4,
  applicability: APPLICABILITY });

const D12_SHARED_OPTION_DEFINITIONS = Object.freeze(definitions);

module.exports = { D12_SHARED_OPTION_DEFINITIONS };
