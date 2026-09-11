// Typed API wrappers over apiFetch — mirrors backend routers (no /api/v1 prefix for MVP).
import { apiFetch } from "./api";

// --- auth ---
export interface MeOut {
  id: number;
  email: string;
}
export const getMe = () => apiFetch<MeOut>("/auth/me");
export const logout = () =>
  apiFetch<{ message: string }>("/auth/logout", { method: "POST" });

// --- vault messages ---
export interface MessageMeta {
  id: number;
  label: string;
  created_at: string;
}
export interface MessageDetail {
  id: number;
  label: string;
  encrypted_content: string;
  ciphertext: string;
  wrapped_mek: string;
  iv: string;
  crypto_version: number;
  crypto_metadata: Record<string, unknown>;
  created_at: string;
  category?: string | null;
  coverage_tags?: string[];
}

export const listMessages = () => apiFetch<MessageMeta[]>("/vault/messages");
export const getMessage = (id: number) => apiFetch<MessageDetail>(`/vault/messages/${id}`);
export const createMessage = (body: {
  label: string;
  ciphertext: string;
  wrapped_mek: string;
  iv: string;
  crypto_version?: number;
  crypto_metadata?: Record<string, unknown>;
  category?: string | null;
  coverage_tags?: string[];
}) =>
  apiFetch<{ id: number }>("/vault/messages", { method: "POST", body: JSON.stringify(body) });
export const deleteMessage = (id: number) =>
  apiFetch<void>(`/vault/messages/${id}`, { method: "DELETE" });

// --- crypto material (wrapped only) ---
export interface CryptoMaterial {
  wrapped_vmk: string | null;
  vmk_crypto_version: number | null;
  vmk_kdf_algorithm: string | null;
  vmk_kdf_salt: string | null;
  vmk_kdf_parameters: { iterations: number } | null;
}
export const getCryptoMaterial = () => apiFetch<CryptoMaterial>("/vault/crypto-material");
export const putCryptoMaterial = (body: {
  wrapped_vmk: string;
  vmk_crypto_version: 1;
  vmk_kdf_algorithm: "PBKDF2-SHA256";
  vmk_kdf_salt: string;
  vmk_kdf_parameters: { iterations: number };
}) => apiFetch<{ message: string }>("/vault/crypto-material", { method: "PUT", body: JSON.stringify(body) });

// --- vault status / trigger ---
export interface VaultStatus {
  status: string;
  grace_started_at: string | null;
  triggered_at: string | null;
  share_threshold: number | null;
  share_total: number | null;
  updated_at: string;
}
export const getVaultStatus = () => apiFetch<VaultStatus>("/vault/status");
export const manualTrigger = (password: string, confirm: true) =>
  apiFetch<{ message: string; triggered_at: string }>("/vault/trigger", {
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
export const listBeneficiaries = () => apiFetch<Beneficiary[]>("/beneficiaries");
export const addBeneficiary = (body: { name: string; email: string; phone?: string }) =>
  apiFetch<{ id: number }>("/beneficiaries", { method: "POST", body: JSON.stringify(body) });
export const deleteBeneficiary = (id: number) =>
  apiFetch<void>(`/beneficiaries/${id}`, { method: "DELETE" });
export const inviteBeneficiary = (id: number) =>
  apiFetch<{ invitation_link: string; beneficiary_id: number }>(`/beneficiaries/${id}/invite`, {
    method: "POST",
  });
// --- heartbeat ---
// NOTE: the API has no next_deadline field; compute it client-side as
// last_check_in + interval_days. PUT returns {message}, not the config.
export interface HeartbeatConfig {
  interval_days: number;
  grace_days: number;
  last_check_in: string | null;
  updated_at?: string;
}
export const getHeartbeat = () => apiFetch<HeartbeatConfig>("/heartbeat");
export const putHeartbeat = (body: { interval_days: number; grace_days: number }) =>
  apiFetch<{ message: string }>("/heartbeat", { method: "PUT", body: JSON.stringify(body) });
export const checkin = () => apiFetch<{ message: string; last_check_in?: string }>("/heartbeat/checkin", { method: "POST" });

export function nextDeadline(cfg: HeartbeatConfig | null): string | null {
  if (!cfg?.last_check_in) return null;
  const ms = new Date(cfg.last_check_in).getTime() + cfg.interval_days * 86400000;
  return new Date(ms).toISOString();
}

// --- beneficiary recovery ---
// The HttpOnly beneficiary cookie (set on invite accept) is sent automatically
// via credentials:include; the tab-scoped sessionStorage token below is a
// fallback for contexts where the cookie is unavailable. The server accepts
// either (header first, then cookie).
function beneficiaryHeaders(): Record<string, string> {
  if (typeof sessionStorage === "undefined") return {};
  const t = sessionStorage.getItem("legacylock_beneficiary_token");
  return t ? { Authorization: `Bearer ${t}` } : {};
}
export const acceptInvite = (hash: string) =>
  apiFetch<{ beneficiary_id: number; access_token: string }>(`/access/invite/${hash}/accept`, {
    method: "POST",
  });
export const getAccessStatus = () =>
  apiFetch<{ vault_status: string; vault_name: string; share_index: number | null }>(
    "/access/status",
    { headers: beneficiaryHeaders() },
  );
export const submitShare = (shareHash: string) =>
  apiFetch<{ message: string; accepted: boolean; duplicate?: boolean }>("/access/share", {
    method: "POST",
    headers: beneficiaryHeaders(),
    body: JSON.stringify({ share_hash: shareHash }),
  });
export const reportMismatch = () =>
  apiFetch<{ message: string }>("/access/share/report-mismatch", {
    method: "POST",
    headers: beneficiaryHeaders(),
  });
export interface RecoveryMessageMeta {
  id: number;
  label: string;
  category: string | null;
  created_at: string;
}
export interface RecoveryMessageDetail {
  id: number;
  label: string;
  ciphertext: string;
  wrapped_mek: string;
  iv: string;
  crypto_version: number;
  category: string | null;
  created_at: string;
}
export const listRecoveryMessages = () =>
  apiFetch<RecoveryMessageMeta[]>("/access/messages", { headers: beneficiaryHeaders() });
export const getRecoveryMessage = (id: number) =>
  apiFetch<RecoveryMessageDetail>(`/access/messages/${id}`, { headers: beneficiaryHeaders() });
export const assignShare = (beneficiaryId: number, share_index: number) =>
  apiFetch<{ message: string; share_index: number }>(
    `/beneficiaries/${beneficiaryId}/assign-share`,
    { method: "POST", body: JSON.stringify({ share_index }) },
  );

// --- stats ---
export interface Stats {
  message_count: number;
  beneficiary_count: number;
  last_check_in: string | null;
  heartbeat_interval: number | null;
  heartbeat_grace: number | null;
  vault_status: string;
}
export const getStats = () => apiFetch<Stats>("/stats");
export const wipeVault = (password: string) =>
  apiFetch<void>("/vault/messages", {
    method: "DELETE",
    body: JSON.stringify({ password, confirm: true }),
  });

// --- categories (plumbing only; advisor UI deferred) ---
export const MESSAGE_CATEGORIES = [
  "financial",
  "insurance",
  "digital_assets",
  "digital_identity",
  "digital_storage",
  "devices",
  "online_accounts",
  "property",
  "dependents",
  "business",
  "personal",
] as const;
export type MessageCategory = (typeof MESSAGE_CATEGORIES)[number];
