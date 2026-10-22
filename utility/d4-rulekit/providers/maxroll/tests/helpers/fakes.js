'use strict';

const { METRIC_CATALOG } = require('../../src');

function fakeMetrics(phase, fire = 22) {
  return METRIC_CATALOG.map((metric, index) => ({
    id: metric.id, name: metric.name,
    rawValue: metric.id === 'maxroll.heroDetails.446' ? fire : index + 1,
    displayValue: index < 34 ? String(index + 1) : null,
    unit: null, status: 'OBSERVED', provenance: { phase },
  }));
}

function makeSessionDependencies() {
  const controls = {
    phase: 0, failApply: false, failExtract: false, failRestore: false,
    hangApply: false, releases: 0, unmounts: 0,
  };
  const adapter = {
    cdp: {},
    async apply(desired) {
      if (controls.failApply || controls.failRestore) throw new Error('apply failed');
      if (controls.hangApply) await new Promise(() => {});
      controls.phase += 1;
      controls.current = structuredClone(desired);
      return { phase: controls.phase, observed: desired };
    },
  };
  const extractor = {
    async extract(_cdp, phase) {
      if (controls.failExtract) throw new Error('extract failed');
      const modified = controls.current.equipment.Helm.modifiers.includes('of-dampening');
      return fakeMetrics(phase, modified ? 2822 : 22);
    },
  };
  const lease = { valid: true, async release() { controls.releases += 1; } };
  const mount = { async unmount() { controls.unmounts += 1; } };
  return { adapter, extractor, lease, mount, controls };
}

module.exports = { fakeMetrics, makeSessionDependencies };
