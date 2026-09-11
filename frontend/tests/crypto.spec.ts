import { test, expect } from "@playwright/test";
import { encryptMessage, decryptMessage, createWrappedVmk, unlockVMK, generateVMK, sha256Hex } from "../lib/crypto";
import { splitVMK, reconstructVMK } from "../lib/shamir";

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
  for (const [a, b] of [[0, 1], [0, 2], [1, 2]] as const) {
    const rec = reconstructVMK([shares[a], shares[b]]);
    expect(Buffer.from(rec)).toEqual(Buffer.from(vmk));
  }
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
