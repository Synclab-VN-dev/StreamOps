'use strict';

function copy(value) { return structuredClone(value); }

function applyChanges(build, changes) {
  const next = copy(build);
  next.equipment ??= {};
  next.skills ??= {};
  next.effects ??= {};
  for (const change of changes) {
    if (change.type === 'equipment.replace') next.equipment[change.slot] = copy(change.item);
    else if (change.type === 'skill.setRank') next.skills[change.skillId] = change.rank;
    else if (change.type === 'effect.set') next.effects[change.effectId] = change.active;
  }
  return next;
}

function metrics(build) {
  return [
    { id: 'synthetic.effectCount', rawValue: Object.values(build.effects ?? {}).filter(Boolean).length, displayValue: 'synthetic', unit: 'count', status: 'OBSERVED', provenance: { source: 'synthetic-provider' } },
    { id: 'synthetic.itemCount', rawValue: Object.keys(build.equipment ?? {}).length, displayValue: 'synthetic', unit: 'count', status: 'OBSERVED' },
    { id: 'synthetic.percent', rawValue: Object.values(build.skills ?? {}).reduce((sum, rank) => sum + rank, 0), displayValue: 'synthetic', unit: '%', status: 'OBSERVED' },
    { id: 'synthetic.unknown', rawValue: null, displayValue: null, unit: null, status: 'UNKNOWN' },
    { id: 'synthetic.unsupported', rawValue: null, displayValue: null, unit: null, status: 'UNSUPPORTED' },
  ];
}

function capabilities(stateModel) {
  return {
    version: 'synthetic-capabilities/v1', policyVersion: 'synthetic-policy/v1', stateModel,
    metricIds: ['synthetic.effectCount', 'synthetic.itemCount', 'synthetic.percent', 'synthetic.unknown', 'synthetic.unsupported'],
    changeTypes: ['equipment.replace', 'skill.setRank', 'effect.set'],
  };
}

function makeStatefulProvider(options = {}) {
  const controls = {
    failNext: false, failMode: null, failRestore: false,
    transformNext: null, transformMode: null,
    hangNext: false, hangMode: null, hangClose: false,
    evaluations: 0, closes: 0, active: 0, maxActive: 0,
  };
  const provider = {
    id: options.id ?? 'stateful.synthetic', version: options.version ?? '1.0.0', available: options.available,
    getCapabilities: () => ({ ...capabilities('stateful'), internalSecret: 'must-not-leak' }),
    async createSession({ build }) {
      let state = copy(build);
      return {
        async checkpoint() { return copy(state); },
        async restore(checkpoint) {
          if (controls.failRestore) throw new Error('synthetic restore failure');
          state = copy(checkpoint);
        },
        async evaluate(input) {
          controls.evaluations += 1;
          controls.active += 1;
          controls.maxActive = Math.max(controls.maxActive, controls.active);
          try {
            if (controls.hangNext && (!controls.hangMode || controls.hangMode === input.mode)) {
              controls.hangNext = false;
              controls.hangMode = null;
              await new Promise(() => {});
            }
            if (controls.failNext && (!controls.failMode || controls.failMode === input.mode)) {
              controls.failNext = false;
              controls.failMode = null;
              throw new Error('synthetic evaluation failure');
            }
            let candidate = applyChanges(input.build, input.changes);
            if (controls.transformNext && (!controls.transformMode || controls.transformMode === input.mode)) {
              candidate = controls.transformNext(candidate);
              controls.transformNext = null;
              controls.transformMode = null;
            }
            if (input.mode === 'PREVIEW' || input.mode === 'COMMIT' || input.mode === 'RESET') state = copy(candidate);
            return { build: candidate, metrics: metrics(candidate), provenance: { fixture: 'stateful' } };
          } finally {
            controls.active -= 1;
          }
        },
        async close() {
          controls.closes += 1;
          if (controls.hangClose) await new Promise(() => {});
        },
      };
    },
  };
  return { provider, controls };
}

function makeStatelessProvider(options = {}) {
  const controls = { evaluations: 0, closes: 0, active: 0, maxActive: 0, gate: null };
  const provider = {
    id: options.id ?? 'stateless.synthetic', version: options.version ?? '2.0.0', available: options.available,
    getCapabilities: () => capabilities('stateless'),
    async createSession() {
      return {
        async evaluate(input) {
          controls.evaluations += 1;
          controls.active += 1;
          controls.maxActive = Math.max(controls.maxActive, controls.active);
          try {
            if (controls.gate) await controls.gate;
            const candidate = applyChanges(input.build, input.changes);
            return { build: candidate, metrics: metrics(candidate), provenance: { fixture: 'stateless' } };
          } finally { controls.active -= 1; }
        },
        async close() { controls.closes += 1; },
      };
    },
  };
  return { provider, controls };
}

const BASE_BUILD = Object.freeze({ class: 'Synthetic', equipment: {}, skills: {}, effects: {} });

function createOptions(providerId, providerVersion, build = BASE_BUILD) {
  return {
    contractVersion: 'd4-rulekit-application/v1', providerId, providerVersion,
    snapshotId: 'synthetic-snapshot', snapshotManifestSha256: 'a'.repeat(64),
    buildSchemaVersion: 'synthetic-build/v1', build,
  };
}

module.exports = { BASE_BUILD, createOptions, makeStatefulProvider, makeStatelessProvider };
