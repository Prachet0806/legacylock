// Shamir k-of-n over GF(256) — client-side only. Never send raw shares to backend.
// Share envelope v2: `LLS1-<base64url(payload)>` where payload =
//   version(1) | generation(16) | k(1) | n(1) | index(1) | y(32) | crc32(4).
// Legacy shares (base64(x || 32 secret bytes)) still decode for one release.
// Product cap: 10 shares. GF(256) technical max: 255.

import { b64decode, b64encode, randomBytes } from "./crypto";

export const SHAMIR_THRESHOLD = 2;
export const SHAMIR_TOTAL = 3;
export const DEFAULT_THRESHOLD = 2;
export const DEFAULT_TOTAL = 3;
/** LegacyLock product maximum (GF(256) technical maximum is 255). */
export const MAX_SHARES = 10;
const GF_MAX = 255;
export const SHARE_VERSION = 1;
export const SHARE_PREFIX = "LLS1-";

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
    total > GF_MAX
  ) {
    throw new Error("Require 1 <= threshold <= total <= 255");
  }
}

// CRC-32 (IEEE) for accidental-corruption detection (typos), not malice.
const CRC_TABLE = new Uint32Array(256);
(function initCrc() {
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    CRC_TABLE[i] = c >>> 0;
  }
})();
function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of data) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function b64urlEncode(data: Uint8Array): string {
  const b64 = b64encode(data);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecode(s: string): Uint8Array {
  let b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  return b64decode(b64);
}

/** New 128-bit recovery generation id (hex, non-secret, binds a share set). */
export function newRecoveryGeneration(): string {
  return Array.from(randomBytes(16), (b) => b.toString(16).padStart(2, "0")).join("");
}

function normalizeGeneration(generation?: string): Uint8Array {
  if (!generation) return randomBytes(16);
  if (!/^[0-9a-fA-F]{32}$/.test(generation)) throw new Error("Invalid recovery generation");
  const out = new Uint8Array(16);
  for (let i = 0; i < 16; i++) out[i] = parseInt(generation.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export interface ParsedShare {
  version: number;
  generation: string;
  threshold: number;
  total: number;
  index: number;
  y: Uint8Array;
  legacy: boolean;
}

/** Parse + validate a share envelope (v2 or legacy). Throws with UX-grade errors. */
export function parseShare(s: string): ParsedShare {
  const t = s.trim();
  if (t.startsWith(SHARE_PREFIX)) {
    const body = t.slice(SHARE_PREFIX.length);
    let raw: Uint8Array;
    try {
      raw = b64urlDecode(body);
    } catch {
      throw new Error("Invalid share encoding — check for typos");
    }
    if (raw.length !== 56) throw new Error("Invalid share length — check for typos");
    const version = raw[0];
    if (version !== SHARE_VERSION) throw new Error(`Unsupported share version ${version}`);
    const gen = raw.slice(1, 17);
    const k = raw[17];
    const n = raw[18];
    const idx = raw[19];
    const y = raw.slice(20, 52);
    const want = (raw[52] << 24) | (raw[53] << 16) | (raw[54] << 8) | raw[55];
    const got = crc32(raw.slice(0, 52));
    if ((want >>> 0) !== got) throw new Error("Share checksum mismatch — check for typos");
    if (k < 1 || n < 1 || k > n) throw new Error("Share policy invalid");
    if (idx < 1 || idx > n) throw new Error("Share index out of range");
    return {
      version,
      generation: Array.from(gen, (b) => b.toString(16).padStart(2, "0")).join(""),
      threshold: k,
      total: n,
      index: idx,
      y: new Uint8Array(y),
      legacy: false,
    };
  }
  // Legacy: base64(x || 32 bytes).
  let raw: Uint8Array;
  try {
    raw = b64decode(t);
  } catch {
    throw new Error("Invalid share encoding — check for typos");
  }
  if (raw.length !== 33) throw new Error("Invalid share length — check for typos");
  const x = raw[0];
  if (x < 1 || x > 255) throw new Error("Invalid share index");
  return {
    version: 0,
    generation: "",
    threshold: 0,
    total: 0,
    index: x,
    y: raw.slice(1),
    legacy: true,
  };
}

/** Split 32-byte VMK into n shares with threshold k (degree k-1 polynomial per byte). */
export function splitVMK(
  vmk: Uint8Array,
  threshold: number = DEFAULT_THRESHOLD,
  total: number = DEFAULT_TOTAL,
  generation?: string,
): string[] {
  if (vmk.length !== 32) throw new Error("VMK must be 32 bytes");
  validatePolicy(threshold, total);
  const gen = normalizeGeneration(generation);
  const genHex = Array.from(gen, (b) => b.toString(16).padStart(2, "0")).join("");
  void genHex;
  // (k-1) random coefficients per byte.
  const coeffs: Uint8Array[] = [];
  for (let j = 0; j < threshold - 1; j++) coeffs.push(randomBytes(32));
  const shares: string[] = [];
  for (let x = 1; x <= total; x++) {
    const y = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      let v = vmk[i];
      for (let j = 0; j < coeffs.length; j++) {
        v = gfAdd(v, gfMul(coeffs[j][i], gfPow(x, j + 1)));
      }
      y[i] = v;
    }
    const payload = new Uint8Array(56);
    payload[0] = SHARE_VERSION;
    payload.set(gen, 1);
    payload[17] = threshold;
    payload[18] = total;
    payload[19] = x;
    payload.set(y, 20);
    const c = crc32(payload.slice(0, 52));
    payload[52] = (c >>> 24) & 0xff;
    payload[53] = (c >>> 16) & 0xff;
    payload[54] = (c >>> 8) & 0xff;
    payload[55] = c & 0xff;
    shares.push(`${SHARE_PREFIX}${b64urlEncode(payload)}`);
    y.fill(0);
  }
  for (const c of coeffs) c.fill(0);
  return shares;
}

/** Reconstruct VMK from exactly k shares via Lagrange interpolation at x=0. */
export function reconstructVMK(
  shareB64s: string[],
  threshold: number = DEFAULT_THRESHOLD,
  expectedGeneration?: string,
): Uint8Array {
  if (!Number.isInteger(threshold) || threshold < 1) throw new Error("Invalid threshold");
  // Exact-k contract: silently dropping extra shares hid user error.
  if (shareB64s.length !== threshold)
    throw new Error(`Enter exactly ${threshold} shares (got ${shareB64s.length})`);
  const parsed = shareB64s.map(parseShare);
  const modern = parsed.filter((p) => !p.legacy);
  if (modern.length > 0 && modern.length !== parsed.length)
    throw new Error("These shares belong to different recovery sets — do not mix formats");
  if (modern.length > 0) {
    const g0 = expectedGeneration?.toLowerCase() ?? modern[0].generation;
    if (!modern.every((p) => p.generation === g0))
      throw new Error("These shares belong to different recovery sets");
    if (!modern.every((p) => p.threshold === modern[0].threshold && p.total === modern[0].total))
      throw new Error("These shares belong to different recovery sets");
    if (modern[0].threshold !== threshold)
      throw new Error(
        `Shares are for ${modern[0].threshold}-of-${modern[0].total}, not threshold ${threshold}`,
      );
  }
  const pts = parsed.map((p) => ({ x: p.index, y: p.y }));
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
  return parseShare(shareB64).index;
}

export function shareGenerationOf(shareB64: string): string {
  return parseShare(shareB64).generation;
}
