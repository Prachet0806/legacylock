/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";
function httpsOrigin(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:"
      && !parsed.username && !parsed.password
      && parsed.pathname === "/" && !parsed.search && !parsed.hash
      && !["example.com", "localhost", "127.0.0.1"].includes(parsed.hostname)
      && !parsed.hostname.endsWith(".example.com")
      ? parsed.origin : null;
  } catch { return null; }
}
// The HTML CSP is generated per request by middleware.ts with a nonce.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },

];

const nextConfig = {
  output: "standalone",
  // The repository root contains Neon CLI configuration and a separate
  // package manifest; keep frontend tracing scoped to this Next.js app.
  outputFileTracingRoot: process.cwd(),
  devIndicators: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Proxy same-origin /api/* to the backend so the
  // app can use relative API URLs. Production terminates this at the edge.
  // Falls back to localhost:8000 so plain `npm run dev` (empty
  // NEXT_PUBLIC_API_URL) still proxies instead of looping back onto itself.
  async rewrites() {
    const preview = process.env.VERCEL === "1" && process.env.VERCEL_ENV === "preview";
    const target = preview
      ? process.env.PREVIEW_API_UPSTREAM
      : process.env.API_UPSTREAM || (isDev ? "http://localhost:8000" : "");
    if (process.env.VERCEL === "1") {
      if ((process.env.NEXT_PUBLIC_API_URL || "/api") !== "/api") {
        throw new Error("Vercel requires same-origin NEXT_PUBLIC_API_URL=/api");
      }

      // An absent API origin supports an initial frontend-only deployment.
      // Validate routing when configured so placeholder or insecure origins
      // cannot silently ship in a Vercel build.
      if (target && !httpsOrigin(target)) {
        throw new Error("API upstream must be a valid deployed HTTPS origin");
      }

      if (preview && target) {
        const productionTarget = httpsOrigin(process.env.PRODUCTION_API_UPSTREAM || "");
        if (!productionTarget || httpsOrigin(target) === productionTarget) {
          throw new Error("Preview must use an isolated API origin distinct from production");
        }
      }
    }
    if (!target) return [];
    return [{ source: "/api/:path*", destination: `${target.replace(/\/$/, "")}/:path*` }];
  },
};

export default nextConfig;
