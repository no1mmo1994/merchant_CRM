import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow remote images for menu items (Phase 07+).
  // Default: only allow same-origin + Grab CDN.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.grab.com" },
      { protocol: "https", hostname: "**.cloudfront.net" },
    ],
  },
  // Next.js 16 blocks cross-origin requests to dev resources by default.
  // PulseOrder uses 127.0.0.1 (binding required for local mode) but
  // HMR / RSC payloads need to be reachable from that host. Whitelist it.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Pin Turbopack's workspace root to grab-dashboard/ so it uses the
  // monorepo root (apps/web is one level deeper than the root that has
  // pnpm-workspace.yaml + package.json).  Next.js dev runs from apps/web,
  // so "../.." climbs to grab-dashboard/.  Turbopack complains if `root`
  // isn't absolute; pass.resolve gives us an absolute path regardless of
  // the platform shell.
  turbopack: {
    root: path.resolve(__dirname, "..", ".."),
  },
  // Proxy /api/* to the FastAPI dev server so the browser sees a
  // same-origin request. This eliminates the CORS preflight and the
  // `localhost` ⇄ `127.0.0.1` cookie mismatch that masked the cross-port
  // dev server before. `apps/web/lib/api.ts` uses an empty base URL when
  // it detects this rewrite is in effect; the fallback to
  // NEXT_PUBLIC_API_URL preserves the old direct-call path for production
  // builds where the proxy is not set up.
  async rewrites() {
    // Port 8000 (overriding the historical 8124 default) is the canonical
    // FastAPI dev server this repo now expects — earlier session compiles
    // left multiple stale API instances on 8123/8124/8125/8126/8129/8130
    // bound from old uvicorn reloaders, and Next.js' proxy would get
    // "socket hang up" intermittently when its upstream pool grabbed a
    // process that was tearing down.  Pointing the rewrite at a single,
    // freshly-started 8000 instance eliminates the multi-upstream race.
    // `process.env.NEXT_PUBLIC_API_URL` still wins for production deploys
    // where the proxy is not used.
    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
