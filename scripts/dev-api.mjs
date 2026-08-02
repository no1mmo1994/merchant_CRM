// Spawn uvicorn on the first free port from the candidate list, then
// forward signals. Replaces the old `check-port.mjs && cd && uvicorn`
// chain — that hard-failed when the preferred port was held by a
// phantom Windows kernel socket.
//
// Emits `[dev-api] listening on http://127.0.0.1:<port>` so the
// caller (dev:dev orchestrator or a human) can pick up the chosen
// port from the output stream.

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const repoRoot = path.resolve(__dirname, '..');
const apiDir = path.join(repoRoot, 'services', 'api');

const candidates = (process.env.PULSEORDER_API_PORT_CANDIDATES || '8123,8124,8125')
  .split(',')
  .map((s) => Number(s.trim()))
  .filter((n) => Number.isInteger(n) && n > 0 && n <= 65535);

if (!candidates.length) {
  console.error('[dev-api] PULSEORDER_API_PORT_CANDIDATES produced no valid ports');
  process.exit(2);
}

function tryBind(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.once('error', () => resolve(null));
    srv.listen(port, '127.0.0.1', () => {
      const addr = srv.address();
      const chosen = typeof addr === 'object' && addr ? addr.port : port;
      srv.close(() => resolve(chosen));
    });
  });
}

let chosenPort = null;
for (const p of candidates) {
  const bound = await tryBind(p);
  if (bound !== null) {
    chosenPort = bound;
    break;
  }
}
if (chosenPort === null) {
  console.error(`[dev-api] none of [${candidates.join(', ')}] are free on 127.0.0.1`);
  process.exit(1);
}

console.log(`[dev-api] binding to 127.0.0.1:${chosenPort} (candidates: ${candidates.join(', ')})`);

// uvicorn already restarts the worker on reload — we don't need
// forever-process behaviour for the wrapper itself.
const child = spawn(
  'uv',
  [
    'run',
    'uvicorn',
    'app.main:app',
    '--reload',
    '--host',
    '127.0.0.1',
    '--port',
    String(chosenPort),
  ],
  {
    cwd: apiDir,
    stdio: 'inherit',
    shell: process.platform === 'win32',
    env: {
      ...process.env,
      PULSEORDER_API_PORT: String(chosenPort),
    },
  }
);

const forward = (sig) => {
  try { child.kill(sig); } catch {}
};
process.on('SIGINT', () => forward('SIGINT'));
process.on('SIGTERM', () => forward('SIGTERM'));

child.on('exit', (code, signal) => {
  if (signal) {
    console.log(`[dev-api] uvicorn terminated by ${signal}`);
    process.exit(0);
  }
  process.exit(code ?? 0);
});
