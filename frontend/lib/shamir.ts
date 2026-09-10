// Shamir 2-of-3 over GF(256) — client-side only. Never send raw shares to backend.
// Share encoding: base64(x || 32 secret bytes), x in {1,2,3}.

import { b64decode, b64encode, randomBytes } from "./crypto";

export const SHAMIR_THRESHOLD = 2;
export const SHAMIR_TOTAL = 3;

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

/** Split 32-byte VMK into 3 shares (x=1,2,3). Each byte: y = s + a*x. */
export function splitVMK(vmk: Uint8Array): string[] {
  if (vmk.length !== 32) throw new Error("VMK must be 32 bytes");
  const slopes = randomBytes(32);
  const shares: string[] = [];
  for (let x = 1; x <= SHAMIR_TOTAL; x++) {
    const y = new Uint8Array(33);
    y[0] = x;
    for (let i = 0; i < 32; i++) {
      y[i + 1] = gfAdd(vmk[i], gfMul(slopes[i], x));
    }
    shares.push(b64encode(y));
  }
  slopes.fill(0);
  return shares;
}

/** Reconstruct VMK from any 2+ shares via Lagrange interpolation at x=0. */
export function reconstructVMK(shareB64s: string[]): Uint8Array {
  if (shareB64s.length < SHAMIR_THRESHOLD) throw new Error("Need at least 2 shares");
  const pts = shareB64s.slice(0, 3).map((s) => {
    const raw = b64decode(s);
    if (raw.length !== 33) throw new Error("Invalid share length");
    const x = raw[0];
    if (x < 1 || x > 3) throw new Error("Invalid share index");
    return { x, y: raw.slice(1) };
  });
  // Reject duplicate x.
  const xs = pts.map((p) => p.x);
  if (new Set(xs).size !== xs.length) throw new Error("Duplicate shares");
  // Use first 2 distinct shares.
  const [p1, p2] = pts;
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    // L1(0) = x2/(x2-x1), L2(0) = x1/(x1-x2) in GF(256); note subtraction = addition (XOR).
    const l1 = gfDiv(p2.x, gfAdd(p2.x, p1.x));
    const l2 = gfDiv(p1.x, gfAdd(p1.x, p2.x));
    out[i] = gfAdd(gfMul(p1.y[i], l1), gfMul(p2.y[i], l2));
  }
  return out;
}

export function shareIndexOf(shareB64: string): number {
  return b64decode(shareB64)[0];
}
