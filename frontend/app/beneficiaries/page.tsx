"use client";

import { useEffect, useState } from "react";
import { Link2, Send, UserPlus, UserX, Users } from "lucide-react";
import {
  addBeneficiary,
  assignShare,
  deleteBeneficiary,
  inviteBeneficiary,
  listBeneficiaries,
  type Beneficiary,
} from "../../lib/client";
import { CopyButton, EmptyState, Modal, StatusChip } from "../../components/ui";
import { useToast } from "../../components/toast";

function statusTone(s: string): "success" | "warn" | "neutral" {
  return s === "accepted" ? "success" : s === "sent" ? "warn" : "neutral";
}

function ShareAssign({ b, onAssigned }: { b: Beneficiary; onAssigned: () => void }) {
  const { notify } = useToast();
  const [idx, setIdx] = useState<string>(b.share_index != null ? String(b.share_index) : "");
  async function onClick() {
    try {
      await assignShare(b.id, Number(idx));
      notify("success", `${b.name} assigned share ${idx}.`);
      onAssigned();
    } catch {
      notify("error", "Share index already taken or invalid.");
    }
  }
  return (
    <span className="flex items-center gap-1">
      <select
        className="input !w-auto px-1 py-1 text-xs"
        value={idx}
        onChange={(e) => setIdx(e.target.value)}
        aria-label={`Share index for ${b.name}`}
        title="Which Shamir share this beneficiary receives"
      >
        <option value="">Share…</option>
        <option value="1">1</option>
        <option value="2">2</option>
        <option value="3">3</option>
      </select>
      <button type="button" className="btn-ghost px-2 py-1 text-xs" disabled={!idx} onClick={onClick}>
        Assign
      </button>
    </span>
  );
}

export default function BeneficiariesPage() {
  const { notify } = useToast();
  const [rows, setRows] = useState<Beneficiary[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [link, setLink] = useState("");
  const [confirmRemove, setConfirmRemove] = useState<Beneficiary | null>(null);

  async function refresh() {
    setRows(await listBeneficiaries());
  }
  useEffect(() => {
    refresh().catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  async function onAdd() {
    setErr("");
    try {
      await addBeneficiary({ name: name.trim(), email: email.trim() });
      setName("");
      setEmail("");
      await refresh();
      notify("success", "Beneficiary added.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Add failed");
    }
  }

  async function onInvite(b: Beneficiary) {
    try {
      const r = await inviteBeneficiary(b.id);
      setLink(r.invitation_link);
      await refresh();
      notify("success", `Invitation ready for ${b.name}.`);
    } catch {
      notify("error", "Invite failed.");
    }
  }

  async function onRemove() {
    if (!confirmRemove) return;
    try {
      await deleteBeneficiary(confirmRemove.id);
      setConfirmRemove(null);
      await refresh();
      notify("success", "Beneficiary removed.");
    } catch {
      notify("error", "Remove failed.");
    }
  }

  const ready = rows.length >= 3;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-2 flex items-center gap-3">
        <h1 className="text-2xl font-bold">Beneficiaries</h1>
        <span className="chip">{rows.length} of 3 needed for 2-of-3</span>
      </div>
      <p className="mb-6 text-sm text-muted">
        Each beneficiary receives one Shamir share index. Recovery needs any 2 of 3 —
        configure at least three people you trust.
      </p>

      {!ready && (
        <div className="card mb-4 border-warn text-sm">
          Add {3 - rows.length} more {rows.length === 2 ? "beneficiary" : "beneficiaries"} to
          reach a 2-of-3 recovery policy.
        </div>
      )}

      <div className="card mb-6">
        <h2 className="mb-3 flex items-center gap-2 font-semibold">
          <UserPlus className="h-4 w-4 text-accent" />
          Add beneficiary
        </h2>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input" placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
          <input className="input" placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
          <button type="button" className="btn-primary shrink-0" onClick={onAdd}>
            Add
          </button>
        </div>
        {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<Users className="h-8 w-8" />}
          title="No beneficiaries yet"
          hint="Add the people who should receive your vault if you go inactive. They'll each get an invitation link and a recovery share."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((b) => (
            <li key={b.id} className="card flex items-center gap-3 !p-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-raised text-sm font-semibold text-accent">
                {b.name.slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{b.name}</p>
                <p className="truncate text-xs text-faint">{b.email}</p>
              </div>
              <StatusChip tone={statusTone(b.invitation_status)}>{b.invitation_status}</StatusChip>
              {b.share_index != null ? (
                <span className="chip">Share {b.share_index}</span>
              ) : (
                <ShareAssign b={b} onAssigned={refresh} />
              )}
              <button type="button" className="btn-ghost px-2 py-1 text-xs" title="Send invitation" onClick={() => onInvite(b)}>
                <Send className="h-3.5 w-3.5" />
                Invite
              </button>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                title="Remove"
                onClick={() => setConfirmRemove(b)}
              >
                <UserX className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {link && (
        <div className="card mt-4 flex flex-col gap-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Link2 className="h-4 w-4 text-accent" />
            Invitation link — send it yourself, out-of-band
          </p>
          <code className="break-all rounded-md bg-raised p-3 font-mono text-xs">{link}</code>
          <div><CopyButton text={link} label="Copy link" /></div>
        </div>
      )}

      {confirmRemove && (
        <Modal title="Remove beneficiary" onClose={() => setConfirmRemove(null)}>
          <p className="text-sm text-muted">
            Remove <strong className="text-text">{confirmRemove.name}</strong>? Their
            invitation is revoked. Note: a share already handed out cannot be unshared —
            rotate your recovery setup afterwards if needed.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost text-sm" onClick={() => setConfirmRemove(null)}>
              Cancel
            </button>
            <button type="button" className="btn-danger text-sm" onClick={onRemove}>
              Remove
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
