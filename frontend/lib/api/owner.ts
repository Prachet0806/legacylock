// Owner-session API wrappers — mirrors backend owner routers.
import { ownerFetch, publicFetch, sessionChanged } from "./transport";

// --- auth ---
export interface MeOut {
  id: number;
  email: string;
  email_verified?: boolean;
}
export const getMe = () => ownerFetch<MeOut>("/auth/me");
export const logout = async () => {
  sessionChanged();
  try { return await publicFetch<{ message: string }>("/auth/logout", { method: "POST" }); }
  finally { sessionChanged(); }
};

// --- vault messages ---
export interface MessageMeta {
  id: number;
  label: string;
  created_at: string;
  category?: string | null;
}
export interface MessageDetail {
  id: number;
  label: string;
  ciphertext: string;
  wrapped_mek: string;
  crypto_version: number;
  // Canonical shape: the IV lives inside crypto_metadata ({ iv }).
  crypto_metadata: Record<string, unknown>;
  created_at: string;
  category?: string | null;
  coverage_tags?: string[];
}

export const listMessages = (beforeId?: number) => ownerFetch<MessageMeta[]>(`/vault/messages?limit=50${beforeId ? `&before_id=${beforeId}` : ""}`);
export const getMessage = (id: number) => ownerFetch<MessageDetail>(`/vault/messages/${id}`);

/** IV lives inside crypto_metadata ({ iv: base64 }). Empty string if absent. */
export function ivOf(meta: Record<string, unknown> | null | undefined): string {
  const iv = meta?.iv;
  return typeof iv === "string" ? iv : "";
}
export const createMessage = (body: {
  material_revision: number;
  label: string;
  ciphertext: string;
  wrapped_mek: string;
  crypto_version?: number;
  crypto_metadata?: Record<string, unknown>;
  category?: string | null;
  coverage_tags?: string[];
}) =>
  ownerFetch<{ id: number }>("/vault/messages", { method: "POST", body: JSON.stringify(body) });
export const deleteMessage = (id: number) =>
  ownerFetch<void>(`/vault/messages/${id}`, { method: "DELETE" });

// --- crypto material (wrapped only) ---
export interface CryptoMaterial {
  material_revision: number;
  wrapped_vmk: string | null;
  vmk_crypto_version: number | null;
  vmk_kdf_algorithm: string | null;
  vmk_kdf_salt: string | null;
  vmk_kdf_parameters: { iterations: number } | null;
}
export const getCryptoMaterial = () => ownerFetch<CryptoMaterial>("/vault/crypto-material");
export const putCryptoMaterial = (body: {
  expected_revision: number;
  wrapped_vmk: string;
  vmk_crypto_version: 1;
  vmk_kdf_algorithm: "PBKDF2-SHA256";
  vmk_kdf_salt: string;
  vmk_kdf_parameters: { iterations: number };
}) => ownerFetch<{ message: string }>("/vault/crypto-material", { method: "PUT", body: JSON.stringify(body) });

// --- recovery policy + ceremony (per-vault Shamir k-of-n) ---
export interface RecoveryPolicy {
  ceremony_id?: number;
  material_revision?: number;
  recovery_threshold: number;
  recovery_total: number;
  recovery_generation?: string | null;
  recovery_status?: string;
}
export const getRecoveryPolicy = () => ownerFetch<RecoveryPolicy>("/vault/recovery-policy");
export interface Readiness {
  initialized:boolean; material_revision:number; ceremony_status:string; generation:string|null;
  threshold:number; total:number; eligible_assignments:number; quorum_assigned:boolean;
  assignment_signature:string; armed:boolean; owner_reported_drill:{reported_at:string}|null;
  independently_verified_possession:boolean;
}
export const getReadiness = () => ownerFetch<Readiness>("/vault/readiness");
export const reportDrill = (body:{material_revision:number;assignment_signature:string;generation:string}) => ownerFetch<{message:string}>("/vault/drill", {method:"POST",body:JSON.stringify(body)});
export const putRecoveryPolicy = (body: { recovery_threshold: number; recovery_total: number }) =>
  ownerFetch<RecoveryPolicy>("/vault/recovery-policy", { method: "PUT", body: JSON.stringify(body) });
export const postRecoveryCeremony = (body: {
  expected_revision: number;
  initial_material?: Parameters<typeof putCryptoMaterial>[0];
  recovery_threshold: number;
  recovery_total: number;
  recovery_generation: string;
}) => ownerFetch<RecoveryPolicy>("/vault/recovery-ceremony", { method: "POST", body: JSON.stringify(body) });

export const finalizeCeremony = (id: number, stored_indexes: number[]) => ownerFetch<{material_revision: number}>(`/vault/recovery-ceremony/${id}/finalize`, {method:"POST", body:JSON.stringify({stored_indexes})});
export const cancelCeremony = (id: number) => ownerFetch<{message: string}>(`/vault/recovery-ceremony/${id}`, {method:"DELETE"});

// --- vault status / trigger ---
export interface VaultStatus {
  status: string;
  grace_started_at: string | null;
  triggered_at: string | null;
  updated_at: string;
  recovery_threshold?: number;
  recovery_total?: number;
  release_hold: boolean;
  armed: boolean;
}
export const getVaultStatus = () => ownerFetch<VaultStatus>("/vault/status");
export const manualTrigger = (password: string, confirm: true) =>
  ownerFetch<{ message: string; triggered_at: string }>("/vault/trigger", {
    method: "POST",
    body: JSON.stringify({ password, confirm }),
  });

// --- beneficiaries ---
export interface Beneficiary {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  share_index: number | null;
  assignment_current: boolean;
  invitation_status: string;
  invitation_sent_at: string | null;
  invitation_accepted_at: string | null;
  created_at: string;
}
export const listBeneficiaries = () => ownerFetch<Beneficiary[]>("/beneficiaries");
export const addBeneficiary = (body: { name: string; email: string; phone?: string }) =>
  ownerFetch<{ id: number }>("/beneficiaries", { method: "POST", body: JSON.stringify(body) });
export const deleteBeneficiary = (id: number) =>
  ownerFetch<void>(`/beneficiaries/${id}`, { method: "DELETE" });
export const inviteBeneficiary = (id: number) =>
  ownerFetch<{ invitation_link: string; beneficiary_id: number }>(`/beneficiaries/${id}/invite`, {
    method: "POST",
  });
export const assignShare = (beneficiaryId: number, share_index: number) =>
  ownerFetch<{ message: string; share_index: number }>(
    `/beneficiaries/${beneficiaryId}/assign-share`,
    { method: "POST", body: JSON.stringify({ share_index }) },
  );

// --- heartbeat ---
// NOTE: the API has no next_deadline field; compute it client-side as
// last_check_in + interval_days. PUT returns {message}, not the config.
export interface HeartbeatConfig {
  interval_days: number;
  grace_days: number;
  last_check_in: string | null;
  updated_at?: string;
}
export const getHeartbeat = () => ownerFetch<HeartbeatConfig>("/heartbeat");
export const putHeartbeat = (body: { interval_days: number; grace_days: number }) =>
  ownerFetch<{ message: string }>("/heartbeat", { method: "PUT", body: JSON.stringify(body) });
export const checkin = () => ownerFetch<{ message: string; last_check_in?: string }>("/heartbeat/checkin", { method: "POST" });
// Test driver only: backend 404s in production. Runs the checker synchronously
// with simulated elapsed days (time travel for auto-trigger E2E).
export const runHeartbeatCheck = (advance_days: number) =>
  ownerFetch<{ actions: string[]; simulated_now: string }>("/heartbeat/run-check", {
    method: "POST",
    body: JSON.stringify({ advance_days }),
  });

export function nextDeadline(cfg: HeartbeatConfig | null): string | null {
  if (!cfg?.last_check_in) return null;
  const ms = new Date(cfg.last_check_in).getTime() + cfg.interval_days * 86400000;
  return new Date(ms).toISOString();
}

// --- stats ---
export interface Stats {
  message_count: number;
  beneficiary_count: number;
  last_check_in: string | null;
  heartbeat_interval: number | null;
  heartbeat_grace: number | null;
  vault_status: string;
}
export const getStats = () => ownerFetch<Stats>("/stats");
export const wipeVault = (password: string) =>
  ownerFetch<void>("/vault/messages", {
    method: "DELETE",
    body: JSON.stringify({ password, confirm: true }),
  });
