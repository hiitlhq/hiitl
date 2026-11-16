#!/usr/bin/env node
/**
 * Stale-build guard for the SDK package (TICKET-105).
 *
 * The SDK depends on `@hiitl/core` via a `file:../core` reference in
 * package.json. npm symlinks that to `node_modules/@hiitl/core`, and
 * the core package's `main` points to `dist/index.js` — so the SDK
 * always imports the BUILT artifacts, not the source.
 *
 * Before TICKET-105 this caused a subtle trap: developers would edit
 * core source, run `npm test` in the SDK, and see tests fail against
 * a stale dist from a prior build. We fixed that by un-tracking the
 * dist directory from git (it's already in `.gitignore`); this script
 * adds a workflow guard so a stale-or-missing dist now fails the
 * SDK's tests with a clear, actionable error instead of a confusing
 * Zod validation failure on a fixture.
 *
 * Algorithm:
 *   1. Check that core/dist/index.js exists. If not → fail with build instruction.
 *   2. Find the newest mtime under core/src/.
 *   3. Find the newest mtime under core/dist/.
 *   4. If any source file is newer than the newest dist file → fail.
 *
 * Exit 0 = dist is fresh; non-zero = fail with diagnostic.
 */

import { readdirSync, statSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const corePackageRoot = resolve(__dirname, '..', '..', 'core');
const coreDist = join(corePackageRoot, 'dist');
const coreSrc = join(corePackageRoot, 'src');
const coreEntry = join(coreDist, 'index.js');

/** Walk a directory recursively and return the newest mtime in ms. */
function newestMtimeMs(dir) {
  let newest = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      newest = Math.max(newest, newestMtimeMs(fullPath));
    } else {
      newest = Math.max(newest, statSync(fullPath).mtimeMs);
    }
  }
  return newest;
}

function fail(msg) {
  console.error('\n[check-core-dist] FAIL: ' + msg);
  console.error('\nFix:');
  console.error('  cd ../core && npm run build');
  console.error('\nThen re-run your SDK command.\n');
  process.exit(1);
}

// 1. dist must exist.
if (!existsSync(coreEntry)) {
  fail(
    'core/dist/index.js is missing. The SDK package imports @hiitl/core via ' +
      'a file: symlink, and core publishes its built dist. You need to build ' +
      'core at least once before running SDK tests.'
  );
}

// 2 + 3 + 4. Compare source vs dist freshness. We compare directory-wide
// max-mtime rather than per-file because TypeScript compiles all files
// together — if even one source file is newer than the newest dist file,
// the whole dist is suspect.
const srcMtime = newestMtimeMs(coreSrc);
const distMtime = newestMtimeMs(coreDist);

if (srcMtime > distMtime) {
  const lagSec = Math.round((srcMtime - distMtime) / 1000);
  fail(
    `core/dist is older than core/src (by ${lagSec}s). Someone edited core ` +
      `source after the last build; SDK tests would run against stale code.`
  );
}
