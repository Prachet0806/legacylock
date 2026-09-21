// Beneficiary-session API wrappers — cookie-only, never owner refresh.
import { beneficiaryFetch, publicFetch } from "./transport";

export const acceptInvite = (hash: string) =>
  publicFetch<{ beneficiary_id: number }>(`/access/invite/${hash}/accept`, {
    method: "POST",
  });
export const getInviteStatus = (hash: string) =>
  publicFetch<{ invitation_status: string; is_expired: boolean }>(
    `/access/invite/${hash}/status`,
  );
export const getAccessStatus = () =>
  beneficiaryFetch<{
    vault_status: string;
    vault_name: string;
    share_index: number | null;
    recovery_threshold: number;
    recovery_total: number;
    recovery_generation?: string | null;
  }>("/access/status");
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
  // Canonical shape: the IV lives inside crypto_metadata ({ iv }).
  crypto_metadata: Record<string, unknown>;
  crypto_version: number;
  category: string | null;
  created_at: string;
}
export const listRecoveryMessages = () =>
  beneficiaryFetch<RecoveryMessageMeta[]>("/access/messages");
export const getRecoveryMessage = (id: number) =>
  beneficiaryFetch<RecoveryMessageDetail>(`/access/messages/${id}`);
