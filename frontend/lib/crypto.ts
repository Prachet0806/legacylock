// LegacyLock client crypto engine (C3) — WebCrypto only.
// MVP: PBKDF2-SHA256 (600k) -> KEK (AES-KW) -> wrap VMK; VMK (AES-KW) -> wrap MEK; MEK -> AES-GCM.
// Secrets never leave the browser; backend only sees wrapped blobs + non-secret metadata.

export const CRYPTO_VERSION = 1;
export const KDF_ALGORITHM = "PBKDF2-SHA256";
// OWASP-aligned work factor for PBKDF2-HMAC-SHA256. Stored per-vault in
// vmk_kdf_parameters, so existing vaults keep unlocking with their own count.
export const KDF_ITERATIONS = 600_000;
export const VMK_LENGTH = 32;
export const MEK_LENGTH = 32;
export const SALT_LENGTH = 16;
export const IV_LENGTH = 12;

export interface KdfParams {
  iterations: number;
}

export interface EncryptedMessagePayload {
  v: number;
  algo: "AES-256-GCM";
  kdf: null; // per-message KEK not used; VMK wrap metadata lives in crypto-material
  iv_b64: string;
  wrapped_mek_b64: string;
  ciphertext_b64: string;
}

export interface WrappedVmkMaterial {
  wrapped_vmk_b64: string;
  vmk_crypto_version: number;
  vmk_kdf_algorithm: "PBKDF2-SHA256";
  vmk_kdf_salt_b64: string;
  vmk_kdf_parameters: KdfParams;
}

// --- base64 helpers (browser + node compatible for tests) ---
export function b64encode(bytes: Uint8Array): string {
  // Chunked apply avoids O(n²) string growth AND apply() arg limits (~65k)
  // if message sizes ever grow (chunked/file content on the roadmap).
  let s = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK) as unknown as number[]);
  }
  return btoa(s);
}

export function b64decode(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function randomBytes(n: number): Uint8Array {
  const b = new Uint8Array(n);
  crypto.getRandomValues(b);
  return b;
}

/** Best-effort memory wipe for in-memory secrets. */
export function zeroMemory(buf: Uint8Array | null | undefined): void {
  if (buf) buf.fill(0);
}

/** SHA-256 hex digest. Used to hash Shamir shares BEFORE transmission so raw
 *  share material never crosses the trust boundary (server stores the digest). */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// --- KEK derivation (vault passphrase -> AES-KW key, local only) ---
export async function deriveKEK(
  passphrase: string,
  salt_b64: string,
  iterations: number = KDF_ITERATIONS,
): Promise<CryptoKey> {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey("raw", enc.encode(passphrase), "PBKDF2", false, [
    "deriveKey",
  ]);
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt: b64decode(salt_b64),
      iterations,
    },
    base,
    { name: "AES-KW", length: 256 },
    false,
    ["wrapKey", "unwrapKey"],
  );
}

// --- VMK lifecycle ---
export function generateVMK(): Uint8Array {
  return randomBytes(VMK_LENGTH);
}

async function importAesKw(raw: Uint8Array): Promise<CryptoKey> {
  // Copy to a non-shared ArrayBuffer view for WebCrypto (accepts BufferSource).
  const copy = new Uint8Array(raw);
  return crypto.subtle.importKey("raw", copy, { name: "AES-KW" }, true, [
    "wrapKey",
    "unwrapKey",
  ]);
}

export async function wrapVMK(vmkRaw: Uint8Array, kek: CryptoKey): Promise<string> {
  const vmkKey = await importAesKw(vmkRaw);
  const wrapped = await crypto.subtle.wrapKey("raw", vmkKey, kek, { name: "AES-KW" });
  return b64encode(new Uint8Array(wrapped));
}

export async function unwrapVMK(wrappedVmkB64: string, kek: CryptoKey): Promise<Uint8Array> {
  const unwrapped = await crypto.subtle.unwrapKey(
    "raw",
    b64decode(wrappedVmkB64),
    kek,
    { name: "AES-KW" },
    { name: "AES-KW", length: 256 },
    true,
    ["wrapKey", "unwrapKey"],
  );
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", unwrapped));
  return raw;
}

export async function createWrappedVmk(
  passphrase: string,
): Promise<{ vmk: Uint8Array; material: WrappedVmkMaterial }> {
  const vmk = generateVMK();
  const salt = randomBytes(SALT_LENGTH);
  const salt_b64 = b64encode(salt);
  const kek = await deriveKEK(passphrase, salt_b64, KDF_ITERATIONS);
  const wrapped_vmk_b64 = await wrapVMK(vmk, kek);
  return {
    vmk,
    material: {
      wrapped_vmk_b64,
      vmk_crypto_version: CRYPTO_VERSION,
      vmk_kdf_algorithm: KDF_ALGORITHM,
      vmk_kdf_salt_b64: salt_b64,
      vmk_kdf_parameters: { iterations: KDF_ITERATIONS },
    },
  };
}

export async function unlockVMK(
  passphrase: string,
  material: WrappedVmkMaterial,
): Promise<Uint8Array> {
  const kek = await deriveKEK(
    passphrase,
    material.vmk_kdf_salt_b64,
    material.vmk_kdf_parameters.iterations,
  );
  return unwrapVMK(material.wrapped_vmk_b64, kek);
}

export async function rewrapVMK(vmkRaw: Uint8Array, newPassphrase: string): Promise<WrappedVmkMaterial> {
  const salt = randomBytes(SALT_LENGTH);
  const salt_b64 = b64encode(salt);
  const kek = await deriveKEK(newPassphrase, salt_b64, KDF_ITERATIONS);
  const wrapped_vmk_b64 = await wrapVMK(vmkRaw, kek);
  return {
    wrapped_vmk_b64,
    vmk_crypto_version: CRYPTO_VERSION,
    vmk_kdf_algorithm: KDF_ALGORITHM,
    vmk_kdf_salt_b64: salt_b64,
    vmk_kdf_parameters: { iterations: KDF_ITERATIONS },
  };
}

// --- Message encrypt/decrypt (MEK per message, wrapped by VMK) ---
async function importVmkForWrap(vmkRaw: Uint8Array): Promise<CryptoKey> {
  const copy = new Uint8Array(vmkRaw);
  return crypto.subtle.importKey("raw", copy, { name: "AES-KW" }, false, [
    "wrapKey",
    "unwrapKey",
  ]);
}

export async function encryptMessage(
  plaintext: string,
  vmkRaw: Uint8Array,
): Promise<EncryptedMessagePayload> {
  const vmkKey = await importVmkForWrap(vmkRaw);
  const mekKey = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, [
    "encrypt",
    "decrypt",
  ]);
  const iv = randomBytes(IV_LENGTH);
  const data = new TextEncoder().encode(plaintext);
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv: iv as BufferSource }, mekKey, data);
  const wrapped = await crypto.subtle.wrapKey("raw", mekKey, vmkKey, { name: "AES-KW" });
  return {
    v: CRYPTO_VERSION,
    algo: "AES-256-GCM",
    kdf: null,
    iv_b64: b64encode(iv),
    wrapped_mek_b64: b64encode(new Uint8Array(wrapped)),
    ciphertext_b64: b64encode(new Uint8Array(ct)),
  };
}

export async function decryptMessage(
  payload: EncryptedMessagePayload,
  vmkRaw: Uint8Array,
): Promise<string> {
  if (payload.v !== CRYPTO_VERSION || payload.algo !== "AES-256-GCM") {
    throw new Error("Unsupported crypto version/algorithm");
  }
  const vmkKey = await importVmkForWrap(vmkRaw);
  const mekKey = await crypto.subtle.unwrapKey(
    "raw",
    b64decode(payload.wrapped_mek_b64),
    vmkKey,
    { name: "AES-KW" },
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64decode(payload.iv_b64) as BufferSource },
    mekKey,
    b64decode(payload.ciphertext_b64),
  );
  return new TextDecoder().decode(pt);
}
