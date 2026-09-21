"use client";

// Beneficiary recovery stepper: gate -> shares -> pick message -> decrypt.
// Reconstruction and decryption happen in this tab. The server never sees
// shares (not even hashes): brute-force protection is strict rate limiting
// plus the client-side failed-attempt lockout below.
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, FileText, Info, ShieldCheck, Ticket, Unlock } from "lucide-react";
import { clsx } from "clsx";
import { decryptMessage, zeroMemory } from "../../lib/crypto";
import { parseShare, reconstructVMK } from "../../lib/shamir";
import {
  getAccessStatus,
  getRecoveryMessage,
  ivOf,
  listRecoveryMessages,
  type RecoveryMessageMeta,
} from "../../lib/client";
import { CopyButton, EmptyState, Spinner } from "../../components/ui";
import { useToast } from "../../components/toast";

const MAX_LOCAL_FAILURES = 5;
const LOCAL_LOCKOUT_MS = 15 * 60 * 1000;

export default function RecoveryPage() {
  const { notify } = useToast();
  const [step, setStep] = useState(1);
  const [gate, setGate] = useState<string>("checking…");
  const [gateOk, setGateOk] = useState(false);
  const [threshold, setThreshold] = useState(2);
  const [total, setTotal] = useState(3);
  const [generation, setGeneration] = useState<string | null>(null);
  const [shareInputs, setShareInputs] = useState<string[]>(["", ""]);
  const [vmk, setVmk] = useState<Uint8Array | null>(null);
  const [messages, setMessages] = useState<RecoveryMessageMeta[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [out, setOut] = useState<{ label: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [failures, setFailures] = useState(0);
  const [lockedUntil, setLockedUntil] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const s = await getAccessStatus();
        setGate(`${s.vault_name} — ${s.vault_status}`);
        setGateOk(s.vault_status === "triggered");
        const k = s.recovery_threshold ?? 2;
        const n = s.recovery_total ?? 3;
        setThreshold(k);
        setTotal(n);
        setGeneration((s as { recovery_generation?: string | null }).recovery_generation ?? null);
        setShareInputs(Array.from({ length: k }, () => ""));
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
      const inputs = shareInputs.map((s) => s.trim()).filter(Boolean);
      // Exact-k contract: extra input is user error, not silently dropped.
      if (inputs.length !== threshold)
        throw new Error(`Enter exactly ${threshold} shares (got ${inputs.length}).`);
      // Early generation check for a clear error before Lagrange math.
      try {
        const gens = new Set(inputs.map((s) => parseShare(s).generation).filter(Boolean));
        if (gens.size > 1)
          throw new Error("These shares belong to different recovery sets");
        if (generation && gens.size === 1 && !gens.has(generation))
          throw new Error("These shares are not from the current recovery set");
      } catch (e) {
        if (e instanceof Error && /recovery set/.test(e.message)) throw e;
        // Legacy shares carry no generation — fall through to reconstruct.
      }
      // Reconstruct locally only — shares never leave this tab in any form.
      const raw = reconstructVMK(inputs, threshold, generation ?? undefined);
      setVmk(raw);
      // Minimize exposure: drop raw share text once the VMK is derived.
      // (Browser memory can't be securely erased, but this bounds lifetime.)
      setShareInputs(Array.from({ length: threshold }, () => ""));
      setFailures(0);
      setMessages(await listRecoveryMessages());
      setStep(3);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Shares do not combine — check for typos.");
    } finally {
      setBusy(false);
    }
  }

  async function onDecrypt(id: number) {
    setErr("");
    setOut(null);
    if (Date.now() < lockedUntil) {
      setErr("Too many failed attempts — try again later.");
      return;
    }
    setBusy(true);
    try {
      if (!vmk) throw new Error("Enter your shares first.");
      const m = await getRecoveryMessage(id);
      const text = await decryptMessage(
        { v: m.crypto_version, algo: "AES-256-GCM", kdf: null, iv_b64: ivOf(m.crypto_metadata), wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
        vmk,
      );
      setSelectedId(id);
      setFailures(0);
      setOut({ label: m.label, text });
      notify("success", "Decrypted locally.");
    } catch (e) {
      const n = failures + 1;
      setFailures(n);
      if (n >= MAX_LOCAL_FAILURES) setLockedUntil(Date.now() + LOCAL_LOCKOUT_MS);
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
            2. Enter {threshold} of your {total} shares
          </h2>
          <p className="text-sm text-muted">
            Paste the shares distributed to you out-of-band. They never leave
            this tab in any form — reconstruction happens locally. Use shares from a single
            recovery set; mixing sets cannot work.
            {threshold === 1 && " Note: this vault is 1-of-n — any single share alone recovers."}
          </p>
          {shareInputs.map((val, i) => (
            <div key={i}>
              <label className="label" htmlFor={`share-${i}`}>Share {i + 1}</label>
              <textarea
                id={`share-${i}`}
                className="input font-mono text-xs"
                rows={3}
                value={val}
                onChange={(e) =>
                  setShareInputs((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                }
              />
            </div>
          ))}
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
          <div className="flex justify-between">
            <button type="button" className="btn-ghost text-sm" disabled={busy} onClick={() => setStep(1)}>
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={busy || shareInputs.filter((s) => s.trim()).length < threshold}
              onClick={onSharesContinue}
            >
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
