// Owner-session API wrappers — mirrors backend owner routers.
import { ownerFetch } from "./transport";

// --- auth ---
export interface MeOut {
  id: number;
  email: string;
}
export const getMe = () => ownerFetch<MeOut>("/auth/me");
export const logout = () =>
  ownerFetch<{ message: string }>("/auth/logout", { method: "POST" });

// --- vault messages ---
export interface MessageMeta {
  id: number;
  label: string;
  created_at: string;
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

export const listMessages = () => ownerFetch<MessageMeta[]>("/vault/messages");
export const getMessage = (id: number) => ownerFetch<MessageDetail>(`/vault/messages/${id}`);

/** IV lives inside crypto_metadata ({ iv: base64 }). Empty string if absent. */
export function ivOf(meta: Record<string, unknown> | null | undefined): string {
  const iv = meta?.iv;
  return typeof iv === "string" ? iv : "";
}
export const createMessage = (body: {
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
  wrapped_vmk: string | null;
  vmk_crypto_version: number | null;
  vmk_kdf_algorithm: string | null;
  vmk_kdf_salt: string | null;
  vmk_kdf_parameters: { iterations: number } | null;
}
export const getCryptoMaterial = () => ownerFetch<CryptoMaterial>("/vault/crypto-material");
export const putCryptoMaterial = (body: {
  wrapped_vmk: string;
  vmk_crypto_version: 1;
  vmk_kdf_algorithm: "PBKDF2-SHA256";
  vmk_kdf_salt: string;
  vmk_kdf_parameters: { iterations: number };
}) => ownerFetch<{ message: string }>("/vault/crypto-material", { method: "PUT", body: JSON.stringify(body) });

// --- vault status / trigger ---
export interface VaultStatus {
  status: string;
  grace_started_at: string | null;
  triggered_at: string | null;
  updated_at: string;
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
