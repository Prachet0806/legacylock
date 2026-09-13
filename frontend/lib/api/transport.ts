// Shared transport: cookie-authenticated fetch + safe JSON parsing.
// No session logic here — see owner.ts / beneficiary.ts / public.ts.
//
// Same-origin by default: API calls go to relative /api/* and the edge
// (or Next dev rewrites) strips the prefix and forwards to the backend.
// Set NEXT_PUBLIC_API_URL to an absolute origin only for split-origin
// deployments (then cookies need SameSite=None; Secure — see DEPLOY.md).
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/$/, "");

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
    .then((detail) => new Error(detail ? `API ${res.status}: ${detail}` : `API ${res.status}`));
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
  const res = await rawFetch(path, init);
  if (res.status === 401) {
    const r = await fetch(`${API_URL}${refreshPath}`, {
      method: "POST",
      credentials: "include",
    });
    if (r.ok) {
      const retry = await rawFetch(path, init);
      if (!retry.ok) throw await errorFor(retry);
      return parseJson<T>(retry, path);
    }
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw await errorFor(res);
  return parseJson<T>(res, path);
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
