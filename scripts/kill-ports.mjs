// Usage: node scripts/kill-ports.mjs <port> [<port> ...]
//
// Frees each candidate port by taskkill-ing its owning PID(s). Skips
// PIDs that no longer exist (Windows kernel sometimes keeps a phantom
// LISTEN entry for a process that exited — `taskkill` reports "not
// found" and the socket remains held until the next TCP time-wait
// grace period ends; that's normal and not actionable from here).
//
// Always removes the stale Next dev `.next/dev/lock` so a hard-killed
// `next dev` doesn't block the next start.

import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

function pidAlive(pid) {
  if (process.platform === 'win32') {
    // /fi "PID eq <pid>" /fo csv  →  one row if alive, none if not.
    const r = spawnSync(
      'tasklist',
      ['/fi', `PID eq ${pid}`, '/fo', 'csv'],
      { encoding: 'utf8', shell: true }
    );
    return !!r.stdout && r.stdout.includes(`"${pid}"`);
  }
  try { process.kill(pid, 0); return true; }
  catch { return false; }
}

function killPid(pid) {
  if (process.platform === 'win32') {
    const r = spawnSync(
      'taskkill',
      ['/PID', String(pid), '/F', '/T'],
      { stdio: 'inherit', shell: true }
    );
    return r.status === 0;
  }
  try { process.kill(pid, 'SIGKILL'); return true; }
  catch { return false; }
}

function ownersOf(port) {
  if (process.platform !== 'win32') return [];
  // netstat -ano gives one row per listening socket. The owning PID is
  // the last whitespace-delimited column.
  const out = spawnSync('netstat', ['-ano'], { encoding: 'utf8' }).stdout || '';
  const pids = new Set();
  for (const line of out.split(/\r?\n/)) {
    if (!line.includes(`127.0.0.1:${port}`)) continue;
    if (!line.includes('LISTENING')) continue;
    const parts = line.trim().split(/\s+/);
    const m = parts[parts.length - 1];
    if (m && /^\d+$/.test(m)) pids.add(Number(m));
  }
  return [...pids];
}

for (const raw of process.argv.slice(2)) {
  const port = Number(raw);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    console.error(`[kill-ports] invalid port: ${raw}`);
    continue;
  }
  const pids = ownersOf(port);
  if (!pids.length) {
    console.log(`[kill-ports] port ${port} is free (or held by a phantom socket)`);
    continue;
  }
  const live = pids.filter(pidAlive);
  const ghosts = pids.filter((p) => !live.includes(p));
  if (live.length) {
    console.log(`[kill-ports] freeing port ${port} (PIDs ${live.join(', ')})`);
    for (const p of live) killPid(p);
  } else {
    console.log(
      `[kill-ports] port ${port} is held by ${ghosts.length} phantom PID(s); ` +
        `Windows will release these within a few minutes. Continuing.`
    );
  }
}

// Always clear the stale Next dev lock — it can prevent the next `pnpm
// dev:web` from starting even after the port is free.
const lock = join(process.cwd(), 'apps', 'web', '.next', 'dev', 'lock');
if (existsSync(lock)) {
  let pid = null;
  try {
    pid = JSON.parse(readFileSync(lock, 'utf8'))?.pid;
  } catch {}
  if (pid && pidAlive(pid)) {
    killPid(pid);
    console.log(`[kill-ports] killed stale Next dev PID ${pid}`);
  } else {
    console.log(
      `[kill-ports] removed stale Next dev lock (was PID ${pid ?? '?'})`
    );
  }
  try { unlinkSync(lock); } catch {}
}