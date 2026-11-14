'use strict';
// The existing, indexed calculation bootstrap supplies its unchanged handles here.
// This Rule Kit-owned adapter adds UI tooling without changing calculation identity.
const path = require('node:path');
const {fromEnvironment} = require('./manager');
async function main(composition, log) {
  const adapterPath = process.argv[3];
  if (!path.isAbsolute(adapterPath || '')) throw Error('Absolute host adapter required');
  const planner = fromEnvironment(process.env);
  try {
    await require(adapterPath).main({...composition,
      planner: {ensureReady: options => planner.ensureReady(options),
        getEquipmentLayouts: () => require('./equipment-layout').getEquipmentLayouts(planner.stateRoot)},
      close: async () => { try { await planner.close(); } finally { await composition.close?.(); } },
    }, log);
  } catch (error) { await planner.close(); throw error; }
}
module.exports = {main};
