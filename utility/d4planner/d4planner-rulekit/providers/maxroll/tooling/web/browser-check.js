#!/usr/bin/env node
'use strict';
// Retain the established environment-based entrypoint; export-check verifies real downloads.
const {run}=require('./export-check');
const config={url:process.env.LOCAL_EDITOR_URL,evidenceDir:process.env.LOCAL_EDITOR_EVIDENCE,chromium:process.env.CHROMIUM_EXECUTABLE};
if(Object.values(config).some(v=>!v))throw Error('Set LOCAL_EDITOR_URL, LOCAL_EDITOR_EVIDENCE and CHROMIUM_EXECUTABLE');
run(config).catch(error=>{console.error(error);process.exitCode=1;});
