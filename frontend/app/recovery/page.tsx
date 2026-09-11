"use client";

// Beneficiary recovery stepper: gate -> shares -> pick message -> decrypt.
// Reconstruction and decryption happen in this tab; the backend only records
// share hashes and serves ciphertext to TRIGGERED-vault beneficiaries.
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, FileText, Info, ShieldCheck, Ticket, Unlock } from "lucide-react";
import { clsx } from "clsx";
import { decryptMessage, sha256Hex, zeroMemory } from "../../lib/crypto";
import { reconstructVMK } from "../../lib/shamir";
import {
  getAccessStatus,
  getRecoveryMessage,
  listRecoveryMessages,
  reportMismatch,
  submitShare,
  type RecoveryMessageMeta,
} from "../../lib/client";
import { CopyButton, EmptyState, Spinner } from "../../components/ui";
import { useToast } from "../../components/toast";

export default function RecoveryPage() {
  const { notify } = useToast();
  const [step, setStep] = useState(1);
  const [gate, setGate] = useState<string>("checking…");
  const [gateOk, setGateOk] = useState(false);
  const [s1, setS1] = useState("");
  const [s2, setS2] = useState("");
  const [vmk, setVmk] = useState<Uint8Array | null>(null);
  const [messages, setMessages] = useState<RecoveryMessageMeta[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [out, setOut] = useState<{ label: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const s = await getAccessStatus();
        setGate(`${s.vault_name} — ${s.vault_status}`);
        setGateOk(s.vault_status === "triggered");
      } catch (e) {
        setGate(e instanceof Error ? e.message : "status check failed");
      }
    })();
    return () => {
      setVmk((prev) => {
        if (prev) zeroMemory(prev);
        return null;
      });
    };
  }, []);

  async function onSharesContinue() {
    setErr("");
    setBusy(true);
    try {
      const a = s1.trim();
      const b = s2.trim();
      if (!a || !b) throw new Error("Enter two shares.");
      // Hash locally FIRST: raw shares never leave this tab. The server only
      // records digests ("accepted" = recorded, not verified — only local
      // reconstruction can verify shares).
      await submitShare(await sha256Hex(a)).catch((e) => {
        throw new Error(e instanceof Error ? `Share A rejected: ${e.message}` : "Share A rejected");
      });
      await submitShare(await sha256Hex(b)).catch((e) => {
        throw new Error(e instanceof Error ? `Share B rejected: ${e.message}` : "Share B rejected");
      });
      const raw = reconstructVMK([a, b]);
      setVmk(raw);
      setMessages(await listRecoveryMessages());
      setStep(3);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Share submission failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDecrypt(id: number) {
    setErr("");
    setOut(null);
    setBusy(true);
    try {
      if (!vmk) throw new Error("Enter your shares first.");
      const m = await getRecoveryMessage(id);
      const text = await decryptMessage(
        { v: m.crypto_version, algo: "AES-256-GCM", kdf: null, iv_b64: m.iv, wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
        vmk,
      );
      setSelectedId(id);
      setOut({ label: m.label, text });
      notify("success", "Decrypted locally.");
    } catch (e) {
      try {
        await reportMismatch();
      } catch {
        /* counter best-effort; surface the decrypt error below */
      }
      setErr(e instanceof Error ? e.message : "Decrypt failed — shares may not match this vault.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-bold">Beneficiary recovery</h1>
      <ol className="my-6 flex items-center gap-2 text-sm" aria-label="Recovery progress">
        {["Access", "Shares", "Decrypt"].map((label, i) => (
          <li
            key={label}
            className="flex items-center gap-2"
            aria-current={step === i + 1 ? "step" : undefined}
          >
            <span
              className={clsx(
                "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                step > i + 1 ? "bg-success text-black" : step === i + 1 ? "bg-accent text-black" : "bg-raised text-muted",
              )}
            >
              {i + 1}
            </span>
            <span className={step === i + 1 ? "text-text" : "text-muted"}>{label}</span>
            {i < 2 && <span className="mx-1 text-faint">—</span>}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div className="card flex flex-col gap-3">
          <h2 className="font-semibold">1. Vault access gate</h2>
          <p className="text-sm text-muted">
            Recovery unlocks only after the vault is TRIGGERED. Accept your invitation first,
            then return here.
          </p>
          <p className="text-sm">Gate: <strong>{gate}</strong></p>
          {!gateOk && (
            <p className="flex items-start gap-2 text-sm text-warn">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Not yet released. If you are the owner testing, trigger the vault from Heartbeat.
            </p>
          )}
          <button type="button" className="btn-primary self-end text-sm" disabled={!gateOk} onClick={() => setStep(2)}>
            Continue
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="card flex flex-col gap-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <Ticket className="h-4 w-4 text-accent" />
            2. Enter 2 of your 3 shares
          </h2>
          <p className="text-sm text-muted">
            Paste the shares distributed to you out-of-band. Hashes are recorded server-side
            for abuse protection; raw shares never leave this tab.
          </p>
          <div>
            <label className="label" htmlFor="share-a">Share A</label>
            <textarea id="share-a" className="input font-mono text-xs" rows={3} value={s1} onChange={(e) => setS1(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="share-b">Share B</label>
            <textarea id="share-b" className="input font-mono text-xs" rows={3} value={s2} onChange={(e) => setS2(e.target.value)} />
          </div>
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
          <div className="flex justify-between">
            <button type="button" className="btn-ghost text-sm" disabled={busy} onClick={() => setStep(1)}>
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button type="button" className="btn-primary text-sm" disabled={busy || !s1.trim() || !s2.trim()} onClick={onSharesContinue}>
              {busy && <Spinner />}
              Submit shares
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <div className="card flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-semibold">
              <FileText className="h-4 w-4 text-accent" />
              3. Choose a message to decrypt
            </h2>
            {messages.length === 0 ? (
              <EmptyState
                icon={<FileText className="h-8 w-8" />}
                title="No messages released"
                hint="The vault has no messages to recover."
              />
            ) : (
              <ul className="flex flex-col gap-2">
                {messages.map((m) => (
                  <li key={m.id} className="flex items-center gap-3 rounded-md bg-raised p-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{m.label}</p>
                      {m.category && <p className="text-xs text-faint">{m.category}</p>}
                    </div>
                    <button
                      type="button"
                      className="btn-ghost px-2 py-1 text-xs"
                      disabled={busy}
                      onClick={() => onDecrypt(m.id)}
                    >
                      {busy && selectedId === m.id ? <Spinner /> : <Unlock className="h-3.5 w-3.5" />}
                      Decrypt
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {err && <p role="alert" className="text-sm text-danger">{err}</p>}
            <div>
              <button
                type="button"
                className="btn-ghost text-sm"
                disabled={busy}
                onClick={() => {
                  if (vmk) zeroMemory(vmk);
                  setVmk(null);
                  setOut(null);
                  setStep(2);
                }}
              >
                <ArrowLeft className="h-4 w-4" />
                Re-enter shares
              </button>
            </div>
          </div>
          {out && (
            <div className="card border-success">
              <p className="mb-2 flex items-center gap-2 text-sm font-medium text-success">
                <ShieldCheck className="h-4 w-4" />
                {out.label} — decrypted locally
              </p>
              <pre className="whitespace-pre-wrap rounded-md bg-raised p-4 text-sm">{out.text}</pre>
              <div className="mt-3 flex justify-end">
                <CopyButton text={out.text} label="Copy text" />
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
