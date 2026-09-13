"use client";

// Settings: vault-passphrase change (re-wraps the SAME VMK) and danger-zone
// vault wipe (deletes all encrypted messages, requires login password).
import { useState } from "react";
import { AlertOctagon, KeyRound, Trash2 } from "lucide-react";
import { CRYPTO_VERSION, rewrap } from "../../lib/crypto-session";
import { putCryptoMaterial, wipeVault } from "../../lib/client";
import { useVault } from "../../lib/store/vault-context";
import { Modal, Spinner } from "../../components/ui";
import { useToast } from "../../components/toast";

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
      const material = await rewrap(newPass);
      await putCryptoMaterial({
        wrapped_vmk: material.wrapped_vmk_b64,
        vmk_crypto_version: CRYPTO_VERSION,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt: material.vmk_kdf_salt_b64,
        vmk_kdf_parameters: material.vmk_kdf_parameters,
      });
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
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold">Settings</h1>

      <div className="card mb-4 flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-semibold">
          <KeyRound className="h-4 w-4 text-accent" />
          Change vault passphrase
        </h2>
        <p className="text-sm text-muted">
          Re-wraps your existing vault key with a new passphrase. Messages are not
          re-encrypted and shares stay valid. Requires the vault to be unlocked.
        </p>
        <div>
          <label className="label" htmlFor="new-pass">New passphrase (12+ chars)</label>
          <input id="new-pass" type="password" className="input" autoComplete="new-password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="new-pass-confirm">Confirm new passphrase</label>
          <input id="new-pass-confirm" type="password" className="input" autoComplete="new-password" value={confirmPass} onChange={(e) => setConfirmPass(e.target.value)} />
        </div>
        <div>
          <button type="button" className="btn-primary text-sm" disabled={busy || !unlocked} onClick={onRewrap}>
            {busy && <Spinner />}
            Change passphrase
          </button>
          {!unlocked && <p className="mt-1 text-xs text-faint">Unlock your vault first.</p>}
        </div>
      </div>

      <div className="card border-danger">
        <h2 className="mb-1 flex items-center gap-2 font-semibold text-danger">
          <AlertOctagon className="h-4 w-4" />
          Danger zone
        </h2>
        <p className="mb-3 text-sm text-muted">
          Permanently delete every encrypted message in your vault. This cannot be undone.
        </p>
        <button type="button" className="btn-danger text-sm" onClick={() => setShowWipe(true)}>
          <Trash2 className="h-4 w-4" />
          Wipe all messages…
        </button>
      </div>

      {showWipe && (
        <Modal title="Wipe all messages?" onClose={() => setShowWipe(false)}>
          <p className="mb-4 text-sm text-muted">
            Type <code className="rounded bg-raised px-1 font-mono">WIPE</code> and enter your
            login password to confirm permanent deletion.
          </p>
          <label className="label" htmlFor="wipe-text">Type WIPE to confirm</label>
          <input id="wipe-text" className="input" value={wipeText} onChange={(e) => setWipeText(e.target.value)} />
          <label className="label mt-3" htmlFor="wipe-pass">Login password</label>
          <input id="wipe-pass" type="password" className="input" autoComplete="current-password" value={wipePass} onChange={(e) => setWipePass(e.target.value)} />
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost text-sm" onClick={() => setShowWipe(false)}>
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
