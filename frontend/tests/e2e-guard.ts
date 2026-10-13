import { test, type APIRequestContext } from "@playwright/test";

// Fail-not-skip in CI: a missing backend/seed must turn CI red instead of
// silently skipping security-critical E2E. Locally, keep skip for ergonomics.
export async function requireLiveBackend(request: APIRequestContext, label: string) {
  const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const health = await request.get(`${API}/health`).catch(() => null);
  if (!health || !health.ok()) {
    if (process.env.CI) throw new Error(`${label} requires a live backend at ${API}`);
    test.skip(true, `${label} needs a live backend`);
  }
}

export async function requireOk(
  res: { ok(): boolean } | null | undefined,
  label: string,
) {
  if (!res || !res.ok()) {
    if (process.env.CI) throw new Error(`${label} failed in CI`);
    test.skip(true, label);
  }
}

export async function freshOwner(request: APIRequestContext, password:string):Promise<string>{
 const API=process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000";
 const email=`e2e-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
 const registered=await request.post(`${API}/auth/register`,{data:{email,password,invite_code:process.env.E2E_INVITE_CODE??"test-invite-code-123"}});
 if(!registered.ok())throw new Error(`Registration fixture failed ${registered.status()}`);
 const issued=await request.post(`${API}/auth/test-issue-verification`,{data:{email}});
 if(!issued.ok())throw new Error("Verification fixture failed");
 const {link}=await issued.json();
 const token=new URLSearchParams(new URL(link).hash.slice(1)).get("token");
 const verified=await request.post(`${API}/auth/verify-email`,{data:{token}});
 if(!verified.ok())throw new Error("Fixture verify failed");
 return email;
}
