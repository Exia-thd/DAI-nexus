#!/usr/bin/env node
console.warn("WARNING: dai-nexus-sync-projects.js has been moved to utilities/dai-nexus-sync-projects.js. This shim will be removed in the next release.");
const { spawn } = require('child_process');
const path = require('path');
const new_path = path.join(__dirname, "utilities/dai-nexus-sync-projects.js");
const child = spawn(process.execPath, [new_path, ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('exit', code => process.exit(code));
