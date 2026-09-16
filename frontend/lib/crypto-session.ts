// CryptoSessionManager — the ONLY holder of the owner's unwrapped VMK.
//
// The raw key never leaves this module: components get { unlocked, unlock,
// lock } plus operations (encrypt/decrypt/rewrap/split) that run against the
// internally held key. In-memory only — cleared on lock and tab close.

import {
  CRYPTO_VERSION,
  createWrappedVmk,
  decryptMessage,
  encryptMessage,
  rewrapVMK,
  unlockVMK,
  zeroMemory,
  type EncryptedMessagePayload,
  type WrappedVmkMaterial,
} from "./crypto";
import { splitVMK } from "./shamir";

let vmk: Uint8Array | null = null;
const listeners = new Set<() => void>();

function notify() {
  for (const fn of listeners) fn();
}

export function isUnlocked(): boolean {
  return vmk !== null;
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function lockVault(): void {
  if (vmk) zeroMemory(vmk);
  vmk = null;
  notify();
}

function requireKey(): Uint8Array {
  if (!vmk) throw new Error("Vault is locked");
  return vmk;
}

function adopt(raw: Uint8Array): void {
  if (vmk) zeroMemory(vmk);
  vmk = new Uint8Array(raw);
  zeroMemory(raw);
  notify();
}

/** Set up a fresh vault: generate VMK, return wrapped material + shares. */
export async function setupVault(
  passphrase: string,
  threshold: number = 2,
  total: number = 3,
): Promise<{ material: WrappedVmkMaterial; shares: string[] }> {
  const { vmk: raw, material } = await createWrappedVmk(passphrase);
  const shares = splitVMK(raw, threshold, total);
  adopt(raw);
  return { material, shares };
}

/** Unlock an existing vault from server-provided wrapped material. */
export async function unlockVault(
  passphrase: string,
  material: WrappedVmkMaterial,
): Promise<void> {
  adopt(await unlockVMK(passphrase, material));
}

export async function encrypt(plaintext: string): Promise<EncryptedMessagePayload> {
  return encryptMessage(plaintext, requireKey());
}

export async function decrypt(payload: EncryptedMessagePayload): Promise<string> {
  return decryptMessage(payload, requireKey());
}

/** Re-wrap the SAME VMK under a new passphrase (no re-encrypt, shares stay valid). */
export async function rewrap(newPassphrase: string): Promise<WrappedVmkMaterial> {
  return rewrapVMK(requireKey(), newPassphrase);
}

export { CRYPTO_VERSION };
