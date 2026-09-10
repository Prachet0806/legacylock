import { test, expect } from "@playwright/test";
import { encryptMessage, decryptMessage, createWrappedVmk, unlockVMK, generateVMK } from "../lib/crypto";
import { splitVMK, reconstructVMK } from "../lib/shamir";

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
