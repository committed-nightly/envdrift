// The npm `dotenv` package, resolved from the directory the file lives in so a
// project's own installed version is the one that answers.
'use strict';
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

function out(o) { process.stdout.write(JSON.stringify(o)); }

const target = process.argv[2];
const from = createRequire(path.join(path.resolve(path.dirname(target)), 'noop.js'));

// Whichever of the two resolvers actually found dotenv is the one that can
// answer for its version. Asking `from` after falling back to `require` gets
// null every time, because `from` is the one that just failed.
let dotenv;
let resolver = from;
try {
  dotenv = from('dotenv');
} catch (e) {
  try {
    dotenv = require('dotenv');
    resolver = require;
  } catch (e2) {
    out({ unavailable: 'the `dotenv` package does not resolve from ' + path.dirname(target) });
    process.exit(0);
  }
}

try {
  out({ values: dotenv.parse(fs.readFileSync(target)), version: versionOf(resolver) });
} catch (e) {
  out({ error: String((e && e.message) || e) });
}

function versionOf(req) {
  // dotenv's `exports` map does not expose package.json, so requiring it by
  // subpath fails on recent versions. Walk up from the resolved entry point.
  try {
    return req('dotenv/package.json').version;
  } catch (e) {
    try {
      let dir = path.dirname(req.resolve('dotenv'));
      for (let i = 0; i < 5; i++) {
        const candidate = path.join(dir, 'package.json');
        if (fs.existsSync(candidate)) {
          return JSON.parse(fs.readFileSync(candidate, 'utf8')).version || null;
        }
        const up = path.dirname(dir);
        if (up === dir) break;
        dir = up;
      }
    } catch (e2) {
      return null;
    }
    return null;
  }
}
