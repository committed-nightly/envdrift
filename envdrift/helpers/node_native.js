// Node's built-in .env parser (util.parseEnv, Node >= 20.12).
// Prints {"values": {...}} or {"error": "..."} on stdout, always exit 0.
'use strict';
const fs = require('fs');
const util = require('util');

function out(o) { process.stdout.write(JSON.stringify(o)); }

if (typeof util.parseEnv !== 'function') {
  out({ unavailable: 'this Node has no util.parseEnv (needs Node >= 20.12)' });
  process.exit(0);
}

try {
  out({ values: util.parseEnv(fs.readFileSync(process.argv[2], 'utf8')) });
} catch (e) {
  out({ error: String((e && e.message) || e) });
}
