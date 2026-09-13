// Backwards-compatible entrypoint — implementation lives in lib/api/.
// New code should import from lib/api/transport, lib/api/owner,
// lib/api/beneficiary, or lib/api/public directly.
export {
  beneficiaryFetch,
  ownerFetch,
  publicFetch,
  // Deprecated alias for owner calls (being migrated to ownerFetch).
  ownerFetch as apiFetch,
} from "./api/transport";
export { login } from "./api/public";
