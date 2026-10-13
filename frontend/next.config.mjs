/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";
// The HTML CSP is generated per request by middleware.ts with a nonce.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },

];

const nextConfig = {
  output: "standalone",
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Proxy same-origin /api/* to the backend so the
  // app can use relative API URLs. Production terminates this at the edge.
  // Falls back to localhost:8000 so plain `npm run dev` (empty
  // NEXT_PUBLIC_API_URL) still proxies instead of looping back onto itself.
  async rewrites() {
    const target = process.env.API_UPSTREAM || (isDev ? "http://localhost:8000" : "");
    if (!target) return [];
    return [{ source: "/api/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;
