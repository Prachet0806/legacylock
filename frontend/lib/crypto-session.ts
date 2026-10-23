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
import { newRecoveryGeneration, reconstructVMK, splitVMK } from "./shamir";

/** Recovery ceremony state: generation binds policy metadata to the share set. */
let activeGeneration: string | null = null;
export function getActiveGeneration(): string | null {
  return activeGeneration;
}

let vmk: Uint8Array | null = null;
let epoch = 0;
let binding: string | null = null;
let revision = 0;
const HIDDEN_LOCK_MS = 5 * 60 * 1000;
const IDLE_LOCK_MS = 15 * 60 * 1000;
let hiddenAt: number | null = null;
let lastActivityAt: number | null = null;
export const currentEpoch = () => epoch;
export const materialRevision = () => revision;
export function bindVault(identity: string, material: number): void {
  const next = `${identity}:${material}`;
  if (binding !== next) lockVault();
  binding = next;
  revision = material;
}
export function assertEpoch(value: number): void {
  enforceLockDeadline();
  if (epoch !== value) throw new Error("Session changed; unlock again");
}
export function recover(shares: string[], threshold: number, generation?: string): void {
  adopt(reconstructVMK(shares, threshold, generation));
}
const listeners = new Set<() => void>();

function notify() {
  for (const fn of listeners) fn();
}

export function isUnlocked(): boolean {
  enforceLockDeadline();
  return vmk !== null;
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function lockVault(): void {
  epoch++;
  activeGeneration = null;
  if (vmk) zeroMemory(vmk);
  vmk = null;
  hiddenAt = null;
  lastActivityAt = null;
  notify();
}

export function enforceLockDeadline(now: number = Date.now()): void {
  if (vmk && ((hiddenAt !== null && now - hiddenAt >= HIDDEN_LOCK_MS)
      || (lastActivityAt !== null && now - lastActivityAt >= IDLE_LOCK_MS))) {
    lockVault();
  }
}

export function noteVaultActivity(): void {
  enforceLockDeadline();
  if (vmk && (typeof document === "undefined" || !document.hidden)) lastActivityAt = Date.now();
}

export function noteVaultVisibility(hidden: boolean): void {
  enforceLockDeadline();
  if (vmk) hiddenAt = hidden ? (hiddenAt ?? Date.now()) : null;
}

export function millisecondsUntilVaultLock(): number | null {
  enforceLockDeadline();
  if (!vmk || lastActivityAt === null) return null;
  const deadlines = [lastActivityAt + IDLE_LOCK_MS];
  if (hiddenAt !== null) deadlines.push(hiddenAt + HIDDEN_LOCK_MS);
  return Math.max(0, Math.min(...deadlines) - Date.now());
}

function requireKey(): Uint8Array {
  enforceLockDeadline();
  if (!vmk) throw new Error("Vault is locked");
  return vmk;
}

function adopt(raw: Uint8Array): void {
  if (vmk) zeroMemory(vmk);
  vmk = new Uint8Array(raw);
  zeroMemory(raw);
  lastActivityAt = Date.now();
  hiddenAt = typeof document !== "undefined" && document.hidden ? Date.now() : null;
  notify();
}

/** Set up a fresh vault: generate VMK + ceremony generation, return all. */
export async function setupVault(
  passphrase: string,
  threshold: number = 2,
  total: number = 3,
): Promise<{ material: WrappedVmkMaterial; shares: string[]; generation: string }> {
  const before = epoch;
  const { vmk: raw, material } = await createWrappedVmk(passphrase);
  if (before !== epoch) { zeroMemory(raw); throw new Error("Session changed; restart setup"); }
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
  const before = epoch;
  const raw = await unlockVMK(passphrase, material);
  if (before !== epoch) { zeroMemory(raw); throw new Error("Session changed; unlock again"); }
  adopt(raw);
}

export async function encrypt(plaintext: string): Promise<EncryptedMessagePayload> {
  const before = epoch;
  if (new TextEncoder().encode(plaintext).length > 1024 * 1024) throw new Error("Secret text exceeds 1 MiB");
  const result = await encryptMessage(plaintext, requireKey());
  assertEpoch(before);
  return result;
}

export async function decrypt(payload: EncryptedMessagePayload): Promise<string> {
  const before = epoch;
  const result = await decryptMessage(payload, requireKey());
  assertEpoch(before);
  return result;
}

/** Re-wrap the SAME VMK under a new passphrase (no re-encrypt, shares stay valid). */
export async function rewrap(newPassphrase: string): Promise<WrappedVmkMaterial> {
  const before = epoch;
  const result = await rewrapVMK(requireKey(), newPassphrase);
  const checked = await unlockVMK(newPassphrase, result);
  try {
    assertEpoch(before);
    if (!checked.every((value, index) => value === requireKey()[index])) throw new Error("Wrapping verification failed");
    return result;
  } finally { zeroMemory(checked); }
}

export { CRYPTO_VERSION };

export function reshare(threshold: number, total: number): {shares:string[]; generation:string} {
  const generation = newRecoveryGeneration();
  return {generation, shares:splitVMK(requireKey(), threshold, total, generation)};
}

export async function verifyRecovery(shares:string[], threshold:number, generation:string, sample:EncryptedMessagePayload):Promise<void> {
  const before = epoch;
  const raw = reconstructVMK(shares, threshold, generation);
  try { await decryptMessage(sample, raw); assertEpoch(before); }
  finally { zeroMemory(raw); }
}
