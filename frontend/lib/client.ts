// Backwards-compatible entrypoint — implementation lives in lib/api/.
// New code should import from lib/api/owner or lib/api/beneficiary directly.
export {
  addBeneficiary,
  assignShare,
  checkin,
  createMessage,
  deleteBeneficiary,
  deleteMessage,
  getCryptoMaterial,
  getHeartbeat,
  getMe,
  getMessage,
  getRecoveryPolicy,
  getStats,
  getVaultStatus,
  inviteBeneficiary,
  ivOf,
  listBeneficiaries,
  listMessages,
  logout,
  manualTrigger,
  nextDeadline,
  postRecoveryCeremony,
  putCryptoMaterial,
  putHeartbeat,
  putRecoveryPolicy,
  runHeartbeatCheck,
  wipeVault,
  type Beneficiary,
  type CryptoMaterial,
  type HeartbeatConfig,
  type MessageDetail,
  type MessageMeta,
  type RecoveryPolicy,
  type Stats,
  type VaultStatus,
} from "./api/owner";
export {
  acceptInvite,
  getAccessStatus,
  getInviteStatus,
  getRecoveryMessage,
  listRecoveryMessages,
  type RecoveryMessageDetail,
  type RecoveryMessageMeta,
} from "./api/beneficiary";
export type { MeOut } from "./api/owner";

// --- categories (plumbing only; advisor UI deferred) ---
// Mirrors backend models/message.py MessageCategory — keep in sync
// (covered by backend test_message_category_contract).
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
