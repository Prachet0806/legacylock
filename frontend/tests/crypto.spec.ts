import { test, expect } from "@playwright/test";
import { encryptMessage, decryptMessage, createWrappedVmk, unlockVMK, generateVMK, sha256Hex, rewrapVMK } from "../lib/crypto";
import { splitVMK, reconstructVMK } from "../lib/shamir";
import * as session from "../lib/crypto-session";
import {ownerFetch} from "../lib/api/transport";

test("late response body from a previous session is discarded",async()=>{
  const original=globalThis.fetch;
  let readStarted!:()=>void,finish!: (value:string)=>void;
  const started=new Promise<void>(resolve=>{readStarted=resolve;});
  const body=new Promise<string>(resolve=>{finish=resolve;});
  const response=new Response(null,{status:200});
  response.text=async()=>{readStarted();return body;};
  globalThis.fetch=async()=>response;
  try {
    const pending=ownerFetch("/vault/messages");
    await started;
    session.lockVault();
    finish('[{"id":1,"label":"old identity"}]');
    await expect(pending).rejects.toThrow(/Session changed/);
  } finally {globalThis.fetch=original;}
});

test("passphrase rewrap preserves old encrypted messages and existing recovery quorum", async () => {
  const {vmk, material} = await createWrappedVmk("old-passphrase-fixture-1234");
  const shares = splitVMK(vmk, 2, 3);
  const payload = await encryptMessage("rewrap must preserve this", vmk);
  const next = await rewrapVMK(vmk, "new-passphrase-fixture-1234");
  expect(await decryptMessage(payload, await unlockVMK("new-passphrase-fixture-1234", next))).toBe("rewrap must preserve this");
  expect(await decryptMessage(payload, reconstructVMK(shares.slice(0,2),2))).toBe("rewrap must preserve this");
  await expect(unlockVMK("old-passphrase-fixture-1234", next)).rejects.toThrow();
  expect(material.wrapped_vmk_b64).not.toBe(next.wrapped_vmk_b64);
});

test("resharing does not cryptographically revoke a previous quorum", async () => {
  const vmk=generateVMK();
  const old=splitVMK(vmk,2,3), next=splitVMK(vmk,3,5);
  const payload=await encryptMessage("historical quorum retains the key", vmk);
  for(const raw of [reconstructVMK(old.slice(0,2),2),reconstructVMK(next.slice(0,3),3)]) {
    expect(await decryptMessage(payload,raw)).toBe("historical quorum retains the key");
  }
});

test("principal change locks the key and invalidates in-flight cryptography", async () => {
  session.bindVault("owner:one",1);
  await session.setupVault("session-fixture-passphrase-1234");
  const pending=session.encrypt("delayed private body");
  session.bindVault("beneficiary:two",1);
  expect(session.isUnlocked()).toBe(false);
  await expect(pending).rejects.toThrow(/Session changed/);
});

test("hidden-tab deadline locks even when its timer never runs", async () => {
  const original = Date.now;
  await session.setupVault("hidden-deadline-test-passphrase");
  const hiddenAt = original();
  try {
    session.noteVaultVisibility(true);
    Date.now = () => hiddenAt + 5 * 60 * 1000 + 1;
    expect(session.isUnlocked()).toBe(false);
    await expect(session.encrypt("must stay locked")).rejects.toThrow(/locked/);
  } finally { Date.now = original; session.lockVault(); }
});

test("idle deadline is checked before extending activity", async () => {
  const original = Date.now;
  await session.setupVault("idle-deadline-test-passphrase");
  const unlockedAt = original();
  try {
    Date.now = () => unlockedAt + 15 * 60 * 1000 + 1;
    session.noteVaultActivity();
    expect(session.isUnlocked()).toBe(false);
  } finally { Date.now = original; session.lockVault(); }
});

test("sha256Hex matches known vector", async () => {
  expect(await sha256Hex("abc")).toBe(
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

test("vmk wrap/unwrap roundtrip is stable", async () => {
  const { vmk, material } = await createWrappedVmk("correct-horse-battery-staple-1");
  const raw2 = await unlockVMK("correct-horse-battery-staple-1", material);
  expect(Buffer.from(raw2)).toEqual(Buffer.from(vmk));
});

test("message encrypt/decrypt roundtrip", async () => {
  const vmk = generateVMK();
  const payload = await encryptMessage("hello legacy", vmk);
  const text = await decryptMessage(payload, vmk);
  expect(text).toBe("hello legacy");
});

test("shamir any-2-of-3 reconstructs", async () => {
  const vmk = generateVMK();
  const shares = splitVMK(vmk);
  expect(shares).toHaveLength(3);
  for (const s of shares) expect(s.startsWith("LLS1-")).toBe(true);
  for (const [a, b] of [[0, 1], [0, 2], [1, 2]] as const) {
    const rec = reconstructVMK([shares[a], shares[b]]);
    expect(Buffer.from(rec)).toEqual(Buffer.from(vmk));
  }
});

test("shamir k-of-n roundtrips (2-of-2, 3-of-5, 2-of-5)", async () => {
  for (const [k, n] of [[2, 2], [1, 1], [3, 5], [2, 5], [5, 5]] as const) {
    const vmk = generateVMK();
    const shares = splitVMK(vmk, k, n);
    expect(shares).toHaveLength(n);
    // First k reconstruct; a different k-subset also reconstructs when n > k.
    expect(Buffer.from(reconstructVMK(shares.slice(0, k), k))).toEqual(Buffer.from(vmk));
    if (n > k) {
      expect(Buffer.from(reconstructVMK(shares.slice(n - k), k))).toEqual(Buffer.from(vmk));
    }
  }
});

test("shamir exact-k contract rejects extra shares", async () => {
  const { splitVMK: split, reconstructVMK: rec } = await import("../lib/shamir");
  const vmk = generateVMK();
  const shares = split(vmk, 2, 3);
  expect(() => rec([shares[0], shares[1], shares[2]], 2)).toThrow(/exactly 2/);
});

test("shamir mixed generations rejected", async () => {
  const { splitVMK: split, reconstructVMK: rec } = await import("../lib/shamir");
  const vmk = generateVMK();
  const a = split(vmk, 2, 3);
  const b = split(vmk, 2, 3);
  expect(() => rec([a[0], b[1]], 2)).toThrow(/different recovery sets/);
});

test("shamir typo triggers checksum error", async () => {
  const { reconstructVMK: rec } = await import("../lib/shamir");
  const vmk = generateVMK();
  const shares = splitVMK(vmk, 2, 3);
  const bad = shares[0].slice(0, -2) + (shares[0].endsWith("A") ? "BB" : "AA");
  expect(() => rec([bad, shares[1]], 2)).toThrow();
});

test("shamir below-threshold fails", async () => {
  const vmk = generateVMK();
  const shares = splitVMK(vmk, 3, 5);
  expect(() => reconstructVMK(shares.slice(0, 2), 3)).toThrow();
});

test("shamir single share fails", async () => {
  const vmk = generateVMK();
  const shares = splitVMK(vmk);
  expect(() => reconstructVMK([shares[0]])).toThrow();
});

test("wrong passphrase cannot unwrap VMK", async () => {
  const { material } = await createWrappedVmk("correct-horse-battery-staple-1");
  await expect(unlockVMK("wrong-passphrase-xxxxxxxx", material)).rejects.toThrow();
});

test("tampered payloads fail decryption", async () => {
  const vmk = generateVMK();
  const payload = await encryptMessage("hello legacy", vmk);
  const flip = (b64: string) => {
    const raw = Buffer.from(b64, "base64");
    raw[0] ^= 0xff;
    return raw.toString("base64");
  };
  await expect(
    decryptMessage({ ...payload, ciphertext_b64: flip(payload.ciphertext_b64) }, vmk),
  ).rejects.toThrow();
  await expect(
    decryptMessage({ ...payload, iv_b64: flip(payload.iv_b64) }, vmk),
  ).rejects.toThrow();
  await expect(
    decryptMessage({ ...payload, wrapped_mek_b64: flip(payload.wrapped_mek_b64) }, vmk),
  ).rejects.toThrow();
  const other = generateVMK();
  await expect(decryptMessage(payload, other)).rejects.toThrow();
});

test("unsupported crypto version is rejected", async () => {
  const vmk = generateVMK();
  const payload = await encryptMessage("hello legacy", vmk);
  await expect(decryptMessage({ ...payload, v: 999 }, vmk)).rejects.toThrow();
});

test("shamir duplicate/corrupt shares fail", async () => {
  const vmk = generateVMK();
  const shares = splitVMK(vmk);
  expect(() => reconstructVMK([shares[0], shares[0]])).toThrow();
  expect(() => reconstructVMK([shares[0], "AAAA"])).toThrow();
});
