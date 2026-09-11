"use client";

// Vault setup wizard (Flow I/H): passphrase -> generate -> share ceremony.
// VMK is generated in-browser; the server only stores the wrapped VMK.
// Shares display ONCE for out-of-band distribution and are never transmitted.
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import { clsx } from "clsx";
import { CRYPTO_VERSION, createWrappedVmk } from "../../../lib/crypto";
import { splitVMK } from "../../../lib/shamir";
import { putCryptoMaterial } from "../../../lib/client";
import { useVault } from "../../../lib/store/vault-context";
import { CopyButton, Spinner } from "../../../components/ui";
import { useToast } from "../../../components/toast";

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

export default function VaultSetupPage() {
  const router = useRouter();
  const { notify } = useToast();
  const { setVMK } = useVault();
  const [step, setStep] = useState(1);
  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [shares, setShares] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [stored, setStored] = useState([false, false, false]);

  const s = strength(passphrase);
  const canContinue = passphrase.length >= 12 && passphrase === confirm;

  async function onGenerate() {
    setErr("");
    setBusy(true);
    try {
      const { vmk, material } = await createWrappedVmk(passphrase);
      await putCryptoMaterial({
        wrapped_vmk: material.wrapped_vmk_b64,
        vmk_crypto_version: CRYPTO_VERSION,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt: material.vmk_kdf_salt_b64,
        vmk_kdf_parameters: material.vmk_kdf_parameters,
      });
      setShares(splitVMK(vmk));
      setVMK(vmk);
      // The passphrase has served its purpose (KEK derived + VMK wrapped);
      // drop both copies so a failure below doesn't leave them in state.
      setPassphrase("");
      setConfirm("");
      setStep(3);
      notify("success", "Vault created. Store your shares now.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }

  function downloadShares() {
    const blob = new Blob(
      [[`LegacyLock recovery shares (2 of 3 required)\nStored: ${new Date().toISOString()}\n\n`, ...shares.map((s, i) => `Share ${i + 1}:\n${s}\n\n`)].join("")],
      { type: "text/plain" },
    );
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "legacylock-shares.txt";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-bold">Vault setup</h1>

      {/* Stepper */}
      <ol className="my-6 flex items-center gap-2 text-sm" aria-label="Setup progress">
        {["Passphrase", "Generate", "Shares"].map((label, i) => (
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
              {step > i + 1 ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span className={step === i + 1 ? "text-text" : "text-muted"}>{label}</span>
            {i < 2 && <span className="mx-1 text-faint">—</span>}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div className="card flex flex-col gap-4">
          <p className="text-sm text-muted">
            This passphrase unlocks your vault keys. It must be distinct from your login
            password and is never sent to the server.
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
                <div className="h-1.5 rounded bg-raised">
                  <div className={clsx("h-1.5 rounded bg-accent transition-all", s.width)} />
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
          <button type="button" className="btn-primary self-end" disabled={!canContinue} onClick={() => setStep(2)}>
            Continue
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="card flex flex-col items-start gap-4">
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-accent" />
            <h2 className="font-semibold">Generate your vault key</h2>
          </div>
          <p className="text-sm text-muted">
            Your browser will generate a random 256-bit vault key, split it into 3 Shamir
            shares (any 2 recover), and upload only the wrapped key. This takes a moment.
          </p>
          {err && <p role="alert" className="text-sm text-danger">{err}</p>}
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => setStep(1)}>
              <ArrowLeft className="h-4 w-4" />
              Back
            </button>
            <button type="button" className="btn-primary" disabled={busy} onClick={onGenerate}>
              {busy && <Spinner />}
              {busy ? "Generating…" : "Generate vault key"}
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <div className="card border-warn">
            <p className="flex items-start gap-2 text-sm">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
              <span>
                <strong>Write these down now — shown once.</strong> Any 2 of 3 shares
                recover your vault. Distribute them out-of-band (paper, safe, trusted people).
                LegacyLock never transmits raw shares.
              </span>
            </p>
          </div>
          {shares.map((share, i) => (
            <div key={i} className="card flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold">Share {i + 1} of 3</span>
                <CopyButton text={share} />
              </div>
              <code data-testid={`share-${i + 1}`} className="break-all rounded-md bg-raised p-3 font-mono text-xs">{share}</code>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[#d4af37]"
                  checked={stored[i]}
                  onChange={() => setStored((prev) => prev.map((v, j) => (j === i ? !v : v)))}
                />
                I have stored share {i + 1} somewhere safe
              </label>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-ghost" onClick={downloadShares}>
              <Download className="h-4 w-4" />
              Download shares (.txt)
            </button>
            <button
              type="button"
              className="btn-primary ml-auto"
              disabled={!stored.every(Boolean)}
              onClick={() => router.push("/vault")}
            >
              <ShieldCheck className="h-4 w-4" />
              Finish — open my vault
            </button>
          </div>
          {!stored.every(Boolean) && (
            <p className="text-xs text-faint">Confirm all three shares are stored to continue.</p>
          )}
        </div>
      )}
    </main>
  );
}
