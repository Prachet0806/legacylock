// Owner login bootstrap (public endpoint, no retry).
import { publicFetch } from "./transport";

export async function login(email: string, password: string): Promise<void> {
  await publicFetch<void>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  // Session lives in HttpOnly cookies only; the body carries no tokens.
}
