// Beneficiary-session API wrappers — cookie-only, never owner refresh.
import { beneficiaryFetch, publicFetch, sessionChanged } from "./transport";

export const acceptInvite = (hash: string) => {
  sessionChanged();
  return publicFetch<{ beneficiary_id: number }>("/access/invitation/accept", {method:"POST",body:JSON.stringify({token:hash})}).finally(sessionChanged);
};
export const getInviteStatus = (hash: string) =>
  publicFetch<{ invitation_status: string; is_expired: boolean }>(
    "/access/invitation/status", {method:"POST",body:JSON.stringify({token:hash})},
  );
export const getAccessStatus = () =>
  beneficiaryFetch<{
    beneficiary_id: number;
  material_revision: number;
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
export const listRecoveryMessages = (beforeId?:number) =>
  beneficiaryFetch<RecoveryMessageMeta[]>(`/access/messages?limit=50${beforeId?`&before_id=${beforeId}`:""}`);
export const getRecoveryMessage = (id: number) =>
  beneficiaryFetch<RecoveryMessageDetail>(`/access/messages/${id}`);
export const revokeBeneficiarySession = async () => {
  sessionChanged();
  try { return await beneficiaryFetch<{ message: string }>("/access/revoke", { method: "POST" }); }
  finally { sessionChanged(); }
};
