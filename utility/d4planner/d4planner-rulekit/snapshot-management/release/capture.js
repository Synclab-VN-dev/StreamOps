'use strict';
// Capture logs are not a wire protocol. Persist the exact report separately.
const fs = require('node:fs/promises');
async function capture(configFile, reportFile, run = require('../../providers/maxroll/tooling/capture-workflow').run) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  for (const signal of ['SIGINT','SIGTERM','SIGHUP']) process.once(signal, abort);
  try {
    const report = await run({mode:'all', config:configFile, signal:controller.signal});
    await fs.writeFile(reportFile, JSON.stringify(report), {flag:'wx',mode:0o600});
  } catch(error) {
    if (error.report) await fs.writeFile(reportFile, JSON.stringify(error.report), {flag:'wx',mode:0o600});
    throw error;
  } finally {
    for (const signal of ['SIGINT','SIGTERM','SIGHUP']) process.removeListener(signal, abort);
  }
}
if (require.main === module) capture(process.argv[2],process.argv[3]).catch(() => {
  process.stderr.write('BLOCKED_CAPTURE\n');process.exitCode=2;
});
module.exports = {capture};
