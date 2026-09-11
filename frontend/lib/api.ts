// Authenticated API client — Option A: HttpOnly cookies only.
// Never store refresh tokens in localStorage; refresh is cookie-only.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function parseJson<T>(res: Response, path: string): Promise<T> {
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

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 401) {
    // Try one silent refresh (cookie rotation), then retry once.
    const r = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (r.ok) {
      const retry = await fetch(`${API_URL}${path}`, {
        ...init,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(init.headers ?? {}),
        },
      });
      if (!retry.ok) {
        const detail = await retry.text().catch(() => "");
        throw new Error(detail ? `API ${retry.status}: ${detail}` : `API ${retry.status}`);
      }
      return parseJson<T>(retry, path);
    }
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail ? `API ${res.status}: ${detail}` : `API ${res.status}`);
  }
  return parseJson<T>(res, path);
}

export async function login(email: string, password: string): Promise<{ access_token: string }> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(`Login ${res.status}`);
  // Response contains only short-lived access_token; refresh stays in HttpOnly cookie.
  return (await res.json()) as { access_token: string };
}
