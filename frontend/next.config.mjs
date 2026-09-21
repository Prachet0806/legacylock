/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";
// Absolute API origin only for split-origin deploys; same-origin (default)
// is covered by 'self'.
const apiOrigin = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const connectSrc = apiOrigin ? `connect-src 'self' ${apiOrigin}` : "connect-src 'self'";

// Mirrors backend SecurityHeadersMiddleware for the API; these protect the
// rendered HTML document itself (CSP/frame-ancestors are meaningless on JSON).
// Next.js requires 'unsafe-inline' scripts (inline bootstrap) and, in dev
// only, 'unsafe-eval' (webpack devtool) — without them the app cannot hydrate.
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      scriptSrc,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      connectSrc,
      "frame-ancestors 'none'",
    ].join("; "),
  },
];

const nextConfig = {
  output: "standalone",
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Local dev (and only dev): proxy same-origin /api/* to the backend so the
  // app can use relative API URLs. Production terminates this at the edge.
  // Falls back to localhost:8000 so plain `npm run dev` (empty
  // NEXT_PUBLIC_API_URL) still proxies instead of looping back onto itself.
  async rewrites() {
    if (!isDev) return [];
    const target = apiOrigin || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;
