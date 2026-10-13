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
  constructor(public readonly status: number, message: string) { super(message); this.name="ApiError"; }
}
let channel: BroadcastChannel | null = null;
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
  return res
    .text()
    .catch(() => "")
    .then((detail) => {
      try {
        const body=JSON.parse(detail);
        if(typeof body.detail === "string") return new ApiError(res.status, body.detail);
      } catch { /* non-JSON failure gets the status fallback */ }
      return new ApiError(res.status, `Request failed (${res.status})`);
    });
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
        if (!r.ok) throw new Error("Sign in again");
      };
      flight = (typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request(`legacylock:${refreshPath}`, {signal:AbortSignal.timeout(15000)}, refresh)
        : refresh()).finally(() => flights.delete(refreshPath));
      flights.set(refreshPath, flight);
    }
    try { await flight; } catch (e) { sessionChanged(); throw e; }
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
