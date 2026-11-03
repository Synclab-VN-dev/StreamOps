'use strict';
// Real IPC/HTTP lifecycle with a synthetic calculation provider; never native UI evidence.
const {createComposition: calculation} = require('./rulekit-test-composition');
const {fromEnvironment} = require('../../../d4planner-rulekit/providers/maxroll/tooling/planner/manager');
exports.createComposition = async env => {
  const composition = await calculation(env), planner = fromEnvironment(env);
  if (env.TEST_PLANNER_DELAY_MS) {
    const load = planner.load;
    planner.load = async config => {await new Promise(resolve => setTimeout(resolve, Number(env.TEST_PLANNER_DELAY_MS))); return load(config);};
  }
  return {...composition, planner: {ensureReady: options => planner.ensureReady(options)},
    close: async () => {try {await planner.close();} finally {await composition.close?.();}}};
};
