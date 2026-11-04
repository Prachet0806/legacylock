"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Link2, Send, UserPlus, UserX, Users } from "lucide-react";
import { clsx } from "clsx";
import {
  addBeneficiary,
  assignShare,
  deleteBeneficiary,
  getRecoveryPolicy,
  inviteBeneficiary,
  listBeneficiaries,
  type Beneficiary,
} from "../../lib/client";
import { Avatar, CopyButton, EmptyState, Modal, Spinner, StatusChip } from "../../components/ui";
import { RecoveryReadiness } from "../../components/vault-ui";
import { useToast } from "../../components/toast";

function statusTone(s: string): "success" | "warn" | "neutral" {
  return s === "accepted" ? "success" : s === "sent" ? "warn" : "neutral";
}

function lifecycle(b: Beneficiary): { label: string; done: boolean }[] {
  return [
    { label: "Added", done: true },
    { label: "Current share assigned", done: b.assignment_current },
    { label: "Invitation sent", done: b.invitation_status === "sent" || b.invitation_status === "accepted" },
    { label: "Accepted", done: b.invitation_status === "accepted" },
    { label: "Enrolled and assigned", done: b.invitation_status === "accepted" && b.assignment_current },
  ];
}

function ShareAssign({
  b,
  total,
  onAssigned,
}: {
  b: Beneficiary;
  total: number;
  onAssigned: () => void;
}) {
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
    <span className="flex items-center gap-1.5">
      <select
        className="input !w-auto !rounded-lg px-2 py-1.5 text-xs"
        value={idx}
        onChange={(e) => setIdx(e.target.value)}
        aria-label={`Share index for ${b.name}`}
        title="Which recovery share this person receives"
      >
        <option value="">Share…</option>
        {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
      <button type="button" className="btn-ghost !rounded-lg px-2.5 py-1.5 text-xs" disabled={!idx} onClick={onClick}>
        Assign
      </button>
    </span>
  );
}

function PersonCard({ b, total, onInvite, onRemove, onAssigned }: {
  b: Beneficiary;
  total: number;
  onInvite: () => void;
  onRemove: () => void;
  onAssigned: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const steps = lifecycle(b);
  const ready = b.invitation_status === "accepted" && b.assignment_current;
  return (
    <li className="surface-lg !p-5">
      <div className="flex items-center gap-3">
        <Avatar name={b.name} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{b.name}</p>
          <p className="truncate text-xs text-faint">{b.email}</p>
        </div>
        <StatusChip tone={ready ? "success" : statusTone(b.invitation_status)}>
          {ready ? "● Ready" : b.invitation_status}
        </StatusChip>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {b.assignment_current ? (
          <span className="chip !border-success/30 !text-success">Recovery share {b.share_index} · Assigned ✓</span>
        ) : (
          <ShareAssign b={b} total={total} onAssigned={onAssigned} />
        )}
        <span className="text-faint">
          {b.invitation_status === "accepted" ? "Invitation accepted" : b.invitation_status === "sent" ? "Invitation sent" : "Not yet invited"}
        </span>
        <button
          type="button"
          className="ml-auto inline-flex items-center gap-1 font-medium text-muted hover:text-text"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          Manage
          <ArrowRight className={clsx("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")} />
        </button>
      </div>

      {/* Lifecycle */}
      <ol className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]" aria-label={`Setup progress for ${b.name}`}>
        {steps.map((s, i) => (
          <li key={s.label} className="flex items-center gap-1.5">
            <span className={clsx("font-medium", s.done ? "text-success" : "text-faint")}>
              {s.done ? "●" : "○"} {s.label}
            </span>
            {i < steps.length - 1 && <span className="text-faint">→</span>}
          </li>
        ))}
      </ol>

      {expanded && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
          <button type="button" className="btn-ghost !rounded-lg px-2.5 py-1.5 text-xs" title="Send invitation" onClick={onInvite}>
            <Send className="h-3.5 w-3.5" />
            Invite
          </button>
          <button
            type="button"
            className="btn-ghost !rounded-lg px-2.5 py-1.5 text-xs hover:!border-danger/50 hover:text-danger"
            aria-label={`Remove ${b.name}`}
            title="Remove"
            onClick={onRemove}
          >
            <UserX className="h-3.5 w-3.5" />
            Remove
          </button>
        </div>
      )}
    </li>
  );
}

export default function BeneficiariesPage() {
  const { notify } = useToast();
  const [rows, setRows] = useState<Beneficiary[]>([]);
  const [threshold, setThreshold] = useState(2);
  const [total, setTotal] = useState(3);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [err, setErr] = useState("");
  const [link, setLink] = useState("");
  const [confirmRemove, setConfirmRemove] = useState<Beneficiary | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const [list, policy] = await Promise.all([listBeneficiaries(), getRecoveryPolicy().catch(() => null)]);
      setRows(list);
      if (policy) {
        setThreshold(policy.recovery_threshold);
        setTotal(policy.recovery_total);
      }
    } finally {
      setLoading(false);
    }
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
      setShowAdd(false);
      await refresh();
      notify("success", "Trusted person added.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Add failed");
    }
  }

  async function onInvite(b: Beneficiary) {
    try {
      const r = await inviteBeneficiary(b.id);
      setLink(r.invitation_link ?? "");
      await refresh();
      notify("success", r.invitation_link ? `Invitation link ready for ${b.name}.` : `Invitation email queued for ${b.name}.`);
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
      notify("success", "Trusted person removed.");
    } catch {
      notify("error", "Remove failed.");
    }
  }

  // Cryptographic readiness counts assigned share indexes, not beneficiary
  // rows: a vault is recoverable once at least k shares have a distribution
  // path. Full distribution (all n assigned) is recommended but not required.
  const assigned = rows.filter((b) => b.assignment_current && b.invitation_status === "accepted").length;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="supporting">Beneficiaries</p>
          <h1 className="page-title mt-1">People</h1>
          <p className="supporting mt-2">People you trust to receive your legacy.</p>
        </div>
        <button type="button" className="btn-primary text-sm" onClick={() => setShowAdd((v) => !v)}>
          <UserPlus className="h-4 w-4" />
          Add person
        </button>
      </div>

      <div className="mt-6">
        <RecoveryReadiness assigned={assigned} threshold={threshold} total={total} />
        <p className="mt-2 text-center text-xs text-faint">
          Assignment metadata · {threshold} of {total} {total === 1 ? "person" : "people"} required
        </p>
      </div>

      {showAdd && (
        <div className="surface-lg mt-4">
          <h2 className="flex items-center gap-2 font-semibold">
            <UserPlus className="h-4 w-4 text-accent" />
            Add person
          </h2>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <div className="flex-1">
              <label className="label" htmlFor="ben-name">Name</label>
              <input id="ben-name" className="input" placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="flex-1">
              <label className="label" htmlFor="ben-email">Email</label>
              <input id="ben-email" className="input" placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <button type="button" className="btn-primary shrink-0 self-end" onClick={onAdd}>
              Add
            </button>
          </div>
          {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
        </div>
      )}

      <div className="mt-4">
        {loading ? (
          <div className="surface-lg flex items-center gap-2 text-sm text-muted" aria-busy="true" aria-label="Loading trusted people">
            <Spinner />
            Loading trusted people…
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Users className="h-6 w-6" />}
            title="No trusted people yet"
            hint="Add the people who should receive your vault if you go inactive. They receive an invitation email. Distribute their recovery shares separately."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {rows.map((b) => (
              <PersonCard
                key={b.id}
                b={b}
                total={total}
                onInvite={() => onInvite(b)}
                onRemove={() => setConfirmRemove(b)}
                onAssigned={refresh}
              />
            ))}
          </ul>
        )}
      </div>

      {link && (
        <div className="surface-lg mt-4 flex flex-col gap-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Link2 className="h-4 w-4 text-accent" />
            Invitation link — send it yourself, out-of-band
          </p>
          <code className="break-all rounded-xl bg-raised p-3 font-mono text-xs">{link}</code>
          <div><CopyButton text={link} label="Copy link" /></div>
        </div>
      )}

      {confirmRemove && (
        <Modal title="Remove trusted person" onClose={() => setConfirmRemove(null)}>
          <p className="text-sm leading-relaxed text-muted">
            Remove <strong className="text-text">{confirmRemove.name}</strong>? Their
            invitation is revoked. Note: a share already handed out cannot be unshared —
            removing an assignment or resharing the same key cannot revoke an old quorum.
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
