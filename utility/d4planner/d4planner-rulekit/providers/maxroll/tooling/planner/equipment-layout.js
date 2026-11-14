'use strict';
// Read layout evidence from the validated UI snapshot. No capture, download,
// browser launch, character-class inference or modification of user profiles.
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {readSelection} = require('./selection');
const {loadSnapshot} = require('../web/server');
const unavailable = () => Object.assign(new Error('Verified equipment layout unavailable'), {code:'PLANNER_LAYOUT_UNAVAILABLE'});
function layoutFromCoverage(coverage, provenance) {
  if (coverage?.schemaVersion !== 'maxroll-selectable-coverage/v1' ||
      coverage.method !== 'READ_ONLY_NATIVE_CATEGORY_MODEL' ||
      !Array.isArray(coverage.groups) || !coverage.groups.length) throw unavailable();
  const classes = new Map();
  for (const group of coverage.groups) {
    if (typeof group.className !== 'string' || !group.className.trim() ||
        !Number.isSafeInteger(group.slot) || group.slot < 0 || !Array.isArray(group.categories)) throw unavailable();
    if (!classes.has(group.className)) classes.set(group.className, new Map());
    const slots = classes.get(group.className);
    if (slots.has(group.slot)) throw unavailable();
    const types = new Set();
    for (const category of group.categories) {
      if (typeof category.name !== 'string' || !category.name.trim() || !Array.isArray(category.entities)) throw unavailable();
      if (category.name !== 'All Items' && category.entities.length) types.add(category.name);
    }
    slots.set(group.slot,{providerSlotId:String(group.slot),slotFamily:group.slot===7?'main_hand':group.slot===6?'off_hand':group.slot>=8&&group.slot<=12?'unsupported_weapon':null,itemTypes:[...types]});
  }
  return {schemaVersion:'d4planner-equipment-layout/v1',status:'READY',
    provenance:{...provenance},classes:[...classes].map(([className,slots])=>({className,slots:[...slots.values()]}))};
}
async function getEquipmentLayouts(stateRoot) {
  const config = await readSelection(stateRoot,6085);
  const snapshot = await loadSnapshot(config);
  if (snapshot.uiVerification.status !== 'AUTOMATED_VALIDATED') throw unavailable();
  // Recheck the exact bytes used here, not only the earlier verification read.
  const bytes = await fs.readFile(path.join(config.snapshotRoot,config.snapshotId,'ui-coverage.json'));
  if (createHash('sha256').update(bytes).digest('hex') !== config.uiTrust.coverageSha256) throw unavailable();
  const result = layoutFromCoverage(JSON.parse(bytes).selectable,{
    providerId:'maxroll',snapshotId:config.snapshotId,manifestSha256:config.manifestSha256,
    coverageSha256:config.uiTrust.coverageSha256,gameVersion:snapshot.manifest.version,
  });
  const after = await readSelection(stateRoot,6085);
  if (after.snapshotId !== config.snapshotId || after.manifestSha256 !== config.manifestSha256 ||
      after.uiTrust.coverageSha256 !== config.uiTrust.coverageSha256 ||
      after.uiTrust.validationSha256 !== config.uiTrust.validationSha256) throw unavailable();
  return result;
}
module.exports = {layoutFromCoverage,getEquipmentLayouts};
