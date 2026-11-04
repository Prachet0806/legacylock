"use client";

// Vault setup wizard: policy -> passphrase -> generate -> share ceremony.
// VMK is generated in-browser; the server only stores the wrapped VMK + k-of-n policy.
// Shares display ONCE for out-of-band distribution and are never transmitted.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import { clsx } from "clsx";
import { assertEpoch, currentEpoch, isUnlocked, subscribe, CRYPTO_VERSION, lockVault, setupVault } from "../../../lib/crypto-session";
import { postRecoveryCeremony, getCryptoMaterial, finalizeCeremony } from "../../../lib/client";
import { CopyButton, Spinner, Stepper } from "../../../components/ui";
import { useToast } from "../../../components/toast";

const MAX_POLICY_N = 10;

function strength(pass: string): { label: string; width: string } {
  if (pass.length < 12) return { label: "Too short (12+ required)", width: "w-1/5" };
  let score = 1;
  if (pass.length >= 16) score++;
  if (/[A-Z]/.test(pass) && /[a-z]/.test(pass)) score++;
  if (/\d/.test(pass)) score++;
  if (/[^A-Za-z0-9]/.test(pass)) score++;
  const labels = ["Weak", "Fair", "Good", "Strong", "Excellent", "Excellent"];
  const widths = ["w-1/5", "w-2/5", "w-3/5", "w-4/5", "w-full", "w-full"];
  return { label: labels[score], width: widths[score] };
}

function ShareStep({ shares, threshold, total, stored, setStored, onFinish }: {
  shares: string[];
  threshold: number;
  total: number;
  stored: boolean[];
  setStored: (v: boolean[]) => void;
  onFinish: () => void;
}) {
  const [index, setIndex] = useState(0);
  const share = shares[index];
  const allStored = stored.length > 0 && stored.every(Boolean);
  return (
    <div className="flex flex-col gap-4">
      <div className="surface-lg py-8 text-center">
        <p className="supporting">Protect your recovery key</p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight">
          Your vault key has been split into {total} independent recovery shares.
        </h2>
        <p className="supporting mt-2">Any {threshold} {threshold === 1 ? "share can" : "shares can"} recover your vault.</p>
        <p className="mx-auto mt-4 inline-flex items-center gap-2 rounded-full bg-raised px-4 py-1.5 text-sm font-medium">
          {threshold} of {total} required
        </p>
      </div>

      <div className="surface-lg">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold">Share {index + 1} of {total}</p>
          <div className="flex gap-1.5">
            {shares.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIndex(i)}
                aria-label={`Go to share ${i + 1}`}
                className={clsx(
                  "h-2 rounded-full transition-all",
                  i === index ? "w-6 bg-accent" : stored[i] ? "w-2 bg-success" : "w-2 bg-raised",
                )}
              />
            ))}
          </div>
        </div>
        <code data-testid={`share-${index + 1}`} className="mt-3 block break-all rounded-xl bg-raised p-4 font-mono text-xs leading-relaxed">{share}</code>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <CopyButton text={share} label="Copy" />
          <button
            type="button"
            className={clsx("btn-ghost text-xs", stored[index] && "!border-success/40 !text-success")}
            onClick={() => setStored(stored.map((v, j) => (j === index ? !v : v)))}
            aria-pressed={stored[index]}
          >
            <Check className="h-3.5 w-3.5" />
            {stored[index] ? "Stored ✓" : "I've stored this safely"}
          </button>
        </div>
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            className="btn-ghost text-sm"
            disabled={index === 0}
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
          >
            <ArrowLeft className="h-4 w-4" />
            Previous
          </button>
          {index < shares.length - 1 ? (
            <button type="button" className="btn-primary text-sm" disabled={!stored[index]} onClick={() => setIndex((i) => i + 1)}>
              Next share
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button type="button" className="btn-primary text-sm" disabled={!allStored} onClick={onFinish}>
              <ShieldCheck className="h-4 w-4" />
              Complete setup
            </button>
          )}
        </div>
      </div>

      <div className="surface-lg">
        <p className="text-sm font-medium">Recovery setup</p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {shares.map((_, i) => (
            <li key={i} className="flex items-center justify-between text-sm">
              <span className="text-muted">Share {i + 1}</span>
              <span className={stored[i] ? "font-medium text-success" : "text-faint"}>
                {stored[i] ? "✓ Stored" : "○ Pending"}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-faint">
          Copy each share and store it out-of-band — paper, a safe, or with trusted people.
          Storing all shares in one place defeats the purpose.
        </p>
      </div>
    </div>
  );
}

export default function VaultSetupPage() {
  const router = useRouter();
  const { notify } = useToast();
  const [step, setStep] = useState(1);
  const [threshold, setThreshold] = useState(2);
  const [total, setTotal] = useState(3);
  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [shares, setShares] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [stored, setStored] = useState<boolean[]>([]);
  const [ceremonyId, setCeremonyId] = useState<number | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    getCryptoMaterial().then((mat) => {
      if (mat.wrapped_vmk) { router.replace("/vault"); return; }
      setReady(true);
    }).catch((e) => {
      if (e instanceof Error && /404/.test(e.message)) setReady(true);
      else setErr("Sign in before creating a vault.");
    });
    return () => lockVault();
  }, [router]);

  async function onFinish() {
    if (!ceremonyId) return;
    setBusy(true);
    try {
      await finalizeCeremony(ceremonyId, stored.map((ok, i) => ok ? i + 1 : 0).filter(Boolean));
      setShares([]); setStored([]); lockVault(); router.push("/vault");
    } catch (e) { setErr(e instanceof Error ? e.message : "Finalization failed"); }
    finally { setBusy(false); }
  }

  const s = strength(passphrase);
  const canContinue = passphrase.length >= 12 && passphrase === confirm;
  const policyValid =
    Number.isInteger(threshold) &&
    Number.isInteger(total) &&
    threshold >= 1 &&
    total >= 1 &&
    threshold <= total &&
    total <= MAX_POLICY_N;

  useEffect(()=>subscribe(()=>{if(!isUnlocked()){setShares([]);setStored([]);setPassphrase("");setConfirm("");setStep(1);}}),[]);

  async function onGenerate() {
    const before=currentEpoch();
    setErr("");
    setBusy(true);
    try {
      const { material, shares: freshShares, generation } = await setupVault(
        passphrase,
        threshold,
        total,
      );
      // Single-writer: ceremony owns (k/n/generation) first, then material only.
      const draft = await postRecoveryCeremony({
        expected_revision: 0,
        recovery_threshold: threshold,
        recovery_total: total,
        recovery_generation: generation,
        initial_material: {
        expected_revision: 0,
        wrapped_vmk: material.wrapped_vmk_b64,
        vmk_crypto_version: CRYPTO_VERSION,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt: material.vmk_kdf_salt_b64,
        vmk_kdf_parameters: material.vmk_kdf_parameters,
        },
      });
      assertEpoch(before);
      setCeremonyId(draft.ceremony_id ?? null);
      setShares(freshShares);
      setStored(freshShares.map(() => false));
      // The passphrase has served its purpose (KEK derived + VMK wrapped);
      // drop both copies so a failure below doesn't leave them in state.
      setPassphrase("");
      setConfirm("");
      setStep(4);
      notify("success", "Draft created. Store every share, then complete setup.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setPassphrase(""); setConfirm("");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <p className="supporting">Vault setup</p>
      <h1 className="page-title mt-1">{step === 4 ? "Save your recovery shares" : step === 2 ? "Create your vault" : step === 3 ? "Generate your key" : "Choose your recovery policy"}</h1>

      <div className="my-6">
        <Stepper steps={["Policy", "Passphrase", "Generate", "Shares"]} current={step} />
      </div>

      {step === 1 && (
        <div className="surface-lg flex flex-col gap-4">
          <p className="text-sm leading-relaxed text-muted">
            Choose how many recovery shares to create (n) and how many are needed to
            recover (k). Any k of n shares reconstruct your vault key, locally.
            Existing vaults keep their key. Resharing never revokes old quorums.
            If setup is interrupted, restart with fresh shares and discard the abandoned set.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="total">Total shares (n)</label>
              <select
                id="total"
                className="input"
                value={String(total)}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  setTotal(n);
                  if (threshold > n) setThreshold(n);
                }}
              >
                {Array.from({ length: MAX_POLICY_N }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="threshold">Required shares (k)</label>
              <select
                id="threshold"
                className="input"
                value={String(threshold)}
                onChange={(e) => setThreshold(Number(e.target.value))}
              >
                {Array.from({ length: total }, (_, i) => i + 1).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-sm text-muted" aria-live="polite">
            Policy: <strong className="text-text">{threshold}-of-{total}</strong>
            {threshold === 1 && " — any single share recovers (convenient, less safe)."}
            {threshold === total && total > 1 && " — all shares required (no redundancy)."}
          </p>
          <button type="button" className="btn-primary self-end" disabled={!policyValid} onClick={() => setStep(2)}>
            Continue
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="surface-lg flex flex-col gap-4">
          <p className="text-sm leading-relaxed text-muted">
            This passphrase protects the key to your private messages. It never leaves this browser.
          </p>
          <div>
            <label className="label" htmlFor="pass">Vault passphrase</label>
            <input
              id="pass"
              type="password"
              className="input"
              autoComplete="new-password"
              placeholder="12+ characters"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
            />
            {passphrase && (
              <div className="mt-2">
                <div className="h-1.5 rounded-full bg-raised">
                  <div className={clsx("h-1.5 rounded-full bg-accent transition-all", s.width)} />
                </div>
                <p className="mt-1 text-xs text-muted" aria-live="polite">{s.label}</p>
              </div>
            )}
          </div>
          <div>
            <label className="label" htmlFor="confirm">Confirm passphrase</label>
            <input
              id="confirm"
              type="password"
              className="input"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            {confirm && passphrase !== confirm && (
              <p className="mt-1 text-xs text-danger">Passphrases do not match.</p>
            )}
          </div>
          <p className="text-xs leading-relaxed text-faint">
            Your login password and vault passphrase serve different purposes.
          </p>
          <div className="flex justify-between">
            <button type="button" className="btn-ghost" onClick={() => setStep(1)}>
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button type="button" className="btn-primary" disabled={!canContinue} onClick={() => setStep(3)}>
              Continue
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="surface-lg flex flex-col items-center gap-4 py-10 text-center">
          <span className={clsx(
            "flex h-14 w-14 items-center justify-center rounded-full bg-raised",
            busy && "motion-safe:animate-pulse",
          )} aria-hidden="true">
            <KeyRound className="h-6 w-6 text-accent" />
          </span>
          <div>
            <h2 className="font-semibold">{busy ? "Creating your private vault" : "Generate your vault key"}</h2>
            <p className="mx-auto mt-1 max-w-sm text-sm leading-relaxed text-muted">
              {busy
                ? "A unique vault key is being created locally. Your key will never be sent to LegacyLock."
                : `Your browser will generate a random 256-bit vault key, split it into ${total} shares (any ${threshold} recover), and upload only the wrapped key.`}
            </p>
          </div>
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => setStep(2)}>
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button type="button" className="btn-primary" disabled={busy || !ready} onClick={onGenerate}>
              {busy && <Spinner />}
              {busy ? "Generating…" : "Generate vault key"}
            </button>
          </div>
        </div>
      )}

      {step === 4 && (
        <ShareStep
          shares={shares}
          threshold={threshold}
          total={total}
          stored={stored}
          setStored={setStored}
          onFinish={onFinish}
        />
      )}
      {step === 4 && err && <p role="alert" className="text-danger">{err}</p>}
    </main>
  );
}
