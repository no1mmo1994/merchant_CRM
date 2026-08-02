// Usage: node scripts/find-free-port.mjs <preferredPort> [<fallback1> <fallback2> ...]
//
// Returns the first port that we can bind a *listening* socket on. A
// purely-in-use port reports `EADDRINUSE` when the *server* tries to
// bind it. That's the only signal that matters — connect() to that port
// also succeeds, so `check-port.mjs` can't tell the difference between
// "my dev server is already running" and "Windows still owns a phantom
// socket for a process that's long gone".
//
// Prints the chosen port on stdout so the calling shell script can
// capture it (`set "API_PORT=$(node scripts/find-free-port.mjs 8123 8124 8125)"`).
//
// Exit codes:
//   0 → found a free port (printed on stdout)
//   1 → all candidate ports are in use
//   2 → invalid args

import net from 'node:net';

const candidates = process.argv.slice(2).map((s) => {
  const n = Number(s);
  if (!Number.isInteger(n) || n <= 0 || n > 65535) {
    console.error(`[find-free-port] invalid port: ${s}`);
    process.exit(2);
  }
  return n;
});

if (!candidates.length) {
  console.error('[find-free-port] no candidate ports given');
  process.exit(2);
}

const host = '127.0.0.1';

async function tryBind(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.once('error', () => resolve(null));
    srv.listen(port, host, () => {
      const chosenPort = srv.address().port;
      srv.close(() => resolve(chosenPort));
    });
  });
}

for (const p of candidates) {
  const bound = await tryBind(p);
  if (bound !== null) {
    console.log(String(bound));
    process.exit(0);
  }
}

console.error(
  `[find-free-port] none of [${candidates.join(', ')}] are free on ${host}`
);
process.exit(1);
