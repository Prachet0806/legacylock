"use client";

// Beneficiary recovery: check TRIGGERED gate -> submit share hashes (backend records
// hashes only) -> reconstruct VMK locally -> paste encrypted payload -> decrypt locally.
// Backend never sees shares or VMK (mock notifications kept).
import { useEffect, useState } from "react";
import { reconstructVMK } from "../../lib/shamir";
import { decryptMessage } from "../../lib/crypto";
import { getAccessStatus, submitShare } from "../../lib/client";

export default function RecoveryPage() {
  const [gate, setGate] = useState<string>("checking…");
  const [s1, setS1] = useState("");
  const [s2, setS2] = useState("");
  const [ciphertext, setCiphertext] = useState("");
  const [wrappedMek, setWrappedMek] = useState("");
  const [iv, setIv] = useState("");
  const [out, setOut] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const s = await getAccessStatus();
        setGate(`vault: ${s.vault_name} — ${s.vault_status}`);
      } catch (e) {
        setGate(e instanceof Error ? e.message : "status check failed");
      }
    })();
  }, []);

  function onRecover() {
    setErr("");
    setOut("");
    (async () => {
      try {
        const a = s1.trim();
        const b = s2.trim();
        if (!a || !b) throw new Error("Enter two shares");
        // Record share hashes server-side (idempotent); failures surface here, not VMK.
        await submitShare(a).catch((e) => {
          throw new Error(e instanceof Error ? `Share A rejected: ${e.message}` : "Share A rejected");
        });
        await submitShare(b).catch((e) => {
          throw new Error(e instanceof Error ? `Share B rejected: ${e.message}` : "Share B rejected");
        });
        const vmk = reconstructVMK([a, b]);
        const text = await decryptMessage(
          { v: 1, algo: "AES-256-GCM", kdf: null, iv_b64: iv.trim(), wrapped_mek_b64: wrappedMek.trim(), ciphertext_b64: ciphertext.trim() },
          vmk,
        );
        setOut(text);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Recovery failed");
      }
    })();
  }

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Beneficiary recovery (2-of-3)</h1>
      <p>Access gate: {gate} (requires TRIGGERED; accept your invite first).</p>
      <p>Paste 2 shares distributed out-of-band, plus the encrypted message fields copied from the vault export.</p>
      <div style={{ display: "grid", gap: 8 }}>
        <textarea placeholder="Share A (base64)" value={s1} onChange={(e) => setS1(e.target.value)} rows={3} />
        <textarea placeholder="Share B (base64)" value={s2} onChange={(e) => setS2(e.target.value)} rows={3} />
        <textarea placeholder="ciphertext_b64" value={ciphertext} onChange={(e) => setCiphertext(e.target.value)} rows={3} />
        <input placeholder="wrapped_mek_b64" value={wrappedMek} onChange={(e) => setWrappedMek(e.target.value)} />
        <input placeholder="iv_b64" value={iv} onChange={(e) => setIv(e.target.value)} />
        <button onClick={onRecover}>Submit shares + decrypt locally</button>
      </div>
      {out && <pre style={{ whiteSpace: "pre-wrap", border: "1px solid #090", padding: 12 }}>{out}</pre>}
      {err && <p style={{ color: "red" }}>{err}</p>}
    </main>
  );
}
