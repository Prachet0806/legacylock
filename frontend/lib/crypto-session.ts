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
import { newRecoveryGeneration, splitVMK } from "./shamir";

/** Recovery ceremony state: generation binds policy metadata to the share set. */
let activeGeneration: string | null = null;
export function getActiveGeneration(): string | null {
  return activeGeneration;
}

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

/** Set up a fresh vault: generate VMK + ceremony generation, return all. */
export async function setupVault(
  passphrase: string,
  threshold: number = 2,
  total: number = 3,
): Promise<{ material: WrappedVmkMaterial; shares: string[]; generation: string }> {
  const { vmk: raw, material } = await createWrappedVmk(passphrase);
  const generation = newRecoveryGeneration();
  const shares = splitVMK(raw, threshold, total, generation);
  activeGeneration = generation;
  adopt(raw);
  return { material, shares, generation };
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
