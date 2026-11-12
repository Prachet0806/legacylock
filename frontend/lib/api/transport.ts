// Shared transport: cookie-authenticated fetch + safe JSON parsing.
// No session logic here — see owner.ts / beneficiary.ts / public.ts.
//
// Same-origin by default: API calls go to relative /api/* and the edge
// (or Next dev rewrites) strips the prefix and forwards to the backend.
// Set NEXT_PUBLIC_API_URL to an absolute origin only for split-origin
// deployments (then cookies need SameSite=None; Secure — see DEPLOY.md).
import { assertEpoch, currentEpoch, lockVault } from "../crypto-session";
const API_URL = (process.env.NEXT_PUBLIC_API_URL?.trim() || "/api").replace(/\/$/, "");
const flights = new Map<string, Promise<void>>();
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly retryAfterSeconds: number | null = null,
  ) { super(message); this.name="ApiError"; }
}
let channel: BroadcastChannel | null = null;
type SessionPrincipal = "owner" | "beneficiary";
class SessionExpiredError extends Error {}

function sessionExpired(principal: SessionPrincipal, broadcast = true): void {
  lockVault();
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("legacylock-session-expired", { detail: principal }));
  if (broadcast) channel?.postMessage({ kind: "session-expired", principal });
}

export function sessionChanged(): void {
  lockVault();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("legacylock-session-changed"));
    channel?.postMessage({kind:"identity-changed"});
  }
}
if (typeof window !== "undefined" && typeof BroadcastChannel !== "undefined") {
  channel = new BroadcastChannel("legacylock-session");
  channel.onmessage = (event) => {
    if (event.data?.kind === "identity-changed") {
      lockVault();
      window.dispatchEvent(new Event("legacylock-session-changed"));
    } else if (event.data?.kind === "session-expired"
      && (event.data.principal === "owner" || event.data.principal === "beneficiary")) {
      sessionExpired(event.data.principal, false);
    }
  };
}

export async function parseJson<T>(res: Response, path: string): Promise<T> {
  // 204 No Content (deletes, wipes) carries no body — .json() would throw.
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`API ${res.status} (${path})`);
  }
}

export function errorFor(res: Response): Promise<Error> {
  const retryAfterHeader = res.headers.get("Retry-After");
  const retryAfterSeconds = retryAfterHeader && /^\d+$/.test(retryAfterHeader)
    ? Number(retryAfterHeader)
    : null;
  return res
    .text()
    .catch(() => "")
    .then((detail) => {
      try {
        const body=JSON.parse(detail);
        if(typeof body.detail === "string") {
          if (res.status === 429) return new ApiError(res.status, rateLimitMessage(retryAfterSeconds), retryAfterSeconds);
          return new ApiError(res.status, body.detail, retryAfterSeconds);
        }
      } catch { /* non-JSON failure gets the status fallback */ }
      return new ApiError(res.status, res.status === 429 ? rateLimitMessage(retryAfterSeconds) : `Request failed (${res.status})`, retryAfterSeconds);
    });
}

export function rateLimitMessage(seconds: number | null): string {
  if (seconds === null) return "Too many requests. Please wait a little and try again.";
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return `Too many requests. Please wait about ${minutes} minute${minutes === 1 ? "" : "s"} and try again.`;
}

export async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
}

/** Check for an owner cookie on the public entry page without expiring other tabs. */
export async function probeOwnerSession(): Promise<boolean> {
  const before = currentEpoch();
  const me = await rawFetch("/auth/me");
  if (before !== currentEpoch()) return false;
  if (me.ok) return true;
  if (me.status !== 401) return false;

  // A refresh cookie may still be valid after the access cookie expires. Use
  // the same browser lock as ownerFetch so another tab cannot rotate it first.
  const refresh = async () => {
    const current = await rawFetch("/auth/me");
    if (current.ok) return true;
    const response = await rawFetch("/auth/refresh", { method: "POST" });
    return response.ok;
  };
  try {
    const refreshed = typeof navigator !== "undefined" && navigator.locks
      ? await navigator.locks.request(
        "legacylock:/auth/refresh", { signal: AbortSignal.timeout(15000) }, refresh,
      )
      : await refresh();
    if (!refreshed || before !== currentEpoch()) return false;
    const verified = await rawFetch("/auth/me");
    return verified.ok && before === currentEpoch();
  } catch {
    return false;
  }
}

async function fetchWithRefresh<T>(
  path: string,
  init: RequestInit,
  refreshPath: string,
): Promise<T> {
  const before=currentEpoch();
  const res = await rawFetch(path, init);
  assertEpoch(before);
  if (res.status === 401) {
    const detail = await res.clone().json().catch(() => ({}));
    if (detail.detail === "Invalid password") throw await errorFor(res);
    let flight = flights.get(refreshPath);
    if (!flight) {
      const refresh = async () => {
        const probe = await rawFetch(refreshPath === "/auth/refresh" ? "/auth/me" : "/access/status");
        if (probe.ok) return;
        const r = await rawFetch(refreshPath, {method:"POST"});
        if (!r.ok) {
          if (r.status === 429) throw await errorFor(r);
          if (r.status === 401) throw new SessionExpiredError("Sign in again");
          throw new Error("Sign in again");
        }
      };
      flight = (typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request(`legacylock:${refreshPath}`, {signal:AbortSignal.timeout(15000)}, refresh)
        : refresh()).finally(() => flights.delete(refreshPath));
      flights.set(refreshPath, flight);
    }
    try { await flight; } catch (e) {
      if (e instanceof SessionExpiredError) {
        sessionExpired(refreshPath === "/auth/refresh" ? "owner" : "beneficiary");
      }
      throw e;
    }
    assertEpoch(before);
    const retry = await rawFetch(path, init);
    assertEpoch(before);
    if (!retry.ok) throw await errorFor(retry);
    const body = await parseJson<T>(retry, path);
    assertEpoch(before);
    return body;
  }
  if (!res.ok) throw await errorFor(res);
  const body = await parseJson<T>(res, path);
  assertEpoch(before);
  return body;
}

/** Owner session: silent retry via the owner refresh cookie. */
export function ownerFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  return fetchWithRefresh<T>(path, init, "/auth/refresh");
}

/** Beneficiary session: silent retry via the beneficiary refresh cookie.
 *  Never touches the owner refresh endpoint. */
export function beneficiaryFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  return fetchWithRefresh<T>(path, init, "/access/session");
}

/** Public endpoints and auth bootstraps: no retry. */
export async function publicFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await rawFetch(path, init);
  if (!res.ok) throw await errorFor(res);
  return parseJson<T>(res, path);
}
