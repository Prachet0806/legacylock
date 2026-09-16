// Shamir k-of-n over GF(256) — client-side only. Never send raw shares to backend.
// Share encoding: base64(x || 32 secret bytes), x in {1..n} (max 255).

import { b64decode, b64encode, randomBytes } from "./crypto";

export const SHAMIR_THRESHOLD = 2;
export const SHAMIR_TOTAL = 3;
export const DEFAULT_THRESHOLD = 2;
export const DEFAULT_TOTAL = 3;
export const MAX_SHARES = 10;

// GF(256) with AES polynomial x^8 + x^4 + x^3 + x + 1 (0x11b).
// NOTE: x (2) has multiplicative order 51, so tables must be built with
// generator 3 (x+1), exactly like the AES log/alog tables.
const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
function xtime(a: number): number {
  return a & 0x80 ? ((a << 1) ^ 0x11b) & 0xff : (a << 1) & 0xff;
}
(function initTables() {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x = xtime(x) ^ x; // multiply by 3
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
})();

function gfAdd(a: number, b: number): number {
  return a ^ b;
}

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return EXP[LOG[a] + LOG[b]];
}

function gfDiv(a: number, b: number): number {
  if (b === 0) throw new Error("GF(256) division by zero");
  if (a === 0) return 0;
  return EXP[(LOG[a] - LOG[b] + 255) % 255];
}

function gfPow(a: number, e: number): number {
  if (e === 0) return 1;
  if (a === 0) return 0;
  return EXP[(LOG[a] * e) % 255];
}

function validatePolicy(threshold: number, total: number): void {
  if (
    !Number.isInteger(threshold) ||
    !Number.isInteger(total) ||
    threshold < 1 ||
    total < 1 ||
    threshold > total ||
    total > 255
  ) {
    throw new Error("Require 1 <= threshold <= total <= 255");
  }
}

/** Split 32-byte VMK into n shares with threshold k (degree k-1 polynomial per byte). */
export function splitVMK(
  vmk: Uint8Array,
  threshold: number = DEFAULT_THRESHOLD,
  total: number = DEFAULT_TOTAL,
): string[] {
  if (vmk.length !== 32) throw new Error("VMK must be 32 bytes");
  validatePolicy(threshold, total);
  // (k-1) random coefficients per byte.
  const coeffs: Uint8Array[] = [];
  for (let j = 0; j < threshold - 1; j++) coeffs.push(randomBytes(32));
  const shares: string[] = [];
  for (let x = 1; x <= total; x++) {
    const y = new Uint8Array(33);
    y[0] = x;
    for (let i = 0; i < 32; i++) {
      let v = vmk[i];
      for (let j = 0; j < coeffs.length; j++) {
        v = gfAdd(v, gfMul(coeffs[j][i], gfPow(x, j + 1)));
      }
      y[i + 1] = v;
    }
    shares.push(b64encode(y));
  }
  for (const c of coeffs) c.fill(0);
  return shares;
}

/** Reconstruct VMK from any k shares via Lagrange interpolation at x=0. */
export function reconstructVMK(
  shareB64s: string[],
  threshold: number = DEFAULT_THRESHOLD,
): Uint8Array {
  if (!Number.isInteger(threshold) || threshold < 1) throw new Error("Invalid threshold");
  if (shareB64s.length < threshold) throw new Error(`Need at least ${threshold} shares`);
  const pts = shareB64s.slice(0, threshold).map((s) => {
    const raw = b64decode(s);
    if (raw.length !== 33) throw new Error("Invalid share length");
    const x = raw[0];
    if (x < 1 || x > 255) throw new Error("Invalid share index");
    return { x, y: raw.slice(1) };
  });
  // Reject duplicate x.
  const xs = pts.map((p) => p.x);
  if (new Set(xs).size !== xs.length) throw new Error("Duplicate shares");
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    let acc = 0;
    for (let j = 0; j < pts.length; j++) {
      // L_j(0) = prod_{m != j} x_m / (x_m - x_j); subtraction = XOR in GF(256).
      let num = 1;
      let den = 1;
      for (let m = 0; m < pts.length; m++) {
        if (m === j) continue;
        num = gfMul(num, pts[m].x);
        den = gfMul(den, gfAdd(pts[m].x, pts[j].x));
      }
      acc = gfAdd(acc, gfMul(pts[j].y[i], gfDiv(num, den)));
    }
    out[i] = acc;
  }
  return out;
}

export function shareIndexOf(shareB64: string): number {
  return b64decode(shareB64)[0];
}
