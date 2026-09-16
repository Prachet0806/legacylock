// Owner auth bootstrap (public endpoints, no retry).
import { publicFetch } from "./transport";

export async function login(email: string, password: string): Promise<void> {
  await publicFetch<void>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  // Session lives in HttpOnly cookies only; the body carries no tokens.
}

export async function register(
  email: string,
  password: string,
  inviteCode: string,
): Promise<{ message: string }> {
  return publicFetch<{ message: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, invite_code: inviteCode }),
  });
}

export async function verifyEmail(token: string): Promise<{ message: string }> {
  return publicFetch<{ message: string }>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function resendVerification(email: string): Promise<{ message: string }> {
  return publicFetch<{ message: string }>("/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}
