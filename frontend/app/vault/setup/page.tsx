"use client";

// Vault setup (Flow I/H): generate VMK -> Shamir split -> KEK wrap -> persist wrapped VMK.
// Displays shares ONCE for out-of-band distribution. LegacyLock never transmits shares.
import { useState } from "react";
import { createWrappedVmk } from "../../../lib/crypto";
import { splitVMK } from "../../../lib/shamir";
import { putCryptoMaterial } from "../../../lib/client";
import { useVault } from "../../../lib/store/vault-context";

export default function VaultSetupPage() {
  const { setVMK } = useVault();
  const [passphrase, setPassphrase] = useState("");
  const [shares, setShares] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  async function onSetup() {
    setErr("");
    try {
      if (passphrase.length < 12) throw new Error("Passphrase must be 12+ chars");
      const { vmk, material } = await createWrappedVmk(passphrase);
      await putCryptoMaterial({
        wrapped_vmk: material.wrapped_vmk_b64,
        vmk_crypto_version: 1,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt: material.vmk_kdf_salt_b64,
        vmk_kdf_parameters: material.vmk_kdf_parameters,
      });
      setShares(splitVMK(vmk));
      setVMK(vmk);
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Setup failed");
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Vault setup</h1>
      <p>Generates a random VMK in your browser. The server only stores the wrapped VMK.</p>
      <input
        type="password"
        placeholder="Vault passphrase (12+ chars, distinct from login)"
        value={passphrase}
        onChange={(e) => setPassphrase(e.target.value)}
        style={{ width: "100%" }}
      />
      <button onClick={onSetup} style={{ marginTop: 12 }}>Generate + save wrapped VMK</button>
      {err && <p style={{ color: "red" }}>{err}</p>}
      {done && (
        <section style={{ marginTop: 16, border: "1px solid #c00", padding: 12 }}>
          <strong>Write these 3 shares down now (2-of-3 required). Shown once. Distribute out-of-band — LegacyLock never sends them.</strong>
          <ol>
            {shares.map((s, i) => (
              <li key={i}><code style={{ wordBreak: "break-all" }}>{s}</code></li>
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}
