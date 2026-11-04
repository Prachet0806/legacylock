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

// Establish the current release gate while leaving the journey's target
// beneficiary pending. That recipient can then accept the original invite
// after the vault is released, as the recovery specs intend.
export async function prepareReleaseEvidence(
  request: APIRequestContext,
  targetEmail: string,
  threshold: number,
): Promise<void> {
  const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const peopleResponse = await request.get(`${API}/beneficiaries`);
  await requireOk(peopleResponse, "list beneficiaries for release evidence");
  const people = await peopleResponse.json() as Array<{id:number; email:string; share_index:number|null}>;
  const target = people.find((person) => person.email.toLowerCase() === targetEmail.toLowerCase());
  if (!target) throw new Error("Release evidence target beneficiary was not found");
  if (target.share_index !== 1) {
    const assigned = await request.post(`${API}/beneficiaries/${target.id}/assign-share`, {data:{share_index:1}});
    await requireOk(assigned, "assign target recovery share");
  }

  for (let index = 2; index <= threshold + 1; index++) {
    const email = `e2e-ready-${Date.now()}-${index}@example.com`;
    const created = await request.post(`${API}/beneficiaries`, {
      data:{name:`E2E readiness ${index}`, email, share_index:index},
    });
    await requireOk(created, "create release-readiness beneficiary");
    const {id} = await created.json() as {id:number};
    const invited = await request.post(`${API}/beneficiaries/${id}/invite`);
    await requireOk(invited, "invite release-readiness beneficiary");
    const {invitation_link: link} = await invited.json() as {invitation_link:string};
    const token = new URLSearchParams(new URL(link).hash.slice(1)).get("token");
    if (!token) throw new Error("Release-readiness invite token missing");
    const accepted = await request.post(`${API}/access/invitation/accept`, {data:{token}});
    await requireOk(accepted, "accept release-readiness invitation");
  }

  const readinessResponse = await request.get(`${API}/vault/readiness`);
  await requireOk(readinessResponse, "read release readiness");
  const readiness = await readinessResponse.json() as {
    material_revision:number; assignment_signature:string; generation:string|null;
  };
  if (!readiness.generation) throw new Error("Current recovery ceremony generation missing");
  const drill = await request.post(`${API}/vault/drill`, {data:{
    material_revision:readiness.material_revision,
    assignment_signature:readiness.assignment_signature,
    generation:readiness.generation,
  }});
  await requireOk(drill, "record current owner-reported recovery drill");
}
