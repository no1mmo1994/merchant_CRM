// Usage: node scripts/check-port.mjs <port>
import net from 'node:net';

const port = Number(process.argv[2]);
if (!Number.isInteger(port) || port <= 0 || port > 65535) {
  console.error(`[check-port] invalid port: ${process.argv[2]}`);
  process.exit(2);
}

const probe = net.createConnection({ host: '127.0.0.1', port, timeout: 300 });
probe.on('connect', () => {
  probe.destroy();
  console.error(`[check-port] port ${port} is already in use on 127.0.0.1. Run 'pnpm dev:fix' to free it.`);
  process.exit(1);
});
probe.on('error', () => process.exit(0));
probe.on('timeout', () => { probe.destroy(); process.exit(0); });