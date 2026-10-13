"use client";

// Beneficiary recovery ceremony: gate -> shares -> pick message -> decrypt.
// Reconstruction and decryption happen in this tab. The server never sees
// shares (not even hashes): brute-force protection is strict rate limiting
// plus the client-side failed-attempt lockout below.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, CheckCircle2, FileText, Info, Lock, ShieldCheck, Ticket, Unlock, Vault as VaultIcon } from "lucide-react";
import { clsx } from "clsx";
import { assertEpoch, bindVault, currentEpoch, decrypt, isUnlocked, lockVault, recover, subscribe } from "../../lib/crypto-session";
import { parseShare } from "../../lib/shamir";
import {
  getAccessStatus,
  getRecoveryMessage,
  ivOf,
  listRecoveryMessages,
  type RecoveryMessageMeta,
} from "../../lib/client";
import { CopyButton, EmptyState, Spinner, Stepper } from "../../components/ui";
import { useToast } from "../../components/toast";

const MAX_LOCAL_FAILURES = 5;
const LOCAL_LOCKOUT_MS = 15 * 60 * 1000;

export default function RecoveryPage() {
  const { notify } = useToast();
  const [step, setStep] = useState(1);
  const [gate, setGate] = useState<string>("checking…");
  const [gateOk, setGateOk] = useState(false);
  const [vaultName, setVaultName] = useState("");
  const [threshold, setThreshold] = useState(2);
  const [total, setTotal] = useState(3);
  const [generation, setGeneration] = useState<string | null>(null);
  const [shareInputs, setShareInputs] = useState<string[]>(["", ""]);
  const [unlocked, setUnlocked] = useState(false);
  useEffect(() => subscribe(() => { setUnlocked(isUnlocked()); if (!isUnlocked()) { setOut(null); setMessages([]); setShareInputs(Array.from({length:threshold},()=>"")); setStep(1); } }), [threshold]);
  const [messages, setMessages] = useState<RecoveryMessageMeta[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [out, setOut] = useState<{ label: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [failures, setFailures] = useState(0);
  const [lockedUntil, setLockedUntil] = useState(0);

  useEffect(() => {
    let cancelled=false;
    const before=currentEpoch();
    (async () => {
      try {
        const s = await getAccessStatus();
        if(cancelled)return;
        assertEpoch(before);
        bindVault(`beneficiary:${s.beneficiary_id}`, s.material_revision);
        setVaultName(s.vault_name ?? "");
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
    return () => {cancelled=true;lockVault();};
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
      recover(inputs, threshold, generation ?? undefined);
      setUnlocked(true);
      // Minimize exposure: drop raw share text once the VMK is derived.
      // (Browser memory can't be securely erased, but this bounds lifetime.)
      setShareInputs(Array.from({ length: threshold }, () => ""));
      setFailures(0);
      const before=currentEpoch();
      const rows=await listRecoveryMessages();
      assertEpoch(before);
      setMessages(rows);
      setHasMore(rows.length === 50);
      setStep(3);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Shares do not combine — check for typos.");
    } finally {
      setBusy(false);
    }
  }

  async function loadMore() {
    setBusy(true);
    setErr("");
    try {
      const before = currentEpoch();
      const rows = await listRecoveryMessages(messages[messages.length - 1]?.id);
      assertEpoch(before);
      setMessages((previous) => [...previous, ...rows]);
      setHasMore(rows.length === 50);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load messages.");
    } finally { setBusy(false); }
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
      if (!unlocked) throw new Error("Enter your shares first.");
      const before = currentEpoch();
      const m = await getRecoveryMessage(id);
      const text = await decrypt(
        { v: m.crypto_version, algo: "AES-256-GCM", kdf: null, iv_b64: ivOf(m.crypto_metadata), wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
      );
      assertEpoch(before);
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
      <div className="flex flex-col items-center text-center">
        <VaultIcon className="h-7 w-7 text-accent" />
        <p className="eyebrow mt-3">LegacyLock Recovery</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Beneficiary recovery</h1>
      </div>
      <Link className="btn-ghost mt-4" href="/access/login">Request a new sign-in link</Link>
      <div className="my-6 flex justify-center">
        <Stepper steps={["Access", "Shares", "Decrypt"]} current={step} />
      </div>

      {step === 1 && (
        <div className="surface-lg flex flex-col items-center gap-3 py-10 text-center">
          {gateOk ? (
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-success/15">
              <CheckCircle2 className="h-6 w-6 text-success" />
            </span>
          ) : (
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-raised">
              <Lock className="h-5 w-5 text-muted" />
            </span>
          )}
          <h2 className="text-lg font-semibold">
            {gateOk ? "The vault has been released." : "Checking vault access…"}
          </h2>
          <p className="text-sm text-muted">Gate: <strong className="text-text">{gate}</strong></p>
          {gateOk ? (
            <>
              <p className="flex items-center gap-1.5 text-sm text-success">
                <CheckCircle2 className="h-4 w-4" />
                Access verified{vaultName ? ` · ${vaultName}` : ""}
              </p>
              <p className="max-w-xs text-sm leading-relaxed text-muted">
                You need {threshold} of {total} recovery shares to reconstruct the vault key.
              </p>
              <button type="button" className="btn-primary mt-2 min-w-44" onClick={() => setStep(2)}>
                Continue
                <ArrowRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <p className="flex max-w-xs items-start gap-2 text-sm leading-relaxed text-warn">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Not yet released. If you are the owner testing, trigger the vault from Heartbeat.
            </p>
          )}
        </div>
      )}

      {step === 2 && (
        <div className="surface-lg flex flex-col gap-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <Ticket className="h-4 w-4 text-accent" />
            Recovery shares
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            Enter {threshold} of {total} shares. Your shares are processed locally.
            They are never uploaded. Use shares from a single recovery set.
            {threshold === 1 && " Note: this vault is 1-of-n — any single share alone recovers."}
          </p>
          {shareInputs.map((val, i) => (
            <div key={i}>
              <label className="label" htmlFor={`share-${i}`}>Share {i + 1}</label>
              <textarea
                id={`share-${i}`}
                className="input font-mono text-xs"
                rows={3}
                placeholder="Paste share…"
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
              Reconstruct
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <div className="surface-lg flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-semibold">
              <FileText className="h-4 w-4 text-accent" />
              Vault recovered
            </h2>
            <p className="text-sm leading-relaxed text-muted">
              Your recovery key was reconstructed locally in this browser.{" "}
              {messages.length > 0 ? `${messages.length} ${messages.length === 1 ? "message" : "messages"} available.` : ""}
            </p>
            {messages.length === 0 ? (
              <EmptyState
                icon={<FileText className="h-6 w-6" />}
                title="No messages released"
                hint="The vault has no messages to recover."
              />
            ) : (
              <ul className="overflow-hidden rounded-xl border border-border">
                {messages.map((m) => (
                  <li key={m.id} className="row-item !bg-transparent">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{m.label}</p>
                      {m.category && <p className="text-xs text-faint">{m.category}</p>}
                    </div>
                    <button
                      type="button"
                      className="btn-ghost !rounded-lg px-2.5 py-1.5 text-xs"
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
            {hasMore && <button type="button" className="btn-ghost text-sm" disabled={busy} onClick={loadMore}>Load more messages</button>}
            {err && <p role="alert" className="text-sm text-danger">{err}</p>}
            <div>
              <button
                type="button"
                className="btn-ghost text-sm"
                disabled={busy}
                onClick={() => {
                  lockVault();
                  setUnlocked(false);
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
            <div className="surface-lg !border-success/40">
              <p className="mb-2 flex items-center gap-2 text-sm font-medium text-success">
                <ShieldCheck className="h-4 w-4" />
                {out.label} — decrypted locally
              </p>
              <pre className="whitespace-pre-wrap rounded-xl bg-raised p-4 text-sm leading-relaxed">{out.text}</pre>
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
