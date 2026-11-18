/** Observe the filesystem clock itself; Date.now() may be finer than inode time. */
import fs from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

export function readFileClock(source: fs.BigIntStats): bigint | undefined {
  // Windows ctime is creation time. An unavailable/different filesystem clock
  // keeps content confirmation; the policy's directory need not be writable.
  if (process.platform === 'win32') return undefined;
  const path = join(tmpdir(), 'hiitl-file-clock-' + randomUUID());
  let fd: number | undefined;
  try {
    fd = fs.openSync(path, 'wx', 0o600);
    fs.unlinkSync(path);
    const stamp = fs.fstatSync(fd, {bigint: true});
    return stamp.dev === source.dev ? stamp.ctimeNs : undefined;
  } catch {
    return undefined;
  } finally {
    if (fd !== undefined) {
      try { fs.closeSync(fd); } catch { /* The unavailable clock keeps content confirmation. */ }
      // Unlink can fail independently of opening; remove only this owned marker.
      try { if (fs.existsSync(path)) fs.unlinkSync(path); } catch { /* No new policy permission requirement. */ }
    }
  }
}
