"use client";

// Settings: vault-passphrase change (re-wraps the SAME VMK) and danger-zone
// vault wipe (deletes all encrypted messages, requires login password).
import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertOctagon, ArrowRight, KeyRound, Lock, ShieldCheck, Trash2 } from "lucide-react";
import { CRYPTO_VERSION, assertEpoch, currentEpoch, materialRevision, rewrap, subscribe, isUnlocked } from "../../lib/crypto-session";
import { putCryptoMaterial, wipeVault } from "../../lib/client";
import { useVault } from "../../lib/store/vault-context";
import { Modal, Spinner } from "../../components/ui";
import { useToast } from "../../components/toast";
import {sessionChanged} from "../../lib/api/transport";

export default function SettingsPage() {
  const { notify } = useToast();
    const { unlocked } = useVault();
  const [newPass, setNewPass] = useState("");
  const [confirmPass, setConfirmPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [wipePass, setWipePass] = useState("");
  const [wipeText, setWipeText] = useState("");
  const [showWipe, setShowWipe] = useState(false);
  const [wiping, setWiping] = useState(false);
  useEffect(() => subscribe(() => { if(!isUnlocked()) {setNewPass("");setConfirmPass("");setWipePass("");setWipeText("");setShowWipe(false);} }),[]);

  async function onRewrap() {
    if (newPass.length < 12) {
      notify("error", "New passphrase must be 12+ characters.");
      return;
    }
    if (newPass !== confirmPass) {
      notify("error", "Passphrases do not match.");
      return;
    }
    if (!unlocked) {
      notify("error", "Unlock your vault first (Vault page).");
      return;
    }
    setBusy(true);
    try {
      const before = currentEpoch();
      const revision = materialRevision();
      const material = await rewrap(newPass);
      assertEpoch(before);
      await putCryptoMaterial({
        expected_revision: revision,
        wrapped_vmk: material.wrapped_vmk_b64,
        vmk_crypto_version: CRYPTO_VERSION,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt: material.vmk_kdf_salt_b64,
        vmk_kdf_parameters: material.vmk_kdf_parameters,
      });
      sessionChanged();
      notify("success", "Passphrase changed. Same vault key, new wrapping.");
    } catch {
      notify("error", "Passphrase change failed.");
    } finally {
      // Drop both copies from state whether it worked or not.
      setNewPass("");
      setConfirmPass("");
      setBusy(false);
    }
  }

  async function onWipe() {
    setWiping(true);
    try {
      await wipeVault(wipePass);
      setShowWipe(false);
      setWipePass("");
      setWipeText("");
      notify("success", "All messages wiped.");
    } catch {
      notify("error", "Wipe failed — wrong password?");
    } finally {
      setWiping(false);
      setWipePass(""); setWipeText("");
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="page-title">Settings</h1>
      <Link className="btn-ghost mt-4" href="/vault/reshare">Create a new recovery distribution</Link>

      <section className="surface-lg mt-6" aria-label="Security">
        <p className="eyebrow">Security</p>
        <div className="mt-4 flex flex-col gap-1">
          <div className="flex items-center gap-3 py-3">
            <KeyRound className="h-4 w-4 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">Vault passphrase</p>
              <p className="text-xs text-faint">Protects the key to your messages</p>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="new-pass">New passphrase (12+ chars)</label>
            <input id="new-pass" type="password" className="input" autoComplete="new-password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
          </div>
          <div className="mt-2">
            <label className="label" htmlFor="new-pass-confirm">Confirm new passphrase</label>
            <input id="new-pass-confirm" type="password" className="input" autoComplete="new-password" value={confirmPass} onChange={(e) => setConfirmPass(e.target.value)} />
          </div>
          <div className="mt-3">
            <button type="button" className="btn-primary text-sm" disabled={busy || !unlocked} onClick={onRewrap}>
              {busy && <Spinner />}
              Change passphrase
            </button>
            {!unlocked && <p className="mt-1.5 text-xs text-faint">Unlock your vault first.</p>}
          </div>

          <div className="mt-2 flex items-center gap-3 border-t border-border py-3">
            <Lock className="h-4 w-4 shrink-0 text-muted" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">Session</p>
              <p className="text-xs text-faint">Vault locks automatically when this tab closes</p>
            </div>
          </div>

          <Link href="/settings/security" className="flex items-center gap-3 border-t border-border py-3 transition-colors hover:text-text">
            <ShieldCheck className="h-4 w-4 shrink-0 text-success" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">Privacy & zero-knowledge architecture</p>
              <p className="text-xs text-faint">How your data stays private</p>
            </div>
            <ArrowRight className="h-4 w-4 text-faint" />
          </Link>
        </div>
      </section>

      <section className="surface-lg mt-4 !border-danger/50" aria-label="Danger zone">
        <h2 className="flex items-center gap-2 font-semibold text-danger">
          <AlertOctagon className="h-4 w-4" />
          Danger zone
        </h2>
        <p className="supporting mt-1">
          Delete vault contents — permanently erase all encrypted messages. This cannot be undone.
        </p>
        <button type="button" className="btn-danger mt-3 text-sm" onClick={() => setShowWipe(true)}>
          <Trash2 className="h-4 w-4" />
          Delete →
        </button>
      </section>

      {showWipe && (
        <Modal title="Wipe all messages?" onClose={() => { setShowWipe(false); setWipePass(""); setWipeText(""); }}>
          <p className="mb-4 text-sm leading-relaxed text-muted">
            Type <code className="rounded-lg bg-raised px-1.5 py-0.5 font-mono">WIPE</code> and enter your
            login password to confirm permanent deletion.
          </p>
          <label className="label" htmlFor="wipe-text">Type WIPE to confirm</label>
          <input id="wipe-text" className="input" value={wipeText} onChange={(e) => setWipeText(e.target.value)} />
          <label className="label mt-3" htmlFor="wipe-pass">Login password</label>
          <input id="wipe-pass" type="password" className="input" autoComplete="current-password" value={wipePass} onChange={(e) => setWipePass(e.target.value)} />
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost text-sm" onClick={() => { setShowWipe(false); setWipePass(""); setWipeText(""); }}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger text-sm"
              disabled={wiping || wipeText !== "WIPE" || !wipePass}
              onClick={onWipe}
            >
              {wiping && <Spinner />}
              Wipe everything
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
