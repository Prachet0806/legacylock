"use client";

// Vault message CRUD — encrypts locally before POST, decrypts locally after GET.
import { useEffect, useState } from "react";
import { unlockVMK, encryptMessage, decryptMessage, b64decode } from "../../lib/crypto";
import {
  getCryptoMaterial,
  listMessages,
  getMessage,
  createMessage,
  MESSAGE_CATEGORIES,
  type MessageMeta,
} from "../../lib/client";
import { useVault } from "../../lib/store/vault-context";

export default function VaultPage() {
  const { vmk, setVMK, lock } = useVault();
  const [passphrase, setPassphrase] = useState("");
  const [messages, setMessages] = useState<MessageMeta[]>([]);
  const [label, setLabel] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<string>("personal");
  const [opened, setOpened] = useState("");
  const [err, setErr] = useState("");

  async function unlock() {
    setErr("");
    try {
      const mat = await getCryptoMaterial();
      if (!mat.wrapped_vmk || !mat.vmk_kdf_salt || !mat.vmk_kdf_parameters) {
        throw new Error("No vault yet — go to /vault/setup first");
      }
      const raw = await unlockVMK(passphrase, {
        wrapped_vmk_b64: mat.wrapped_vmk,
        vmk_crypto_version: 1,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt_b64: mat.vmk_kdf_salt,
        vmk_kdf_parameters: mat.vmk_kdf_parameters,
      });
      setVMK(raw);
      setMessages(await listMessages());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Unlock failed");
    }
  }

  async function onCreate() {
    setErr("");
    try {
      if (!vmk) throw new Error("Unlock first");
      const payload = await encryptMessage(body, vmk);
      await createMessage({
        label,
        ciphertext: payload.ciphertext_b64,
        wrapped_mek: payload.wrapped_mek_b64,
        iv: payload.iv_b64,
        crypto_metadata: { iv: payload.iv_b64, v: payload.v },
        category,
        coverage_tags: [],
      });
      setLabel("");
      setBody("");
      setMessages(await listMessages());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function onOpen(id: number) {
    setErr("");
    try {
      if (!vmk) throw new Error("Unlock first");
      const m = await getMessage(id);
      const text = await decryptMessage(
        { v: 1, algo: "AES-256-GCM", kdf: null, iv_b64: m.iv, wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
        vmk,
      );
      // Touch b64decode import (used for future export flows).
      void b64decode;
      setOpened(`# ${m.label}\n\n${text}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Decrypt failed");
    }
  }

  useEffect(() => {
    if (vmk) listMessages().then(setMessages).catch(() => {});
  }, [vmk]);

  if (!vmk) {
    return (
      <main style={{ padding: 24, maxWidth: 480 }}>
        <h1>Unlock vault</h1>
        <input type="password" placeholder="Vault passphrase" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} style={{ width: "100%" }} />
        <button onClick={unlock} style={{ marginTop: 12 }}>Unlock</button>
        {err && <p style={{ color: "red" }}>{err}</p>}
      </main>
    );
  }

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Vault</h1>
      <button onClick={lock}>Lock</button>
      <h2>New message</h2>
      <div style={{ display: "grid", gap: 8 }}>
        <input placeholder="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {MESSAGE_CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <textarea placeholder="Secret text (encrypted locally)" value={body} onChange={(e) => setBody(e.target.value)} rows={4} />
        <button onClick={onCreate}>Encrypt + save</button>
      </div>
      <h2>Messages ({messages.length})</h2>
      <ul>
        {messages.map((m) => (
          <li key={m.id}>
            {m.label} <button onClick={() => onOpen(m.id)}>Decrypt</button>
          </li>
        ))}
      </ul>
      {opened && <pre style={{ whiteSpace: "pre-wrap", border: "1px solid #ccc", padding: 12 }}>{opened}</pre>}
      {err && <p style={{ color: "red" }}>{err}</p>}
    </main>
  );
}
