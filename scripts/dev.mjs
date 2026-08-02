// Single orchestrator. Spawns the API, parses the chosen port from
// its stdout, then starts the frontend with `NEXT_PUBLIC_API_URL` set
// to that port. Replaces the old `concurrently --kill-others` chain —
// that one hard-crashed whenever the candidate port was held by a
// phantom Windows kernel socket, because each child exited 1 the
// moment their pre-checks disagreed.
//
// Behaviour:
//   - API's dev-api.mjs prints `[dev-api] binding to 127.0.0.1:<port>`
//     before launching uvicorn. We grep for that line and forward.
//   - When the API dies, we SIGTERM the web. When the web dies, we
//     SIGTERM the API. Whichever dies first triggers cleanup of the
//     other (matches the old `--kill-others` semantics).
//   - Ctrl+C forwards to both processes.

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..');

const PORT_REGEX = /\[dev-api\]\s+binding to 127\.0\.0\.1:(\d+)/;

function spawnWith(prefix, cmd, args, env = process.env, stdioMode = 'pipe') {
  // shell: true on Windows so paths with spaces & `.exe` resolution work
  // transparently. Stdio piped for the API so we can read its banner;
  // inherited for the web so Next.js colours / HMR output stay live.
  const stdio =
    stdioMode === 'inherit'
      ? 'inherit'
      : ['ignore', 'pipe', 'pipe'];
  return spawn(cmd, args, {
    cwd: repoRoot,
    env,
    shell: process.platform === 'win32',
    stdio,
    windowsHide: true,
  });
}

const api = spawnWith('api', 'node', ['scripts/dev-api.mjs']);
let apiPort = null;
let killed = false;

api.stdout.on('data', (chunk) => {
  const text = chunk.toString();
  process.stdout.write(text);
  if (apiPort === null) {
    const m = text.match(PORT_REGEX);
    if (m) {
      apiPort = m[1];
      console.log(`[dev] api bound to ${apiPort}, starting web…`);
      // Now spawn the web with the chosen port forwarded.
      const webEnv = {
        ...process.env,
        NEXT_PUBLIC_API_URL: `http://127.0.0.1:${apiPort}`,
      };
      const web = spawnWith('web', 'node', ['scripts/dev-web.mjs'], webEnv);
      wireChild('web', web);
    }
  }
});

api.stderr.on('data', (chunk) => {
  process.stderr.write(chunk);
});

api.on('exit', (code, signal) => {
  if (killed) return;
  console.log(`[dev] api exited (code=${code} signal=${signal})`);
  // API went first: ensure cleanup. If web is also running, it will
  // be cleaned by its own watcher when this process exits.
  cleanup(0);
});

let webChild = null;
function wireChild(name, child) {
  webChild = child;
  child.stdout.on('data', (d) => process.stdout.write(d));
  // Next.js sends HMR / progress lines to stderr too — don't colour them
  // in the orchestrator's stream; just relay.
  child.stderr.on('data', (d) => process.stderr.write(d));
  child.on('exit', (code, signal) => {
    if (killed) return;
    console.log(`[dev] ${name} exited (code=${code} signal=${signal})`);
    cleanup(0);
  });
}

function cleanup(code) {
  if (killed) return;
  killed = true;
  // Best-effort termination of whichever child is still alive.
  for (const c of [api, webChild]) {
    if (!c || c.exitCode !== null) continue;
    try { c.kill('SIGTERM'); } catch {}
  }
  // Give children a moment to flush logs, then exit.
  setTimeout(() => process.exit(code), 100);
}

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => cleanup(0));
}
