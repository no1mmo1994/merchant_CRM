// Recover from a stale `.next/dev/lock` (left behind by a hard-killed
// `next dev`), then spawn Next.js dev with the chosen Turbopack root.
//
// Why we *only* trust an alive `next dev` PID:
//   - A hard kill (Ctrl+C during reload, OOM, etc.) leaves a JSON lock
//     pointing at a PID that no longer exists OR has been recycled by
//     Windows to a totally unrelated process. taskkill /F on a recycled
//     PID is the fastest way to crash your editor, AV client, or even
//     the system tray.
//   - We verify the candidate PID is alive AND its parent command line
//     contains "next dev" before killing it. Anything else (no PID, or
//     a different process using the same PID) just deletes the lock
//     and lets Next.js create a fresh one.

import { readFileSync, existsSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

const repoRoot = process.cwd();
const lock = join(repoRoot, 'apps', 'web', '.next', 'dev', 'lock');

function isNextDevPid(pid) {
  // wmic is gone on modern Windows; use tasklist /v and grep for the
  // PID. The ImageName column will be "node.exe" — verify the window
  // title or command-line equivalent contains "next dev".
  if (process.platform !== 'win32') {
    // POSIX: `ps -p <pid> -o args=`
    const r = spawnSync('ps', ['-p', String(pid), '-o', 'args='], {
      encoding: 'utf8',
    });
    return r.stdout && /next\s+dev/.test(r.stdout);
  }
  // Windows: tasklist /v /fi "PID eq <pid>" /fo csv
  const r = spawnSync(
    'tasklist',
    ['/v', '/fi', `PID eq ${pid}`, '/fo', 'csv'],
    { encoding: 'utf8', shell: true }
  );
  if (!r.stdout) return false;
  // Format: "node.exe","1234","Console","1","12,345 K","Host Name","title"
  // The "title" column often contains "node.exe next dev" on Windows.
  const lines = r.stdout.split(/\r?\n/).filter((l) => l.includes(`"${pid}"`));
  if (!lines.length) return false;
  return /next\s+dev/i.test(lines.join('\n'));
}

function killPid(pid) {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/F', '/T'], {
      stdio: 'inherit',
      shell: true,
    });
  } else {
    try { process.kill(pid, 'SIGKILL'); } catch {}
  }
}

if (existsSync(lock)) {
  let pid = null;
  try {
    const parsed = JSON.parse(readFileSync(lock, 'utf8'));
    pid = Number(parsed?.pid);
  } catch {
    // malformed lock — just unlink it.
  }
  if (pid && Number.isInteger(pid) && pid > 0 && isNextDevPid(pid)) {
    console.log(`[dev-web] killing stale next dev PID ${pid}`);
    killPid(pid);
  } else {
    console.log(
      `[dev-web] lock is stale (pid=${pid ?? '?'} is not a live next dev) — discarding`
    );
  }
  try { unlinkSync(lock); } catch {}
}

// Forward signals to the child. On Windows + pnpm, the chain is:
//   node dev-web.mjs → pnpm --filter web dev → node next/dist/.../cli.js dev
// SIGINT propagates through pnpm automatically. SIGTERM is less reliable.
const child = spawn('pnpm', ['--filter', 'web', 'dev'], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

process.on('SIGINT', () => { try { child.kill('SIGINT'); } catch {} });
process.on('SIGTERM', () => { try { child.kill('SIGTERM'); } catch {} });
child.on('exit', (code) => process.exit(code ?? 0));